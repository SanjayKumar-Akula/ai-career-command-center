"""Dashboard history: the current career snapshot vs the previous one.

Read-only aggregation for ``GET /api/dashboard``. Every value is read from rows
the app has already stored — Resume, ResumeAnalysis, SkillHistory, UserSkill,
Activity and CareerRoadmap — so the dashboard can show how a profile evolved
over time without duplicating storage and without ever inventing a score, a
skill or a gap.

Nothing in this module writes, updates or deletes a row: it only issues
SELECTs, so loading the dashboard can never change a user's data.
"""

from __future__ import annotations

from models import (Activity, CareerRoadmap, Resume, SkillHistory, UserSkill,
                    db)
from services.resume_store import (diff_analyses, factor_comparison,
                                   insight_skill_names, latest_two_analyses)
from services.skill_service import user_skill_map

NO_ANALYSIS = "Upload your first resume to start tracking your progress over time."
NEEDS_PREVIOUS = "Complete another resume analysis to see your progress over time."


def build_history(user, roadmap=None) -> dict:
    """The ``history`` block of GET /api/dashboard for the session user only.

    ``roadmap`` is the row the endpoint has already loaded; passing it in keeps
    the dashboard to one roadmap query. Every query below filters on ``user.id``,
    so another account's resumes, skills, analyses or roadmap can never leak.
    """
    current, previous = latest_two_analyses(user)
    cut_off = previous.created_at if previous else None

    skills = _skill_progress(user, cut_off)
    if current is not None and previous is not None:
        delta = diff_analyses(previous, current)
        ats_delta = delta["score_delta"]
        gaps_closed, gaps_opened = delta["resolved_gaps"], delta["new_gaps"]
        factors = _factor_progress(previous, current)
    else:
        # No earlier analysis: report "unknown", never a fabricated comparison.
        ats_delta, gaps_closed, gaps_opened, factors = None, [], [], []

    return {
        "has_previous": bool(current is not None and previous is not None),
        "message": _message(current, previous),
        "current": _summary(user, current),
        "previous": _summary(user, previous),
        "ats_delta": ats_delta,
        "skills_added": skills["added"],
        "skills_removed": skills["removed"],
        "gaps_closed": gaps_closed,
        "gaps_opened": gaps_opened,
        "skills": {"current_total": skills["current_total"],
                   "previous_total": skills["previous_total"],
                   "delta": skills["delta"]},
        "gaps": {"current_missing": _missing_count(current),
                 "previous_missing": _missing_count(previous)},
        "roadmap_progress": _roadmap_progress(user, roadmap),
        "factors": factors,
        "activities_since_previous": _activities_since(user, cut_off),
    }


def _message(current, previous) -> str:
    """Friendly empty-state guidance (empty once a comparison is possible)."""
    if current is None:
        return NO_ANALYSIS
    if previous is None:
        return NEEDS_PREVIOUS
    return ""


def _summary(user, row) -> dict | None:
    """JSON-safe label for one stored analysis (owned resumes only)."""
    if row is None:
        return None
    resume = db.session.get(Resume, row.resume_id) if row.resume_id else None
    if resume is not None and resume.user_id != user.id:
        resume = None  # defence in depth: never label another account's file
    return {
        "analysis_id": row.id,
        "resume_id": row.resume_id,
        "resume_name": resume.filename if resume else "",
        "version": resume.version if resume else None,
        "target_role": row.target_role or "",
        "ats_score": row.ats_score,
        "ai_enhanced": bool(row.ai_enhanced),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _missing_count(row) -> int | None:
    """How many gaps the stored analysis itself reported (None when none)."""
    if row is None:
        return None
    return len(insight_skill_names(row.insights))


def _factor_progress(previous, current) -> list:
    """The six ATS factors, relabelled old/new -> previous/current."""
    return [{"label": item["label"], "previous": item["old"],
             "current": item["new"], "delta": item["delta"], "max": item["max"]}
            for item in factor_comparison(previous, current)]


def _skill_progress(user, cut_off) -> dict:
    """Skill totals now, plus what SkillHistory recorded since the cut-off.

    The history log is append-only and written by every skill change
    (``added`` / ``updated`` / ``removed``), so the earlier total can be rebuilt
    from it — nothing is deleted, modified or stored twice.
    """
    current_total = UserSkill.query.filter_by(user_id=user.id).count()
    if cut_off is None:
        return {"current_total": current_total, "previous_total": None,
                "delta": None, "added": [], "removed": []}

    rows = (SkillHistory.query.filter_by(user_id=user.id)
            .filter(SkillHistory.created_at > cut_off)
            .order_by(SkillHistory.created_at.asc(), SkillHistory.id.asc()).all())
    first_seen: dict = {}
    latest: dict = {}
    for row in rows:
        name = (row.skill_name or "").strip()
        if not name:
            continue
        first_seen.setdefault(name, row.change_type)
        latest[name] = row.change_type

    present = set(user_skill_map(user))
    added = sorted(name for name, kind in latest.items() if kind == "added")
    removed = sorted(name for name, kind in latest.items() if kind == "removed")
    # Rebuild the earlier total from the same log: a skill first logged as
    # "added" after the cut-off did not exist before it, and one first logged as
    # "removed" did. A skill added *and* removed inside the window therefore
    # cancels out instead of skewing the count.
    fresh = sum(1 for name, kind in first_seen.items()
                if kind == "added" and name.lower() in present)
    gone = sum(1 for name, kind in first_seen.items()
               if kind == "removed" and name.lower() not in present)
    previous_total = max(current_total - fresh + gone, 0)
    return {"current_total": current_total, "previous_total": previous_total,
            "delta": current_total - previous_total,
            "added": added, "removed": removed}


def _roadmap_progress(user, roadmap=None) -> dict:
    """Current roadmap completion, plus the earlier snapshot when one exists.

    Roadmaps are stored per (user, target role) and progress is updated in
    place, so a *previous* value only exists when the user has an older roadmap
    row; otherwise it is reported as null rather than guessed.
    """
    if roadmap is None:
        roadmap = (CareerRoadmap.query.filter_by(user_id=user.id)
                   .order_by(CareerRoadmap.updated_at.desc(),
                             CareerRoadmap.id.desc()).first())
    if roadmap is None:
        return {"current": None, "previous": None, "delta": None,
                "current_role": "", "previous_role": "", "has_previous": False,
                "updated_at": None}

    updated_at = roadmap.updated_at.isoformat() if roadmap.updated_at else None
    earlier = (CareerRoadmap.query.filter_by(user_id=user.id)
               .filter(CareerRoadmap.id != roadmap.id)
               .order_by(CareerRoadmap.updated_at.desc(),
                         CareerRoadmap.id.desc()).first())
    current = roadmap.progress_percent or 0
    if earlier is None:
        return {"current": current, "previous": None, "delta": None,
                "current_role": roadmap.target_role or "", "previous_role": "",
                "has_previous": False, "updated_at": updated_at}

    previous = earlier.progress_percent or 0
    return {"current": current, "previous": previous,
            "delta": current - previous,
            "current_role": roadmap.target_role or "",
            "previous_role": earlier.target_role or "",
            "has_previous": True, "updated_at": updated_at}


def _activities_since(user, cut_off) -> int:
    """How many timeline entries were logged since the previous analysis."""
    if cut_off is None:
        return 0
    return (Activity.query.filter_by(user_id=user.id)
            .filter(Activity.created_at > cut_off).count())
