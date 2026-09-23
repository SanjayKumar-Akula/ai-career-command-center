"""Roadmap + progress APIs (AI generation is cached per role in the DB)."""

from __future__ import annotations

from flask import g

from routes.api_helpers import data_api, fail, json_payload, ok
from services.resources import get_job_portals, get_learning_resources
from services.roadmap_service import (
    generate_roadmap,
    get_roadmap,
    set_task_state,
)
from services.skill_service import list_skills, skill_growth
from services.validation import clean_text
from services.web_security import api_login_required

VALID_STATES = ("not_started", "in_progress", "completed")


def register(app) -> None:

    @app.get("/api/roadmap")
    @api_login_required
    @data_api()
    def api_roadmap_get():
        """Stored roadmap only — page loads never trigger an AI call."""
        profile = g.user.profile
        role = clean_text(profile.target_role if profile else "", 120)
        row = get_roadmap(g.user, role)
        return ok({
            "roadmap": row,
            "has_roadmap": row is not None,
            "target_role": role,
            "progress": (row or {}).get("progress_percent", 0),
        })

    @app.post("/api/roadmap")
    @api_login_required
    @data_api(write=True, ai=True)
    def api_roadmap_generate():
        """Generate (or regenerate) the personalized roadmap on request."""
        payload = json_payload()
        profile = g.user.profile
        role = clean_text(payload.get("target_role")
                          or (profile.target_role if profile else ""), 120)
        if len(role) < 3:
            return fail("Set a target role in your profile to generate a roadmap.", 400)
        try:
            data = generate_roadmap(g.user, role)
        except ValueError as exc:
            return fail(str(exc), 400)
        return ok({
            "roadmap": data,
            "has_roadmap": True,
            "target_role": role,
            "progress": data.get("progress_percent", 0),
        })

    @app.post("/api/roadmap/task")
    @api_login_required
    @data_api(write=True)
    def api_roadmap_task():
        payload = json_payload()
        roadmap_id = str(payload.get("roadmap_id") or "")
        task_key = clean_text(payload.get("task_key"), 60)
        state = clean_text(payload.get("state"), 20)
        if not roadmap_id.isdigit() or not task_key:
            return fail("Invalid task update request.", 400)
        if state not in VALID_STATES:
            return fail("Unknown task state.", 400)
        try:
            row = set_task_state(g.user, int(roadmap_id), task_key, state)
        except ValueError as exc:
            return fail(str(exc), 404)
        return ok({"roadmap": row, "progress": row.get("progress_percent", 0)})

    @app.get("/api/progress")
    @api_login_required
    @data_api()
    def api_progress():
        """Skill growth + roadmap progress for the growth-tracking views."""
        profile = g.user.profile
        role = clean_text(profile.target_role if profile else "", 120)
        row = get_roadmap(g.user, role)
        return ok({
            "skills": list_skills(g.user),
            "growth": skill_growth(g.user),
            "roadmap": row,
            "roadmap_progress": (row or {}).get("progress_percent", 0),
        })

    @app.get("/api/resources")
    @api_login_required
    @data_api()
    def api_resources():
        """Curated links (never AI-generated URLs)."""
        from services.resume_analyzer import analyze_resume  # noqa: F401  (keeps ATS module warm)
        return ok({
            "learning_resources": get_learning_resources(),
            "job_portals": get_job_portals(),
        })
