"""Shared helpers for the authenticated JSON APIs.

Every data endpoint:
    * is rate limited (per IP, in-memory sliding window),
    * rejects state-changing calls without a valid CSRF token,
    * converts domain errors into friendly JSON (never a stack trace),
    * wraps unexpected failures in a generic 500 message.
"""

from __future__ import annotations

import functools
import logging
import os

from flask import jsonify, request

from services.rate_limiter import SlidingWindowLimiter

logger = logging.getLogger("api")

# Generous ceiling for dashboard traffic (pages load several endpoints).
_data_limiter = SlidingWindowLimiter(int(os.environ.get("DATA_RATE_LIMIT_PER_MINUTE", "240")), 60)
# Stricter ceiling for expensive/AI endpoints.
_ai_limiter = SlidingWindowLimiter(int(os.environ.get("AI_RATE_LIMIT_PER_MINUTE", "20")), 60)

GENERIC_ERROR = "Something went wrong on our side. Please try again."


def ok(data=None, status: int = 200):
    return jsonify({"success": True, "data": data if data is not None else {}}), status


def fail(message: str, status: int = 400, fields=None):
    payload = {"success": False, "error": {"message": message}}
    if fields:
        payload["error"]["fields"] = fields
    return jsonify(payload), status


def _client_key() -> str:
    return request.remote_addr or "unknown"


def data_api(write: bool = False, ai: bool = False):
    """Guard decorator: rate limit → CSRF (writes only) → friendly errors."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            from services.web_security import csrf_ok

            limiter = _ai_limiter if ai else _data_limiter
            if not limiter.allow(_client_key()):
                return fail("Too many requests. Please slow down and try again.", 429)
            if write and not csrf_ok():
                return fail("Your session expired. Please refresh the page and try again.", 403)
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # domain errors carry .message/.status
                message = getattr(exc, "message", None)
                status = getattr(exc, "status", None)
                if message:
                    logger.info("Handled API error on %s: %s", request.path, message)
                    return fail(str(message), int(status or 400))
                if isinstance(exc, (ValueError, LookupError)):
                    return fail(str(exc) or "Invalid request.", 400)
                logger.exception("Unhandled error on %s", request.path)
                return fail(GENERIC_ERROR, 500)

        return wrapper

    return decorator


def json_payload() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}
