"""Authentication JSON APIs: signup, login, logout, me, password reset."""

from __future__ import annotations

import os

from flask import Blueprint, jsonify, request, session

from models import User, db
from services.user_service import (
    authenticate,
    clear_session,
    create_password_reset,
    create_user,
    current_user,
    email_exists,
    redeem_password_reset,
    set_session,
    validate_signup,
)
from services.validation import clean_text
from services.web_security import (
    api_login_required,
    auth_rate_limited,
    require_csrf,
)

auth_api_bp = Blueprint("auth_api", __name__, url_prefix="/api/auth")

# Demo convenience: without an email provider, the reset link can be shown
# on screen. Disable in production by setting ALLOW_DEMO_RESET_LINK=0 and
# wiring an email service in create_password_reset().
DEMO_RESET_LINKS = os.environ.get("ALLOW_DEMO_RESET_LINK", "1") != "0"


@auth_api_bp.post("/signup")
def signup():
    if auth_rate_limited():
        return jsonify({"success": False, "error": {
            "message": "Too many attempts. Please wait a minute and try again."}}), 429
    payload = request.get_json(silent=True) or {}
    full_name = clean_text(payload.get("full_name"), 120)
    email = clean_text(payload.get("email"), 255).lower()
    password = str(payload.get("password") or "")
    confirm = str(payload.get("confirm_password") or "")

    errors = validate_signup(full_name, email, password, confirm)
    if not errors and email_exists(email):
        errors = {"email": "An account with this email already exists. Please sign in instead."}
    if errors:
        return jsonify({"success": False, "error": {
            "message": "Please fix the highlighted fields and try again.",
            "fields": errors}}), 400

    user = create_user(full_name, email, password)
    set_session(user)
    return jsonify({"success": True, "data": {"user": user.to_public()}})


@auth_api_bp.post("/login")
def login():
    if auth_rate_limited():
        return jsonify({"success": False, "error": {
            "message": "Too many attempts. Please wait a minute and try again."}}), 429
    payload = request.get_json(silent=True) or {}
    email = clean_text(payload.get("email"), 255)
    password = str(payload.get("password") or "")
    user = authenticate(email, password)
    if not user:
        return jsonify({"success": False, "error": {
            "message": "Incorrect email or password. Please try again."}}), 401
    set_session(user)
    return jsonify({"success": True, "data": {"user": user.to_public()}})


@auth_api_bp.post("/logout")
@require_csrf
def logout():
    clear_session()
    return jsonify({"success": True, "data": {"message": "Signed out."}})


@auth_api_bp.get("/me")
def me():
    user = current_user()
    if not user:
        return jsonify({"success": False, "error": {
            "message": "Not signed in."}}), 401
    return jsonify({"success": True, "data": {"user": user.to_public()}})


@auth_api_bp.post("/forgot-password")
def forgot_password():
    if auth_rate_limited():
        return jsonify({"success": False, "error": {
            "message": "Too many attempts. Please wait a minute and try again."}}), 429
    payload = request.get_json(silent=True) or {}
    email = clean_text(payload.get("email"), 255)
    # Same response either way — never reveal whether the account exists.
    generic = {"message": "If that email is registered, a password reset link has been created."}
    token = create_password_reset(email)
    data = dict(generic)
    if token and DEMO_RESET_LINKS:
        data["demo_reset_url"] = f"/reset-password/{token}"
    return jsonify({"success": True, "data": data})


@auth_api_bp.post("/reset-password")
def reset_password():
    if auth_rate_limited():
        return jsonify({"success": False, "error": {
            "message": "Too many attempts. Please wait a minute and try again."}}), 429
    payload = request.get_json(silent=True) or {}
    token = str(payload.get("token") or "")
    new_password = str(payload.get("password") or "")
    confirm = str(payload.get("confirm_password") or "")
    ok, errors = redeem_password_reset(token, new_password, confirm)
    if not ok:
        return jsonify({"success": False, "error": {
            "message": "Please fix the highlighted fields and try again.",
            "fields": errors}}), 400
    session.clear()  # force a fresh sign-in with the new password
    return jsonify({"success": True, "data": {
        "message": "Password updated. Please sign in with your new password."}})
