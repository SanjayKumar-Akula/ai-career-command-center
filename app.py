"""AI Career Guide & Resume Analyzer — Flask application.

Routes:
    GET  /                     -> single-page UI (templates/index.html)
    GET  /api/health           -> service + AI configuration health check
    POST /api/career-guide     -> AI-generated career roadmap (JSON body)
    POST /api/resume-analyzer  -> AI resume analysis (multipart/form-data)
"""

import logging
import os
import secrets
from datetime import timedelta

from flask import Flask, jsonify, render_template, request

from services.ai_client import AIServiceError, get_provider_name, is_ai_configured
from services.career_guide import generate_career_plan
from services.pdf_extractor import PDFExtractionError, extract_text_from_pdf
from services.rate_limiter import SlidingWindowLimiter
from services.resume_analyzer import analyze_resume
from services.user_service import current_user
from services.validation import (
    MAX_RESUME_BYTES,
    MAX_RESUME_LABEL,
    validate_career_form,
    validate_resume_upload,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = "/tmp/ai-career-command-center" if os.environ.get("VERCEL") else BASE_DIR
UPLOAD_DIR = os.path.join(RUNTIME_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = MAX_RESUME_BYTES + 128 * 1024  # + headroom for form fields
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR
# Session hardening for the authenticated area (additive; public pages unaffected).
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)

# ---- AI Career Command Center: database + blueprints (additive upgrade) ----
from models import CareerProfile, init_db  # noqa: E402

init_db(app)

from routes import register_blueprints  # noqa: E402

register_blueprints(app)
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("career_app")

_rate_limiter = SlidingWindowLimiter(int(os.environ.get("RATE_LIMIT_PER_MINUTE", "12")), 60)


def _error_response(message: str, status: int, fields=None):
    payload = {"success": False, "error": {"message": message}}
    if fields:
        payload["error"]["fields"] = fields
    return jsonify(payload), status


def _rate_limited() -> bool:
    return not _rate_limiter.allow(request.remote_addr or "unknown")


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({
        "success": True,
        "status": "ok",
        "ai_configured": is_ai_configured(),
        "ai_provider": get_provider_name(),
    })


def _prefill_career_payload(payload):
    """Upgrade addition: for signed-in users with a stored career profile,
    auto-fill omitted Career Guide fields so they never re-type known data.
    Anonymous behaviour is completely unchanged."""
    if not isinstance(payload, dict):
        return payload
    user = current_user()
    if not user:
        return payload
    profile = CareerProfile.query.filter_by(user_id=user.id).first()
    payload = dict(payload)
    if not payload.get("full_name"):
        payload["full_name"] = user.full_name
    if not payload.get("target_role") and profile and profile.target_role:
        payload["target_role"] = profile.target_role
    if not payload.get("skills"):
        names = [us.skill.name for us in user.skills if us.skill][:12]
        if names:
            payload["skills"] = ", ".join(names)
    return payload


@app.post("/api/career-guide")
def career_guide():
    if _rate_limited():
        return _error_response(
            "Too many requests from your side. Please wait a minute and try again.", 429)
    payload = _prefill_career_payload(request.get_json(silent=True))
    data, errors = validate_career_form(payload)
    if errors:
        return _error_response("Please fix the highlighted fields and try again.", 400, errors)
    try:
        result = generate_career_plan(data)
    except AIServiceError as exc:
        logger.warning("Career guide AI error: %s", exc.message)
        return _error_response(exc.message, exc.status)
    except Exception:
        logger.exception("Unexpected error in career guide")
        return _error_response("Something went wrong on our side. Please try again.", 500)
    return jsonify({"success": True, "data": result})


@app.post("/api/resume-analyzer")
def resume_analyzer():
    if _rate_limited():
        return _error_response(
            "Too many requests from your side. Please wait a minute and try again.", 429)

    uploaded = request.files.get("resume")
    file_info, errors, target_role = validate_resume_upload(
        uploaded, request.form.get("target_role", ""))
    if errors:
        return _error_response("Please fix the highlighted fields and try again.", 400, errors)

    pdf_bytes = uploaded.read()
    if not pdf_bytes:
        message = "The uploaded file is empty. Please choose a valid PDF resume."
        return _error_response(message, 400, {"resume": message})
    if len(pdf_bytes) > MAX_RESUME_BYTES:
        message = f"Resume is too large. Maximum allowed size is {MAX_RESUME_LABEL}."
        return _error_response(message, 413, {"resume": message})

    try:
        resume_text = extract_text_from_pdf(pdf_bytes)
    except PDFExtractionError as exc:
        return _error_response(exc.message, 400, {"resume": exc.message})
    except Exception:
        logger.exception("Unexpected PDF extraction failure")
        return _error_response("We could not read that PDF. Please try a different file.", 500)

    try:
        result = analyze_resume(resume_text, target_role)
        result["filename"] = file_info["filename"]
    except AIServiceError as exc:  # kept for safety; analyze_resume degrades gracefully
        logger.warning("Resume analyzer AI error: %s", exc.message)
        return _error_response(exc.message, exc.status)
    except Exception:
        logger.exception("Unexpected error in resume analyzer")
        return _error_response("Something went wrong on our side. Please try again.", 500)

    return jsonify({"success": True, "data": result})


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return _error_response("Endpoint not found.", 404)
    return "<h1>404 &mdash; Page not found</h1><p><a href='/'>Back to the app</a></p>", 404


@app.errorhandler(405)
def method_not_allowed(_error):
    if request.path.startswith("/api/"):
        return _error_response("Method not allowed for this endpoint.", 405)
    return "<h1>405 &mdash; Method not allowed</h1>", 405


@app.errorhandler(413)
def too_large(_error):
    message = f"That upload is too large. Maximum allowed size is {MAX_RESUME_LABEL}."
    return _error_response(message, 413)


@app.errorhandler(500)
def internal_error(error):
    logger.exception("Unhandled server error: %s", error)
    if request.path.startswith("/api/"):
        return _error_response("Something went wrong on our side. Please try again.", 500)
    return "<h1>500 &mdash; Server error</h1><p>Please try again.</p>", 500


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )

