"""Profile + skills APIs (all scoped to the signed-in user)."""

from flask import g, request

from models import Skill, db
from routes.api_helpers import data_api, fail, json_payload, ok
from services.skill_service import (
    add_user_skill,
    list_skills,
    remove_user_skill,
    skill_growth,
    update_proficiency,
    user_skill_map,
)
from services.validation import clean_text
from services.web_security import api_login_required

PROFILE_FIELDS = ("education", "college", "degree", "graduation_year", "experience",
                  "target_role", "career_goal", "preferred_job_type")
PROFILE_LIMITS = {"education": 200, "college": 200, "degree": 120, "graduation_year": 10,
                  "experience": 1200, "target_role": 120, "career_goal": 600,
                  "preferred_job_type": 60}

VALID_SOURCES = ("resume", "manually_added", "AI_suggested")


def _profile_response(user) -> dict:
    profile = user.profile
    data = profile.to_dict() if profile else {field: "" for field in PROFILE_FIELDS}
    skills = list_skills(user)
    return {
        "user": user.to_public(),
        "profile": data,
        "skill_count": len(skills),
        "skills": skills,
    }


def register(app) -> None:

    @app.get("/api/profile")
    @api_login_required
    @data_api()
    def api_profile_get():
        return ok(_profile_response(g.user))

    @app.route("/api/profile", methods=["PUT", "POST"])
    @api_login_required
    @data_api(write=True)
    def api_profile_update():
        from models import CareerProfile

        payload = json_payload()
        profile = g.user.profile or CareerProfile(user_id=g.user.id)

        for field in PROFILE_FIELDS:
            if field in payload:
                setattr(profile, field, clean_text(payload.get(field), PROFILE_LIMITS[field]))
        if not profile.id:
            db.session.add(profile)

        new_name = clean_text(payload.get("full_name"), 120)
        if len(new_name) >= 2:
            g.user.full_name = new_name
        db.session.commit()
        return ok(_profile_response(g.user))

    # ------------------------------------------------------------------ skills

    @app.get("/api/skills")
    @api_login_required
    @data_api()
    def api_skills_list():
        rows = list_skills(g.user)
        return ok({
            "skills": rows,
            "count": len(rows),
            "growth": skill_growth(g.user),
            "by_source": {source: [s for s in rows if s["source"] == source]
                          for source in VALID_SOURCES},
        })

    @app.get("/api/skills/catalog")
    @api_login_required
    @data_api()
    def api_skills_catalog():
        rows = Skill.query.order_by(Skill.name.asc()).limit(400).all()
        return ok({"catalog": [{"id": row.id, "name": row.name,
                                "category": row.category} for row in rows]})

    @app.get("/api/skills/growth")
    @api_login_required
    @data_api()
    def api_skills_growth():
        return ok({"skills": list_skills(g.user), "growth": skill_growth(g.user)})

    @app.post("/api/skills")
    @api_login_required
    @data_api(write=True)
    def api_skills_add():
        payload = json_payload()
        source = payload.get("source")
        source = source if source in VALID_SOURCES else "manually_added"
        proficiency = payload.get("proficiency")
        proficiency = int(proficiency) if str(proficiency if proficiency is not None else "").isdigit() else None

        names = payload.get("skills")
        if names is None:
            names = [payload.get("name")]
        if isinstance(names, str):
            names = names.split(",")
        if not isinstance(names, list):
            return fail("Please provide at least one skill.", 400)

        added, skipped = [], []
        for raw in names[:40]:
            name = clean_text(raw, 60)
            if len(name) < 2:
                continue
            row, created = add_user_skill(g.user, name, source=source, proficiency=proficiency)
            label = row.skill.name if row and row.skill else name
            (added if created else skipped).append(label)

        db.session.commit()
        return ok({"added": added, "skipped": skipped, "skills": list_skills(g.user)})

    @app.route("/api/skills/<int:skill_id>", methods=["PUT", "PATCH"])
    @api_login_required
    @data_api(write=True)
    def api_skills_update(skill_id: int):
        payload = json_payload()
        value = payload.get("proficiency")
        if not str(value if value is not None else "").strip().isdigit():
            return ok({"message": "No changes applied."})
        row = update_proficiency(g.user, skill_id, int(value))
        if not row:
            return fail("That skill is not in your profile.", 404)
        return ok({"skill": row.to_dict(), "skills": list_skills(g.user)})

    @app.delete("/api/skills/<int:skill_id>")
    @api_login_required
    @data_api(write=True)
    def api_skills_delete(skill_id: int):
        if not remove_user_skill(g.user, skill_id):
            return fail("That skill is not in your profile.", 404)
        return ok({"skills": list_skills(g.user)})

    # -------------------------------------------------------------------- gaps

    @app.get("/api/gaps")
    @api_login_required
    @data_api(ai=True)
    def api_gaps():
        """Skill-gap analysis for the signed-in user's target role.

        The deterministic comparison is instant; AI guidance is cached per
        (role, gap-set) so repeat visits never re-spend an API call.
        """
        from services.gap_engine import gap_analysis_cached
        from services.resources import get_job_portals, get_learning_resources

        profile_role = g.user.profile.target_role if g.user.profile else ""
        role = clean_text(request.args.get("target_role") or profile_role, 120)
        analysis = gap_analysis_cached(g.user, role)
        analysis["resources"] = get_learning_resources()
        analysis["job_portals"] = get_job_portals()
        analysis["owned_skills"] = sorted(user_skill_map(g.user))
        return ok(analysis)
