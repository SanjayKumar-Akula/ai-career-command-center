"""Dashboard, history, notifications, AI coach and resume-builder APIs."""

from __future__ import annotations

from flask import g, send_file
import io

from routes.api_helpers import data_api, fail, json_payload, ok
from services.activity_service import (
    career_readiness,
    list_activities,
    list_notifications,
    mark_all_read,
    mark_notification_read,
    unread_count,
)
from services.user_service import current_user
from services.validation import clean_text
from services.web_security import api_login_required


def register(app) -> None:

    # ------------------------------------------------------------- dashboard

    @app.get("/api/dashboard")
    @api_login_required
    @data_api()
    def api_dashboard():
        from models import CareerRoadmap, Resume, UserSkill
        from services.gap_engine import compute_gap_analysis
        from services.skill_service import skill_growth

        user = g.user
        readiness = career_readiness(user)
        resumes = Resume.query.filter_by(user_id=user.id) \
            .order_by(Resume.created_at.desc()).all()
        skill_count = UserSkill.query.filter_by(user_id=user.id).count()
        roadmap = (CareerRoadmap.query.filter_by(user_id=user.id)
                   .order_by(CareerRoadmap.updated_at.desc()).first())

        gap = compute_gap_analysis(user)
        insight = _ai_insight(readiness, gap, roadmap, resumes, skill_count)

        return ok({
            "user": user.to_public(),
            "readiness": readiness,
            "stats": {
                "skills": skill_count,
                "resumes": len(resumes),
                "skill_gaps": readiness["skill_gaps"],
                "target_role": readiness["target_role"]
                               or (user.profile.target_role if user.profile else ""),
                "ats_score": readiness["ats_score"],
                "roadmap_progress": roadmap.progress_percent if roadmap else 0,
            },
            "insight": insight,
            "recent_activity": list_activities(user, 8),
            "notifications": list_notifications(user, 6),
            "unread_notifications": unread_count(user),
            "skill_growth": skill_growth(user, 5),
            "latest_resumes": [row.to_dict() for row in resumes[:3]],
        })

    # --------------------------------------------------------------- history

    @app.get("/api/history")
    @api_login_required
    @data_api()
    def api_history():
        from services.resume_store import ats_history

        return ok({
            "ats_history": ats_history(g.user),
            "activities": list_activities(g.user, 40),
            "notifications": list_notifications(g.user, 30),
        })

    # --------------------------------------------------------- notifications

    @app.get("/api/notifications")
    @api_login_required
    @data_api()
    def api_notifications_get():
        return ok({"notifications": list_notifications(g.user, 30),
                   "unread": unread_count(g.user)})

    @app.post("/api/notifications/<int:notification_id>/read")
    @api_login_required
    @data_api(write=True)
    def api_notification_read(notification_id: int):
        if not mark_notification_read(g.user, notification_id):
            return fail("That notification was not found.", 404)
        return ok({"unread": unread_count(g.user)})

    @app.post("/api/notifications/read-all")
    @api_login_required
    @data_api(write=True)
    def api_notifications_read_all():
        mark_all_read(g.user)
        return ok({"unread": 0})

    # ----------------------------------------------------------------- coach

    @app.get("/api/coach")
    @api_login_required
    @data_api()
    def api_coach_history():
        from services.coach_service import get_history

        return ok({"history": get_history(g.user)})

    @app.post("/api/coach")
    @api_login_required
    @data_api(ai=True, write=True)
    def api_coach_ask():
        from services.coach_service import ask

        result = ask(g.user, clean_text(json_payload().get("message"), 600))
        if result.get("error"):
            return fail(result["error"], 400)
        return ok(result)

    @app.delete("/api/coach")
    @api_login_required
    @data_api(write=True)
    def api_coach_clear():
        from services.coach_service import clear_history

        clear_history(g.user)
        return ok({"history": []})

    # ----------------------------------------------------- AI resume builder

    @app.get("/api/builder")
    @api_login_required
    @data_api()
    def api_builder_get():
        """Return the user's current draft without spending an AI call."""
        from models import GeneratedResume
        from services.resume_builder import _missing_fields, _collect_facts
        from services.resume_pdf import normalise_content

        draft = (GeneratedResume.query.filter_by(user_id=g.user.id)
                 .order_by(GeneratedResume.created_at.desc()).first())
        if not draft:
            return ok({"draft": None, "content": None, "missing_info": []})
        from models import load_json
        content = normalise_content(load_json(draft.content_json, {}) or {})
        return ok({
            "draft": draft.to_dict(include_content=False),
            "content": content,
            "missing_info": _missing_fields(_collect_facts(g.user), content, []),
        })

    @app.post("/api/builder")
    @api_login_required
    @data_api(ai=True, write=True)
    def api_builder_generate():
        from services.resume_builder import BuilderError, build_resume

        payload = json_payload()
        resume_id = payload.get("resume_id")
        result = build_resume(
            g.user,
            resume_id=int(resume_id) if str(resume_id).isdigit() else None,
            force_ai=bool(payload.get("force_ai", True)),
        )
        return ok(result)

    @app.put("/api/builder")
    @app.patch("/api/builder")
    @api_login_required
    @data_api(write=True)
    def api_builder_save():
        """Save user edits to the draft (whitelisted + clamped server-side)."""
        from models import GeneratedResume, dump_json, load_json
        from services.resume_builder import BuilderError, _missing_fields, _collect_facts
        from services.resume_pdf import normalise_content

        payload = json_payload()
        draft = (GeneratedResume.query.filter_by(user_id=g.user.id)
                 .order_by(GeneratedResume.created_at.desc()).first())
        if not draft:
            return fail("Generate a resume draft first.", 404)

        content = normalise_content(payload.get("content") or {})
        draft.content_json = dump_json(content)
        draft.title = clean_text(payload.get("title") or draft.title, 120)
        db_commit()
        return ok({"draft": draft.to_dict(include_content=False),
                   "content": content,
                   "missing_info": _missing_fields(_collect_facts(g.user), content, [])})

    @app.post("/api/builder/download")
    @api_login_required
    @data_api(write=True)
    def api_builder_download():
        """Generate the ATS-friendly PDF (or DOCX) of the saved draft."""
        from models import GeneratedResume, load_json
        from services.resume_pdf import build_docx, build_pdf, normalise_content

        payload = json_payload()
        fmt = (payload.get("format") or "pdf").lower()
        if fmt not in ("pdf", "docx"):
            return fail("Format must be pdf or docx.", 400)

        draft = (GeneratedResume.query.filter_by(user_id=g.user.id)
                 .order_by(GeneratedResume.created_at.desc()).first())
        if not draft:
            return fail("Generate a resume draft first.", 404)
        content = normalise_content(load_json(draft.content_json, {}) or {})

        if fmt == "docx":
            blob = build_docx(content)
            mime = ("application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document")
        else:
            blob = build_pdf(content)
            mime = "application/pdf"

        safe_name = "".join(ch for ch in (content["name"] or "resume")
                            if ch.isalnum() or ch in " -_").strip() or "resume"
        return send_file(
            io.BytesIO(blob),
            mimetype=mime,
            as_attachment=True,
            download_name=f"{safe_name}-resume.{fmt}",
        )


def db_commit() -> None:
    from models import db
    db.session.commit()


def _ai_insight(readiness: dict, gap: dict, roadmap, resumes, skill_count: int) -> str:
    """One personalized, deterministic recommendation (never needs an AI call)."""
    if gap["has_role"] and gap["missing"]:
        top = gap["missing"][0]["name"]
        second = gap["missing"][1]["name"] if len(gap["missing"]) > 1 else top
        return (f"Your biggest gap for {gap['target_role']} is {top}. "
                f"Add {top} fundamentals to your next learning cycle, then back it "
                f"up with {second} and a small project.")
    if not resumes:
        return ("Upload your first resume to unlock your Career Intelligence — "
                "ATS scoring, skill extraction and a personalized roadmap.")
    if skill_count == 0:
        return "Add your skills on the Skills page so we can compare them against your target role."
    if readiness["ats_score"] and readiness["ats_score"] < 70:
        return (f"Your ATS score is {readiness['ats_score']}/100. "
                "Strengthen keyword match and add measurable outcomes to your projects.")
    if roadmap is None:
        return "Set a target role to generate your personalized 30-day roadmap."
    if roadmap.progress_percent < 50:
        return (f"Your roadmap is {roadmap.progress_percent}% complete. "
                "Mark this week's tasks as done to keep your momentum.")
    return (f"You are in good shape for {readiness['target_role'] or 'your target role'} — "
            "focus on interview prep and one deep project to stand out.")
