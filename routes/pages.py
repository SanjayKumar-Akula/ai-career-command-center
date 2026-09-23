"""Authenticated dashboard pages (server-rendered shells; data loads via API)."""

from __future__ import annotations

from flask import Blueprint, render_template

from services.web_security import page_login_required

pages_bp = Blueprint("pages", __name__)

PAGES = {
    "dashboard": ("Dashboard", "dashboard.html"),
    "resume": ("Resume Vault", "resume.html"),
    "skills": ("Skills", "skills.html"),
    "roadmap": ("Career Roadmap", "roadmap.html"),
    "coach": ("AI Career Coach", "coach.html"),
    "history": ("History", "history.html"),
    "resources": ("Jobs & Resources", "resources.html"),
    "profile": ("Profile", "profile.html"),
    "settings": ("Settings", "settings.html"),
}


def _render(page_id: str):
    title, template = PAGES[page_id]
    return render_template(template, page_id=page_id, page_title=title, nav_pages=PAGES)


@pages_bp.get("/dashboard")
@page_login_required
def dashboard():
    return _render("dashboard")


@pages_bp.get("/resume")
@page_login_required
def resume():
    return _render("resume")


@pages_bp.get("/skills")
@page_login_required
def skills():
    return _render("skills")


@pages_bp.get("/roadmap")
@page_login_required
def roadmap():
    return _render("roadmap")


@pages_bp.get("/coach")
@page_login_required
def coach():
    return _render("coach")


@pages_bp.get("/history")
@page_login_required
def history():
    return _render("history")


@pages_bp.get("/resources")
@page_login_required
def resources():
    return _render("resources")


@pages_bp.get("/profile")
@page_login_required
def profile():
    return _render("profile")


@pages_bp.get("/settings")
@page_login_required
def settings():
    return _render("settings")
