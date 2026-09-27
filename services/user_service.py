"""User account service: signup, authentication, password resets, sessions."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta

from flask import g, session
from werkzeug.security import check_password_hash, generate_password_hash

from models import (Activity, CareerProfile, CareerRoadmap, CoachMessage,
                    GapGuidance, GeneratedResume, Notification,
                    PasswordResetToken, Progress, Resume, ResumeAnalysis,
                    SkillHistory, User, UserSkill, db)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
RESET_TOKEN_MINUTES = 30


def validate_signup(full_name: str, email: str, password: str, confirm: str) -> dict:
    """Return a dict of field errors (empty when valid)."""
    errors: dict = {}
    if not full_name or len(full_name.strip()) < 2:
        errors["full_name"] = "Please enter your full name (at least 2 characters)."
    if not email or not EMAIL_RE.match(email.strip() or ""):
        errors["email"] = "Please enter a valid email address."
    if not password or len(password) < 8:
        errors["password"] = "Password must be at least 8 characters long."
    elif not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        errors["password"] = "Password must contain at least one letter and one number."
    if password != confirm:
        errors["confirm_password"] = "Passwords do not match."
    return errors


def email_exists(email: str) -> bool:
    return User.query.filter(db.func.lower(User.email) == (email or "").strip().lower()).first() is not None


def create_user(full_name: str, email: str, password: str) -> User:
    user = User(
        full_name=full_name.strip()[:120],
        email=email.strip().lower()[:255],
        password_hash=generate_password_hash(password),
    )
    db.session.add(user)
    db.session.commit()
    return user


def authenticate(email: str, password: str):
    """Return the User when credentials are valid, otherwise None."""
    if not email or not password:
        return None
    user = User.query.filter(
        db.func.lower(User.email) == email.strip().lower()).first()
    if user and check_password_hash(user.password_hash, password):
        return user
    return None


def set_session(user: User) -> None:
    session.clear()
    session["user_id"] = user.id
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True


def clear_session() -> None:
    session.clear()


def current_user():
    """Resolve the session user (cached per request). Never trusts the client."""
    if "user_id" not in session:
        return None
    cached = g.get("_current_user", "unset")
    if cached != "unset":
        return cached or None
    user = db.session.get(User, session["user_id"])
    g._current_user = user if user else None
    return user


def change_password(user: User, current_password: str, new_password: str,
                    confirm_password: str) -> dict:
    """Change password; returns field errors dict (empty on success)."""
    errors: dict = {}
    if not check_password_hash(user.password_hash, current_password or ""):
        errors["current_password"] = "Your current password is incorrect."
    if not new_password or len(new_password) < 8:
        errors["new_password"] = "New password must be at least 8 characters long."
    elif not re.search(r"[A-Za-z]", new_password) or not re.search(r"\d", new_password):
        errors["new_password"] = "New password must contain at least one letter and one number."
    if new_password != confirm_password:
        errors["confirm_password"] = "Passwords do not match."
    if errors:
        return errors
    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    return {}


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_password_reset(email: str):
    """Create a single-use reset token. Returns the raw token or None
    (None also when the email is unknown — never reveal account existence)."""
    user = User.query.filter(db.func.lower(User.email) == (email or "").strip().lower()).first()
    if not user:
        return None
    token = secrets.token_urlsafe(32)
    row = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_token(token),
        expires_at=(datetime.utcnow() + timedelta(minutes=RESET_TOKEN_MINUTES)),
    )
    db.session.add(row)
    db.session.commit()
    return token


def redeem_password_reset(token: str, new_password: str, confirm: str) -> tuple:
    """Validate the token and set the new password.

    Returns (success: bool, errors: dict).
    """
    if not token:
        return False, {"form": "This password reset link is invalid or has expired."}
    row = PasswordResetToken.query.filter_by(token_hash=_hash_token(token)).first()
    if not row or row.used_at is not None or row.expires_at < datetime.utcnow():
        return False, {"form": "This password reset link is invalid or has expired."}

    errors: dict = {}
    if not new_password or len(new_password) < 8:
        errors["password"] = "Password must be at least 8 characters long."
    elif not re.search(r"[A-Za-z]", new_password) or not re.search(r"\d", new_password):
        errors["password"] = "Password must contain at least one letter and one number."
    if new_password != confirm:
        errors["confirm_password"] = "Passwords do not match."
    if errors:
        return False, errors

    user = db.session.get(User, row.user_id)
    if not user:
        return False, {"form": "This password reset link is invalid or has expired."}
    user.password_hash = generate_password_hash(new_password)
    row.used_at = datetime.utcnow()
    db.session.commit()
    return True, {}



# ---------------------------------------------------------------------------
# Permanent account deletion
# ---------------------------------------------------------------------------
# The order below was derived from the live schema (15 tables), not guessed.
# `skills` is a GLOBAL catalog shared by every account and is deliberately never
# touched. The other 13 tables are user-owned and each carries a user_id FK.
#
# The schema declares NO "ON DELETE CASCADE", so the deletes must already be in
# a child-first order to stay valid on PostgreSQL as well as SQLite:
#   * resume_analyses references BOTH resumes and users  -> before `resumes`
#   * user_skills     references BOTH users and the shared `skills` catalog
#   * resumes         is the parent of resume_analyses
#   * every other table references only `users`, so any order is safe
# Only rows belonging to this one user are ever selected.
_USER_OWNED_DELETE_ORDER = (
    ResumeAnalysis,     # child of resumes, also a child of users
    Resume,             # parent of resume_analyses
    UserSkill,          # also references the shared `skills` catalog
    SkillHistory,
    CareerRoadmap,
    CoachMessage,       # AI coach conversation history
    Notification,
    Activity,
    Progress,
    CareerProfile,      # profile / settings
    GapGuidance,
    GeneratedResume,    # resume builder drafts
    PasswordResetToken,
)


def delete_account(user: User) -> dict:
    """Permanently delete `user` and every row that belongs to them.

    Everything runs inside ONE database transaction. If any statement fails the
    session is rolled back, so an account is never left partially deleted, and
    the exception is re-raised for the caller to turn into a friendly error.

    Returns ``{table_name: rows_deleted}`` (always including ``users``).
    """
    uid = user.id
    deleted: dict = {}
    try:
        for model in _USER_OWNED_DELETE_ORDER:
            deleted[model.__tablename__] = model.query.filter_by(
                user_id=uid).delete(synchronize_session=False)
        # The user row goes last, once nothing references it any more.
        deleted["users"] = User.query.filter_by(id=uid).delete(
            synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        # Drop the deleted rows from the session identity map so nothing
        # downstream can try to flush or read them again.
        db.session.expunge_all()
    return deleted
