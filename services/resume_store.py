"""Resume vault: per-user storage, versioning, re-analysis, comparison."""

from __future__ import annotations

import logging

from models import Resume, ResumeAnalysis, db, dump_json, load_json
from services.pdf_extractor import PDFExtractionError, extract_text_from_pdf
from services.resume_analyzer import analyze_resume
from services.validation import MAX_RESUME_BYTES, clean_text

logger = logging.getLogger("resume_store")


class ResumeStoreError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def list_resumes(user) -> list:
    rows = (Resume.query.filter_by(user_id=user.id)
            .order_by(Resume.version.desc()).all())
    return [row.to_dict() for row in rows]


def get_resume(user, resume_id: int):
    """Ownership-checked fetch — a user can only ever touch their own rows."""
    return Resume.query.filter_by(id=resume_id, user_id=user.id).first()


def latest_analysis(resume: Resume):
    return (ResumeAnalysis.query.filter_by(resume_id=resume.id, user_id=resume.user_id)
            .order_by(ResumeAnalysis.created_at.desc()).first())


def upload_and_analyze(user, file_storage, target_role: str) -> dict:
    """Validate → extract → next version → store → analyze → persist analysis."""
    target_role = clean_text(target_role, 80)
    if len(target_role) < 3:
        raise ResumeStoreError("Please enter a target role (e.g., Software Developer).")
    if file_storage is None or not (file_storage.filename or "").strip():
        raise ResumeStoreError("Please choose a PDF resume to upload.")
    filename = (file_storage.filename or "").strip()
    if not filename.lower().endswith(".pdf"):
        raise ResumeStoreError("Only PDF files are supported. Please upload a .pdf resume.")

    pdf_bytes = file_storage.read()
    if not pdf_bytes:
        raise ResumeStoreError("The uploaded file is empty. Please choose a valid PDF resume.")
    if len(pdf_bytes) > MAX_RESUME_BYTES:
        raise ResumeStoreError("Resume is too large. Maximum allowed size is 5 MB.", 413)

    try:
        text = extract_text_from_pdf(pdf_bytes)
    except PDFExtractionError as exc:
        raise ResumeStoreError(exc.message)

    last = (Resume.query.filter_by(user_id=user.id)
            .order_by(Resume.version.desc()).first())
    version = (last.version + 1) if last else 1

    resume = Resume(
        user_id=user.id,
        filename=filename[:255],
        version=version,
        target_role=target_role,
        extracted_text=text,
        file_data=pdf_bytes,
    )
    db.session.add(resume)
    db.session.commit()

    result = _run_analysis_and_side_effects(user, resume)
    return {"resume": resume.to_dict(include_detected=True), "analysis": result, }


def _detect_and_store(resume: Resume) -> list:
    """Automatic (instant, deterministic) skill extraction for a resume."""
    from services.skill_service import detect_skills_in_text

    detected = detect_skills_in_text(resume.extracted_text)
    resume.detected_skills = dump_json(detected)
    db.session.commit()
    return detected


def _run_analysis_and_side_effects(user, resume: Resume) -> dict:
    """Persist the analysis, then log activity + notifications (best effort)."""
    from services.activity_service import (
        generate_gap_notification,
        generate_score_improvement_notification,
        log_activity,
    )
    from services.gap_engine import compute_gap_analysis

    previous_score = None
    prior = (ResumeAnalysis.query.filter_by(user_id=user.id)
             .order_by(ResumeAnalysis.created_at.desc()).first())
    if prior:
        previous_score = prior.ats_score

    result = run_analysis(user, resume)

    try:
        detected = _detect_and_store(resume)
        if detected:
            log_activity(user, "skills_detected",
                         f"Detected {len(detected)} skills in {resume.filename}",
                         {"count": len(detected), "resume_id": resume.id})
        log_activity(user, "resume_analyzed",
                     f"{resume.filename} analyzed — ATS {resume.ats_score}/100",
                     {"resume_id": resume.id, "ats_score": resume.ats_score,
                      "target_role": resume.target_role, "version": resume.version})
        if previous_score is not None:
            generate_score_improvement_notification(user, previous_score,
                                                    resume.ats_score or 0)
        gap = compute_gap_analysis(user, resume.target_role)
        if gap.get("has_role"):
            generate_gap_notification(user, len(gap["missing"]), resume.target_role)
        db.session.commit()
    except Exception:  # pragma: no cover - never fail an upload over logging
        logger.warning("Post-analysis bookkeeping failed", exc_info=True)
        db.session.rollback()

    result["detected_skills"] = load_json(resume.detected_skills, [])
    return result

def run_analysis(user, resume: Resume) -> dict:
    """Run the deterministic + AI analysis and persist it as a new row."""
    result = analyze_resume(resume.extracted_text, resume.target_role)
    breakdown = result.get("score_breakdown", [])

    insights = {
        "strengths": result.get("strengths", []),
        "weaknesses": result.get("weaknesses", []),
        "missing_skills": result.get("missing_skills", []),
        "improvement_areas": result.get("improvement_areas", []),
        "ats_checks": result.get("ats_checks", []),
        "target_role_match": result.get("target_role_match", ""),
        "recommended_keywords": result.get("recommended_keywords", []),
        "matched_keywords": result.get("matched_keywords", []),
        "missing_keywords": result.get("missing_keywords", []),
    }

    row = ResumeAnalysis(
        resume_id=resume.id,
        user_id=user.id,
        target_role=result.get("target_role", resume.target_role),
        ats_score=result.get("ats_score", 0),
        keyword_score=breakdown[0]["score"] if len(breakdown) > 0 else 0,
        skills_score=breakdown[1]["score"] if len(breakdown) > 1 else 0,
        experience_score=breakdown[2]["score"] if len(breakdown) > 2 else 0,
        education_score=breakdown[3]["score"] if len(breakdown) > 3 else 0,
        formatting_score=breakdown[4]["score"] if len(breakdown) > 4 else 0,
        sections_score=breakdown[5]["score"] if len(breakdown) > 5 else 0,
        breakdown_json=dump_json(breakdown),
        insights_json=dump_json(insights),
        ai_enhanced=bool(result.get("ai_enhanced")),
    )
    resume.ats_score = result.get("ats_score", 0)
    resume.target_role = result.get("target_role", resume.target_role)
    db.session.add(row)
    db.session.commit()
    return result

def compare_resumes(user, older_id: int, newer_id: int) -> dict:
    """Compare two of the user's own resume analyses factor by factor."""
    older, newer = get_resume(user, older_id), get_resume(user, newer_id)
    if not older or not newer:
        raise ResumeStoreError("One or both resumes were not found in your vault.")
    old_analysis = latest_analysis(older)
    new_analysis = latest_analysis(newer)
    if not old_analysis or not new_analysis:
        raise ResumeStoreError("Both resumes need at least one analysis before comparing.")

    labels = ["Keyword Match", "Skills Match", "Experience / Projects",
              "Education", "ATS Formatting", "Section Completeness"]
    old_b = {item.get("label"): item for item in (old_analysis.breakdown or [])}
    new_b = {item.get("label"): item for item in (new_analysis.breakdown or [])}
    factors = []
    for label in labels:
        old_item, new_item = old_b.get(label, {}), new_b.get(label, {})
        old_score, new_score = old_item.get("score", 0), new_item.get("score", 0)
        factors.append({
            "label": label,
            "old": old_score, "new": new_score,
            "max": max(old_item.get("max", 0), new_item.get("max", 0)),
            "delta": round(new_score - old_score, 1),
        })

    old_ins = old_analysis.insights or {}
    new_ins = new_analysis.insights or {}

    def _names(items):
        return {s.get("skill") if isinstance(s, dict) else str(s) for s in items}

    old_missing, new_missing = _names(old_ins.get("missing_skills", [])), _names(new_ins.get("missing_skills", []))
    old_kw = {str(k).lower() for k in old_ins.get("matched_keywords", [])}
    new_kw = {str(k).lower() for k in new_ins.get("matched_keywords", [])}
    old_skills = set(load_json(older.detected_skills, []) or [])
    new_skills = set(load_json(newer.detected_skills, []) or [])

    return {
        "old": {"resume": older.to_dict(include_detected=True),
                "analysis": old_analysis.to_dict()},
        "new": {"resume": newer.to_dict(include_detected=True),
                "analysis": new_analysis.to_dict()},
        "factors": factors,
        "score_delta": new_analysis.ats_score - old_analysis.ats_score,
        "resolved_gaps": sorted(old_missing - new_missing),
        "new_gaps": sorted(new_missing - old_missing),
        "skills": {"old": sorted(old_skills), "new": sorted(new_skills),
                   "added": sorted(new_skills - old_skills),
                   "removed": sorted(old_skills - new_skills)},
        "keywords": {"added": sorted(new_kw - old_kw),
                     "removed": sorted(old_kw - new_kw)},
        "improved": new_analysis.ats_score > old_analysis.ats_score,
    }


def delete_resume(user, resume_id: int) -> bool:
    resume = get_resume(user, resume_id)
    if not resume:
        return False
    db.session.delete(resume)  # cascades to its analyses
    db.session.commit()
    return True


def set_primary(user, resume_id: int) -> bool:
    resume = get_resume(user, resume_id)
    if not resume:
        return False
    Resume.query.filter_by(user_id=user.id).update({"is_primary": False})
    resume.is_primary = True
    db.session.commit()
    return True


def reanalyze(user, resume: Resume) -> dict:
    """Re-run the analysis for an existing resume (with side effects)."""
    return _run_analysis_and_side_effects(user, resume)


def resume_detail(user, resume_id: int) -> dict:
    """Full detail view for one of the user's resumes (ownership enforced)."""
    resume = get_resume(user, resume_id)
    if not resume:
        raise ResumeStoreError("That resume was not found in your vault.", 404)
    analysis = latest_analysis(resume)
    data = resume.to_dict(include_detected=True)
    data["word_count"] = len((resume.extracted_text or "").split())
    return {
        "resume": data,
        "analysis": analysis.to_dict() if analysis else None,
        "detected_skills": load_json(resume.detected_skills, []),
    }


def ats_history(user, limit: int = 50) -> list:
    """Every stored analysis (oldest → newest) for the ATS progress chart."""
    rows = (ResumeAnalysis.query.filter_by(user_id=user.id)
            .order_by(ResumeAnalysis.created_at.asc()).limit(limit).all())
    history = []
    for row in rows:
        resume = db.session.get(Resume, row.resume_id)
        history.append({
            "analysis_id": row.id,
            "resume_id": row.resume_id,
            "resume_name": (resume.filename if resume else ""),
            "version": (resume.version if resume else None),
            "target_role": row.target_role,
            "ats_score": row.ats_score,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })
    return history


