"""Input validation + sanitisation helpers shared by the Flask routes."""

import re

MAX_RESUME_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_RESUME_LABEL = "5 MB"


def clean_text(value, max_length: int = 200) -> str:
    """Collapse whitespace and trim; always returns a safe plain string."""
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(item) for item in value)
    elif not isinstance(value, str):
        value = "" if value is None else str(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_length]


def validate_career_form(payload):
    """Validate the Career Guide form. Returns (data, field_errors)."""
    if not isinstance(payload, dict):
        return None, {"form": "Invalid request body. Expected JSON."}

    errors: dict = {}

    name = clean_text(payload.get("full_name"), 100)
    skills = clean_text(payload.get("skills"), 400)
    role = clean_text(payload.get("target_role"), 80)

    if len(name) < 2:
        errors["full_name"] = "Please enter your full name (at least 2 characters)."
    if not skills:
        errors["skills"] = "Please enter at least one skill (e.g., Python, SQL, HTML)."
    if len(role) < 3:
        errors["target_role"] = "Please enter a target role (e.g., Software Developer)."

    if errors:
        return None, errors
    return {"full_name": name, "skills": skills, "target_role": role}, {}


def validate_resume_upload(file_storage, target_role):
    """Validate the Resume Analyzer upload.

    Returns (file_info_or_None, field_errors, cleaned_role).
    """
    errors: dict = {}
    role = clean_text(target_role, 80)

    if len(role) < 3:
        errors["target_role"] = "Please enter a target role (e.g., Software Developer)."

    if file_storage is None or not (file_storage.filename or "").strip():
        errors["resume"] = "Please choose a PDF resume to upload."
        return None, errors, role

    filename = (file_storage.filename or "").strip()
    if not filename.lower().endswith(".pdf"):
        errors["resume"] = "Only PDF files are supported. Please upload a .pdf resume."
        return None, errors, role

    return {"filename": filename}, errors, role
