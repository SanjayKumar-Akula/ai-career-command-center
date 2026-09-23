"""Web security helpers: CSRF protection, login requirements, auth limiter."""

from __future__ import annotations

import functools
import os
import secrets

from flask import g, jsonify, redirect, request, session, url_for

from services.rate_limiter import SlidingWindowLimiter
from services.user_service import current_user

# Brute-force protection for auth endpoints (independent of the public API limiter).
auth_limiter = SlidingWindowLimiter(int(os.environ.get("AUTH_RATE_LIMIT_PER_MINUTE", "10")), 60)

# State-changing app APIs require this header to match the session CSRF token.
CSRF_HEADER = "X-CSRF-Token"


def ensure_csrf_token() -> None:
    """Guarantee a CSRF token exists in the session (runs before every request)."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)


def csrf_token() -> str:
    return session.get("csrf_token", "")


def csrf_ok() -> bool:
    token = request.headers.get(CSRF_HEADER, "")
    return bool(token) and secrets.compare_digest(token, session.get("csrf_token", ""))


def require_csrf(fn):
    """Decorator: reject state-changing requests without a valid CSRF token."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not csrf_ok():
            return jsonify({
                "success": False,
                "error": {"message": "Your session expired. Please refresh the page and try again."},
            }), 403
        return fn(*args, **kwargs)

    return wrapper


def api_login_required(fn):
    """Decorator for JSON APIs: 401 when not authenticated."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({
                "success": False,
                "error": {"message": "Please sign in to continue."},
            }), 401
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


def page_login_required(fn):
    """Decorator for HTML pages: redirect to /login when not authenticated."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for("auth_pages.login", next=request.path))
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


def auth_rate_limited() -> bool:
    return not auth_limiter.allow(request.remote_addr or "unknown")
