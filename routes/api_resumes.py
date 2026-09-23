"""Resume vault APIs: upload, re-analyze, download, compare, detection."""

from __future__ import annotations

from flask import Response, g, request

from routes.api_helpers import data_api, fail, json_payload, ok
from services.resume_store import (
    ResumeStoreError,
    ats_history,
    compare_resumes,
    delete_resume,
    get_resume,
    list_resumes,
    reanalyze,
    resume_detail,
    set_primary,
    upload_and_analyze,
)
from services.skill_service import add_user_skill, list_skills
from services.validation import clean_text
from services.web_security import api_login_required


def register(app) -> None:

    @app.get("/api/resumes")
    @api_login_required
    @data_api()
    def api_resumes_list():
        rows = list_resumes(g.user)
        return ok({"resumes": rows, "count": len(rows)})

    @app.post("/api/resumes")
    @api_login_required
    @data_api(write=True, ai=True)
    def api_resumes_upload():
        uploaded = request.files.get("resume")
        profile = g.user.profile
        role = clean_text(request.form.get("target_role", ""), 120) or \
            clean_text(profile.target_role if profile else "", 120)
        try:
            result = upload_and_analyze(g.user, uploaded, role)
        except ResumeStoreError as exc:
            return fail(exc.message, exc.status)
        result["resumes"] = list_resumes(g.user)
        return ok(result, 201)

    @app.get("/api/resumes/<int:resume_id>")
    @api_login_required
    @data_api()
    def api_resume_detail(resume_id: int):
        return ok(resume_detail(g.user, resume_id))

    @app.post("/api/resumes/<int:resume_id>/analyze")
    @api_login_required
    @data_api(write=True, ai=True)
    def api_resume_reanalyze(resume_id: int):
        resume = get_resume(g.user, resume_id)
        if not resume:
            return fail("That resume was not found in your vault.", 404)
        new_role = clean_text(json_payload().get("target_role"), 120)
        if len(new_role) >= 3:
            resume.target_role = new_role
        result = reanalyze(g.user, resume)
        result["resume"] = resume.to_dict(include_detected=True)
        result["analysis_history"] = ats_history(g.user)
        return ok(result)

    @app.get("/api/resumes/<int:resume_id>/download")
    @api_login_required
    def api_resume_download(resume_id: int):
        resume = get_resume(g.user, resume_id)
        if not resume or not resume.file_data:
            return fail("That resume file is no longer available.", 404)
        filename = (resume.filename or "resume.pdf").replace('"', "")
        return Response(
            resume.file_data,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.delete("/api/resumes/<int:resume_id>")
    @api_login_required
    @data_api(write=True)
    def api_resume_delete(resume_id: int):
        if not delete_resume(g.user, resume_id):
            return fail("That resume was not found in your vault.", 404)
        return ok({"resumes": list_resumes(g.user)})

    @app.post("/api/resumes/<int:resume_id>/primary")
    @api_login_required
    @data_api(write=True)
    def api_resume_primary(resume_id: int):
        if not set_primary(g.user, resume_id):
            return fail("That resume was not found in your vault.", 404)
        return ok({"resumes": list_resumes(g.user)})

    @app.get("/api/resumes/<int:resume_id>/detected")
    @api_login_required
    @data_api()
    def api_resume_detected(resume_id: int):
        """Skill detection preview for one resume (AI helps only when ?ai=1)."""
        from services.skill_service import preview_detection

        resume = get_resume(g.user, resume_id)
        if not resume:
            return fail("That resume was not found in your vault.", 404)
        use_ai = request.args.get("ai") in ("1", "true", "yes")
        preview = preview_detection(g.user, resume.extracted_text or "", use_ai=use_ai)
        preview["resume"] = {"id": resume.id, "version": resume.version,
                             "filename": resume.filename}
        return ok(preview)

    @app.post("/api/resumes/<int:resume_id>/detected")
    @api_login_required
    @data_api(write=True)
    def api_resume_add_detected(resume_id: int):
        """Save selected detected skills to the user's profile (source=resume)."""
        from models import dump_json, load_json, db

        resume = get_resume(g.user, resume_id)
        if not resume:
            return fail("That resume was not found in your vault.", 404)
        selected = json_payload().get("skills")
        detected = load_json(resume.detected_skills, []) or []
        if not isinstance(selected, list) or not selected:
            selected = detected  # "Select all" convenience

        allowed = {name.lower(): name for name in detected}
        added, skipped = [], []
        for raw in selected[:40]:
            name = clean_text(raw, 60)
            if len(name) < 2:
                continue
            # Only skills that were genuinely detected may be bulk-added here.
            canonical = allowed.get(name.lower())
            if canonical is None:
                skipped.append(name)
                continue
            row, created = add_user_skill(g.user, canonical, source="resume")
            (added if created else skipped).append(
                row.skill.name if row and row.skill else canonical)
        if added:
            resume.detected_skills = dump_json(detected)
            db.session.commit()
        return ok({"added": added, "skipped": skipped, "skills": list_skills(g.user)})

    @app.get("/api/resumes/compare")
    @api_login_required
    @data_api()
    def api_resume_compare():
        older, newer = request.args.get("older", ""), request.args.get("newer", "")
        if not older.isdigit() or not newer.isdigit():
            return fail("Select two resumes to compare.", 400)
        try:
            return ok(compare_resumes(g.user, int(older), int(newer)))
        except ResumeStoreError as exc:
            return fail(exc.message, exc.status)
