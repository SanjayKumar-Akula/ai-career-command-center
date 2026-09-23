"""Blueprint registration for the AI Career Command Center upgrade.

All new functionality is registered here; the original endpoints in app.py
are untouched, so existing behaviour is fully preserved.
"""

from __future__ import annotations

from flask import app as flask_app_module  # noqa: F401  (type hint aid only)


def register_blueprints(app) -> None:
    from routes.auth_api import auth_api_bp
    from routes.auth_pages import auth_pages_bp
    from routes.pages import pages_bp

    app.register_blueprint(auth_pages_bp)
    app.register_blueprint(auth_api_bp)
    app.register_blueprint(pages_bp)

    from routes.api_data import register_data_routes
    register_data_routes(app)

    # Template globals: auth state + CSRF token for every rendered page
    # (including the public landing page, which stays fully functional
    # for anonymous visitors).
    from models import Notification
    from services.user_service import current_user
    from services.web_security import csrf_token, ensure_csrf_token

    app.before_request(ensure_csrf_token)

    @app.context_processor
    def _inject_globals():
        user = current_user()
        unread = 0
        if user:
            unread = Notification.query.filter_by(user_id=user.id, is_read=False).count()
        return {
            "session_user": user.to_public() if user else None,
            "csrf_token": csrf_token,
            "unread_notifications": unread,
        }
