"""Authentication HTML pages: login, signup, forgot & reset password."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from services.user_service import current_user

auth_pages_bp = Blueprint("auth_pages", __name__)


def _redirect_if_authed():
    """An authenticated visitor has no business on the auth pages.

    The landing page ("/home") is the destination for every signed-in session,
    so send them there rather than to the entry page.
    """
    user = current_user()
    if user:
        return redirect(url_for("home"))
    return None


def _safe_next(target: str | None) -> str:
    """Keep post-login redirects on this site.

    `next` is attacker-controllable (it comes from the query string) and is handed
    to the browser as `window.AUTH_NEXT`, so only same-origin relative paths are
    allowed through. Anything absolute ("https://evil.example"), protocol
    relative ("//evil.example"), backslash-smuggled ("/\\evil.example") or
    containing control characters is discarded so auth.js falls back to the
    landing page ("/") instead of redirecting a freshly signed-in user off-site.
    """
    if not target:
        return ""
    candidate = target.strip()
    if not candidate.startswith("/"):
        return ""
    if candidate.startswith("//") or candidate.startswith("/\\"):
        return ""
    if "\\" in candidate or any(ch in candidate for ch in "\r\n\t\x00"):
        return ""
    return candidate


@auth_pages_bp.get("/login")
def login():
    early = _redirect_if_authed()
    if early:
        return early
    return render_template("login.html", next=_safe_next(request.args.get("next")))


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
