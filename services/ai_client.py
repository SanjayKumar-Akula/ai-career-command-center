"""Provider-agnostic AI client with strict JSON handling.

Providers (set AI_PROVIDER in .env):
    gemini (default) -> Google Gemini — Generative Language API
    openai           -> any OpenAI-compatible chat-completions endpoint
                        (OpenAI, Groq, OpenRouter, Together, LM Studio, ...)

The API key always stays on the server and is never sent to the frontend.
Credentials are read from .env via python-dotenv, with a fallback to the
plain system environment (e.g. GEMINI_API_KEY) if AI_API_KEY is unset.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("ai_client")

DEFAULT_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_TIMEOUT_SECONDS = 75
RETRY_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 3
PLACEHOLDER_API_KEYS = {"PASTE_MY_GEMINI_API_KEY_HERE", "your_api_key_here"}
GEMINI_FALLBACK_MODELS = ("gemini-3.5-flash-lite", "gemini-flash-lite-latest")


class AIServiceError(Exception):
    """AI failure with a user-friendly message + suggested HTTP status."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


class AIResponseError(AIServiceError):
    """The AI replied, but the payload was not usable JSON."""

    def __init__(self, message: str = "The AI service returned an unexpected response format. Please try again."):
        super().__init__(message, status=502)


def _load_config() -> dict:
    """Read AI settings from the environment (never logs or leaks values)."""
    provider = (os.environ.get("AI_PROVIDER") or "gemini").strip().lower()
    if provider not in {"gemini", "openai"}:
        provider = "gemini"

    api_key = (os.environ.get("AI_API_KEY") or "").strip()
    if api_key in PLACEHOLDER_API_KEYS:
        api_key = ""
    if not api_key:
        fallback_vars = {
            "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            "openai": ("OPENAI_API_KEY",),
        }[provider]
        for var in fallback_vars:
            api_key = (os.environ.get(var) or "").strip()
            if api_key:
                break

    default_model = {"gemini": "gemini-3.6-flash", "openai": "gpt-4o-mini"}[provider]
    model = (os.environ.get("AI_MODEL") or default_model).strip()
    base_url = (os.environ.get("AI_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        base_url = DEFAULT_GEMINI_BASE if provider == "gemini" else DEFAULT_OPENAI_BASE

    try:
        timeout = float(os.environ.get("AI_TIMEOUT") or DEFAULT_TIMEOUT_SECONDS)
    except ValueError:
        timeout = float(DEFAULT_TIMEOUT_SECONDS)

    return {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
        "timeout": timeout,
    }


def get_provider_name() -> str:
    return _load_config()["provider"]


def is_ai_configured() -> bool:
    return bool(_load_config()["api_key"])


def _safe_provider_detail(body: str, secret: str = "") -> str:
    """Extract a short provider detail without logging credentials or headers."""
    try:
        payload = json.loads(body or "")
        detail = payload.get("error", {}).get("message", "")
    except (TypeError, ValueError, json.JSONDecodeError):
        detail = body or ""
    detail = str(detail).replace("\n", " ").strip()
    if secret:
        detail = detail.replace(secret, "[REDACTED]")
    detail = re.sub(
        r"(?i)(x-goog-api-key|authorization)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        detail,
    )
    return detail[:300]


def _friendly_http_error(status: int, body: str, secret: str = "") -> AIServiceError:
    """Map an HTTP error from the AI provider to a friendly message."""
    snippet = _safe_provider_detail(body, secret)
    lowered = snippet.lower()
    if status in (401, 403) or ("api key" in lowered and status in (400, 401, 403)):
        return AIServiceError(
            "The AI service rejected the API key. Please check AI_API_KEY in your .env file.",
            status=502,
        )
    if status == 429:
        return AIServiceError(
            "The AI service is rate limited right now. Please wait a moment and try again.",
            status=429,
        )
    if 500 <= status <= 599:
        return AIServiceError(
            "The AI service is temporarily unavailable. Please try again shortly.",
            status=503,
        )
    logger.error("AI provider HTTP %s: %s", status, snippet)
    return AIServiceError("The AI service returned an error. Please try again.", status=502)


def _safe_json(response) -> dict:
    try:
        return response.json()
    except ValueError:
        raise AIResponseError("The AI service returned a non-JSON response. Please try again.")


def _call_gemini(cfg: dict, prompt: str, system, temperature: float, timeout: float, model=None) -> str:
    requested = model or cfg["model"]
    url = f"{cfg['base_url']}/models/{requested}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": cfg["api_key"]}
    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    response = requests.post(url, headers=headers, json=body, timeout=timeout)
    if response.status_code == 404 and model is None:
        # The requested model may be retired; Google's 404 message suggests a
        # replacement ("... please update your code to use models/gemini-X ...").
        matches = re.findall(r"models/([A-Za-z0-9._-]+)", response.text)
        suggestion = matches[-1] if matches else None
        if suggestion and suggestion != requested:
            logger.warning("Gemini model %s unavailable — retrying with %s", requested, suggestion)
            return _call_gemini(cfg, prompt, system, temperature, timeout, model=suggestion)
    if response.status_code >= 400:
        logger.warning(
            "Gemini request failed: status=%s model=%s host=%s detail=%s",
            response.status_code,
            requested,
            urlparse(url).hostname,
            _safe_provider_detail(response.text, cfg["api_key"]),
        )
        raise _friendly_http_error(response.status_code, response.text, cfg["api_key"])

    data = _safe_json(response)
    candidates = data.get("candidates") or []
    parts: list = []
    if candidates:
        content = candidates[0].get("content") or {}
        parts = [part.get("text", "") for part in (content.get("parts") or [])]
    text = "".join(parts).strip()
    if not text:
        finish = (candidates[0].get("finishReason") if candidates else None) or "unknown"
        logger.warning("Gemini returned no text (finishReason=%s)", finish)
        raise AIResponseError("The AI service returned an empty response. Please try again.")
    return text


def _call_openai(cfg: dict, prompt: str, system, temperature: float, timeout: float) -> str:
    url = f"{cfg['base_url']}/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"}
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }

    response = requests.post(url, headers=headers, json=body, timeout=timeout)
    if response.status_code >= 400:
        body_text = response.text[:300]
        logger.warning("OpenAI-compatible HTTP %s: %s", response.status_code, body_text)
        # Some OpenAI-compatible providers reject response_format — retry once without it.
        if response.status_code == 400 and "response_format" in body_text.lower():
            body.pop("response_format", None)
            response = requests.post(url, headers=headers, json=body, timeout=timeout)
            if response.status_code >= 400:
                logger.warning("OpenAI-compatible retry HTTP %s: %s", response.status_code, response.text[:300])
                raise _friendly_http_error(response.status_code, response.text, cfg["api_key"])
        else:
            raise _friendly_http_error(response.status_code, body_text, cfg["api_key"])

    data = _safe_json(response)
    choices = data.get("choices") or []
    text = ""
    if choices:
        text = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not text:
        raise AIResponseError("The AI service returned an empty response. Please try again.")
    return text


def call_ai(prompt: str, system=None, *, temperature: float = 0.4, timeout=None) -> str:
    """Call the configured AI provider and return plain text.

    Raises AIServiceError (with a user-friendly message) on any failure.
    Transient failures (rate limit / provider busy / network) are retried once.
    """
    cfg = _load_config()
    if not cfg["api_key"]:
        raise AIServiceError(
            "The AI service is not configured. Set AI_API_KEY (or GEMINI_API_KEY) "
            "in your .env file and restart the server.",
            status=503,
        )

    effective_timeout = timeout or cfg["timeout"]

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            if cfg["provider"] == "openai":
                return _call_openai(cfg, prompt, system, temperature, effective_timeout)
            models = [cfg["model"]]
            models.extend(model for model in GEMINI_FALLBACK_MODELS if model != cfg["model"])
            last_error = None
            for model in models:
                try:
                    return _call_gemini(
                        cfg, prompt, system, temperature, effective_timeout, model=model)
                except AIServiceError as exc:
                    last_error = exc
                    if exc.status not in (404, 429, 500, 502, 503, 504):
                        raise
                    logger.warning(
                        "Gemini model attempt unavailable: status=%s model=%s",
                        exc.status,
                        model,
                    )
            raise last_error or AIServiceError(
                "The AI service is unavailable right now. Please try again.", status=503)
        except (requests.Timeout, requests.ConnectionError) as exc:
            logger.warning("AI network error (attempt %s/%s): %s", attempt, RETRY_ATTEMPTS, exc)
            if isinstance(exc, requests.Timeout):
                # A timeout has already consumed a lot of wall-clock time —
                # fail fast instead of making the user wait through a retry.
                raise AIServiceError(
                    "The AI service took too long to respond. Please try again in a minute.",
                    status=504,
                )
            failure = AIServiceError(
                "Could not reach the AI service. Check your internet connection and try again.",
                status=503,
            )
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS)
                continue
            raise failure
        except AIServiceError as exc:
            if exc.status in (429, 503) and attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS)
                continue
            raise

    raise AIServiceError("The AI service is unavailable right now. Please try again.", status=503)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def parse_ai_json(text: str) -> dict:
    """Safely extract a JSON object from AI text (handles Markdown fences).

    Raises AIResponseError if no valid JSON object can be recovered.
    """
    if not text or not text.strip():
        raise AIResponseError("The AI service returned an empty response. Please try again.")

    candidates: list = []
    fence = _FENCE_RE.search(text)
    if fence:
        candidates.append(fence.group(1))
    candidates.append(text)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])

    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate.startswith("{"):
            continue
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            return data

    logger.error("AI response was not parseable as JSON: %.300s", text)
    raise AIResponseError()


