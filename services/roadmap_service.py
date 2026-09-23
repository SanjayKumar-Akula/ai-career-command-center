"""Personalized roadmap generation, persistence and progress tracking."""

from __future__ import annotations

import logging

from models import CareerRoadmap, db, dump_json, load_json
from services.ai_client import AIServiceError, call_ai, parse_ai_json
from services.career_guide import _coerce_list, _stringify  # reuse proven helpers
from services.gap_engine import compute_gap_analysis

logger = logging.getLogger("roadmap_service")

WEEKS = ("week_1", "week_2", "week_3", "week_4")
MONTHS = ("month_1", "month_2", "month_3")


def _active_roadmap(user, role: str):
    return (CareerRoadmap.query.filter_by(user_id=user.id, target_role=role)
            .order_by(CareerRoadmap.updated_at.desc()).first())


def get_roadmap(user, role: str | None = None):
    """Return the stored roadmap for the role (or the most recent one)."""
    if role:
        row = _active_roadmap(user, role.strip())
    else:
        row = (CareerRoadmap.query.filter_by(user_id=user.id)
               .order_by(CareerRoadmap.updated_at.desc()).first())
    if not row:
        return None
    return _serialize(row)


def _serialize(row: CareerRoadmap) -> dict:
    data = load_json(row.roadmap_json, {}) or {}
    return {
        "id": row.id,
        "target_role": row.target_role,
        "source": row.source,
        "progress_percent": row.progress_percent,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "roadmap": data.get("roadmap", {}),
        "extended": data.get("extended", {}),
        "task_state": data.get("task_state", {}),
    }


def _build_prompt(user, role: str, gap: dict) -> str:
    profile = getattr(user, "profile", None)
    known = ", ".join(s["name"] for s in (gap["strong"] + gap["developing"])[:12]) or "none yet"
    missing = ", ".join(g["name"] for g in gap["missing"][:8]) or "none — focus on depth"
    goal = profile.career_goal if profile and profile.career_goal else "not specified"
    experience = profile.experience if profile and profile.experience else "not specified"

    return f"""Build a personalized 30-day career plan for a candidate targeting "{role}".

Known skills: {known}
Missing skills: {missing}
Career goal: {goal}
Experience: {experience}

Return ONLY a valid JSON object with EXACTLY this shape:
{{
  "overview": "2 sentences on the strategy for this candidate",
  "roadmap": {{
    "week_1": [{{"topic": "...", "tasks": "...", "practice": "..."}}],
    "week_2": [{{"topic": "...", "tasks": "...", "practice": "..."}}],
    "week_3": [{{"topic": "...", "tasks": "...", "practice": "..."}}],
    "week_4": [{{"topic": "...", "tasks": "...", "practice": "..."}}]
  }},
  "extended": {{
    "month_1": ["2-4 concrete outcomes for month 1"],
    "month_2": ["..."],
    "month_3": ["..."]
  }}
}}

Rules:
- Exactly 4 weeks, 2-3 items per week; prioritise the missing skills.
- Progress from fundamentals (week 1) to interview readiness (week 4).
- extended: the 90-day view (months 1-3) as short outcome strings.
- No URLs. Keep strings under 25 words. JSON only."""

def generate_roadmap(user, role: str | None = None) -> dict:
    """Generate (AI) a roadmap for the role, persist it, and fall back to a
    deterministic plan built from the skill-gap data when AI is unavailable."""
    role = (role or "").strip()
    if not role:
        profile = getattr(user, "profile", None)
        role = profile.target_role if profile else ""
    if not role:
        raise ValueError("Set a target role first.")

    gap = compute_gap_analysis(user, role)
    source = "ai"
    ai_notice = None
    data = None
    try:
        raw = call_ai(
            _build_prompt(user, role, gap),
            system="You always reply with a single valid JSON object and never include URLs.",
            temperature=0.4)
        parsed = parse_ai_json(raw)
        data = {
            "roadmap": {week: _coerce_list(parsed.get("roadmap", {}).get(week), "topic")
                        for week in WEEKS},
            "extended": {month: [_stringify(x) for x in
                                 (parsed.get("extended", {}) or {}).get(month, [])[:4]]
                         for month in MONTHS},
            "overview": _stringify(parsed.get("overview")),
        }
        if not any(data["roadmap"].values()):
            raise ValueError("empty roadmap")
    except AIServiceError as exc:
        ai_notice = exc.message
        source = "deterministic"
    except Exception:
        logger.warning("Roadmap AI generation failed; using deterministic plan", exc_info=True)
        ai_notice = "AI is temporarily unavailable — showing a plan built from your skill-gap analysis."
        source = "deterministic"

    if data is None or source == "deterministic":
        data = _deterministic_plan(gap)

    # Preserve any existing task completion state for the same role.
    previous = _active_roadmap(user, role)
    task_state = {}
    if previous:
        prev = load_json(previous.roadmap_json, {}) or {}
        old_state = prev.get("task_state", {})
        for week in WEEKS:
            for index in range(len(data["roadmap"].get(week, []))):
                key = f"{week}:{index}"
                if key in old_state:
                    task_state[key] = old_state[key]

    row = previous or CareerRoadmap(user_id=user.id, target_role=role)
    row.source = source
    row.roadmap_json = dump_json({"roadmap": data["roadmap"],
                                  "extended": data.get("extended", {}),
                                  "task_state": task_state,
                                  "overview": data.get("overview", "")})
    _recalculate_progress(row)
    db.session.commit()
    result = _serialize(row)
    result["ai_notice"] = ai_notice
    return result


def _deterministic_plan(gap: dict) -> dict:
    """Fallback plan derived purely from the deterministic gap analysis."""
    missing = [g["name"] for g in gap["missing"]]
    developing = [g["name"] for g in gap["developing"]]
    role = gap.get("matched_role") or gap.get("target_role") or "your target role"

    def week(topics: list, focus: str) -> list:
        items = []
        for topic in topics:
            items.append({"topic": f"{topic} — {focus}",
                          "tasks": f"Study {topic} fundamentals and complete 2 tutorials",
                          "practice": f"Apply {topic} in a small hands-on exercise"})
        return items or [{"topic": f"{role} interview preparation",
                          "tasks": "Revise projects and prepare STAR stories",
                          "practice": "Mock interview practice, 3 rounds"}]

    w1 = missing[:2] or ["Core fundamentals"]
    w2 = missing[2:4] or developing[:2] or ["Applied projects"]
    w3 = developing[:2] or missing[4:6] or ["Portfolio depth"]
    return {
        "overview": f"A structured 4-week plan towards {role}, built from your current skill gaps.",
        "roadmap": {
            "week_1": week(w1, "fundamentals"),
            "week_2": week(w2, "guided practice"),
            "week_3": week(w3, "projects"),
            "week_4": week([], "interview readiness"),
        },
        "extended": {
            "month_1": [f"Cover {', '.join(w1 + w2) or 'core skills'} with daily practice"],
            "month_2": ["Build two portfolio projects using the new skills",
                        "Polish your resume with measurable achievements"],
            "month_3": ["Apply to 10+ matching roles", "Mock interviews and referral outreach"],
        },
    }


def set_task_state(user, roadmap_id: int, task_key: str, state: str) -> dict:
    """Persist a task status ('not_started' | 'in_progress' | 'completed')."""
    row = CareerRoadmap.query.filter_by(id=roadmap_id, user_id=user.id).first()
    if not row:
        raise LookupError("Roadmap not found.")
    if state not in ("not_started", "in_progress", "completed"):
        raise ValueError("Invalid task state.")
    data = load_json(row.roadmap_json, {}) or {}
    state_map = data.setdefault("task_state", {})
    if state == "not_started":
        state_map.pop(task_key, None)
    else:
        state_map[task_key] = state
    _recalculate_progress(row)
    db.session.commit()
    return _serialize(row)


def _recalculate_progress(row: CareerRoadmap) -> None:
    data = load_json(row.roadmap_json, {}) or {}
    roadmap = data.get("roadmap", {})
    total = sum(len(roadmap.get(w, [])) for w in WEEKS)
    state = data.get("task_state", {})
    completed = sum(1 for w in WEEKS for i in range(len(roadmap.get(w, [])))
                    if state.get(f"{w}:{i}") == "completed")
    row.progress_percent = round(100 * completed / total) if total else 0


