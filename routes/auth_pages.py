"""Authentication HTML pages: login, signup, forgot & reset password."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from services.user_service import current_user

auth_pages_bp = Blueprint("auth_pages", __name__)


def _redirect_if_authed():
    user = current_user()
    if user:
        return redirect(url_for("pages.dashboard"))
    return None


@auth_pages_bp.get("/login")
def login():
    early = _redirect_if_authed()
    if early:
        return early
    return render_template("login.html", next=request.args.get("next", ""))


@auth_pages_bp.get("/signup")
def signup():
    early = _redirect_if_authed()
    if early:
        return early
    return render_template("signup.html")


@auth_pages_bp.get("/forgot-password")
def forgot_password():
    early = _redirect_if_authed()
    if early:
        return early
    return render_template("forgot_password.html")


@auth_pages_bp.get("/reset-password/<token>")
def reset_password(token: str):
    early = _redirect_if_authed()
    if early:
        return early
    return render_template("reset_password.html", token=token)
