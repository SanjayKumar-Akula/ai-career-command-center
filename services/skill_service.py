"""Skill management: catalog lookup, extraction (deterministic + AI), CRUD."""

from __future__ import annotations

import logging

from models import Skill, SkillHistory, UserSkill, db
from services.ai_client import AIServiceError, call_ai, parse_ai_json
from services.resume_analyzer import _contains_term, _norm

logger = logging.getLogger("skill_service")

MAX_DETECTED = 30


def _record_history(user, skill_name: str, from_value: int, to_value: int,
                    change_type: str) -> None:
    """Append to the skill-growth log (best effort — never blocks the action)."""
    if not skill_name:
        return
    try:
        db.session.add(SkillHistory(user_id=user.id, skill_name=skill_name[:120],
                                    from_value=int(from_value or 0),
                                    to_value=int(to_value or 0),
                                    change_type=change_type))
        db.session.commit()
        from services.activity_service import log_activity
        verb = {"added": "added", "updated": "updated", "removed": "removed"}.get(
            change_type, "updated")
        log_activity(user, "skill_" + change_type, f"Skill {verb}: {skill_name}",
                     {"skill": skill_name, "from": from_value, "to": to_value,
                      "delta": int(to_value or 0) - int(from_value or 0)})
        db.session.commit()
    except Exception:  # pragma: no cover - history must never break an action
        logger.warning("Could not record skill history", exc_info=True)
        db.session.rollback()


def skill_growth(user, limit: int = 12) -> dict:
    """Recent skill changes plus the strongest movers (for the dashboard)."""
    rows = (SkillHistory.query.filter_by(user_id=user.id)
            .order_by(SkillHistory.created_at.desc()).limit(limit).all())
    changes = [row.to_dict() for row in rows]

    deltas: dict = {}
    for row in SkillHistory.query.filter_by(user_id=user.id).all():
        deltas[row.skill_name] = deltas.get(row.skill_name, 0) + (
            (row.to_value or 0) - (row.from_value or 0))
    movers = sorted(
        ({"skill": name, "delta": delta} for name, delta in deltas.items() if delta > 0),
        key=lambda item: -item["delta"])[:5]
    return {"changes": changes, "top_growth": movers}


def get_or_create_skill(name: str) -> Skill | None:
    """Find a catalog skill by (case-insensitive) name or create it."""
    from models import _display_name, _guess_category

    norm = _norm(name)
    if not norm or len(norm) > 100:
        return None
    display = _display_name(norm)
    skill = Skill.query.filter(db.func.lower(Skill.name) == display.lower()).first()
    if skill:
        return skill
    skill = Skill(name=display, category=_guess_category(norm))
    db.session.add(skill)
    db.session.commit()
    return skill


def add_user_skill(user, name: str, source: str = "manually_added",
                   proficiency: int | None = None):
    """Add a skill to a user's profile; duplicates are never created.

    Returns (UserSkill, created: bool).
    """
    skill = get_or_create_skill(name)
    if skill is None:
        return None, False
    existing = UserSkill.query.filter_by(user_id=user.id, skill_id=skill.id).first()
    if existing:
        return existing, False
    row = UserSkill(
        user_id=user.id,
        skill_id=skill.id,
        source=source if source in ("resume", "manually_added", "AI_suggested") else "manually_added",
        proficiency=max(0, min(100, int(proficiency))) if proficiency is not None else 40,
    )
    db.session.add(row)
    db.session.commit()
    _record_history(user, skill.name, 0, row.proficiency, "added")
    return row, True


def bulk_add_skills(user, names, source: str = "resume") -> dict:
    added, skipped = [], []
    for raw in names or []:
        name = str(raw).strip()
        if not name:
            continue
        row, created = add_user_skill(user, name, source=source)
        if created:
            added.append(row.skill.name)
        else:
            skipped.append(row.skill.name if row else name)
    return {"added": added, "skipped": skipped}


def list_user_skills(user) -> list:
    rows = (UserSkill.query.filter_by(user_id=user.id)
            .join(Skill).order_by(Skill.category, Skill.name).all())
    return [row.to_dict() for row in rows]


# Backwards-compatible alias: the API modules import ``list_skills``.
list_skills = list_user_skills


def get_user_skill(user, uskill_id: int):
    return UserSkill.query.filter_by(id=uskill_id, user_id=user.id).first()

def update_proficiency(user, uskill_id: int, value: int):
    row = get_user_skill(user, uskill_id)
    if not row:
        return None
    previous = row.proficiency or 0
    row.proficiency = max(0, min(100, int(value)))
    db.session.commit()
    if row.proficiency != previous:
        _record_history(user, row.skill.name if row.skill else "", previous,
                        row.proficiency, "updated")
    return row


def remove_user_skill(user, uskill_id: int) -> bool:
    row = get_user_skill(user, uskill_id)
    if not row:
        return False
    name = row.skill.name if row.skill else ""
    value = row.proficiency or 0
    db.session.delete(row)
    db.session.commit()
    _record_history(user, name, value, 0, "removed")
    return True


def user_skill_map(user) -> dict:
    """{lowercase skill name: proficiency} for fast comparisons."""
    rows = UserSkill.query.filter_by(user_id=user.id).join(Skill).all()
    return {row.skill.name.lower(): row.proficiency for row in rows if row.skill}


def catalog_names() -> list:
    return [s.name for s in Skill.query.order_by(Skill.name).all()]


def detect_skills_in_text(text: str) -> list:
    """Deterministic skill detection: scan the resume text for every catalog skill."""
    haystack = _norm(text)
    if not haystack:
        return []
    found = []
    for skill in Skill.query.all():
        if _contains_term(haystack, _norm(skill.name)):
            found.append(skill.name)
        if len(found) >= MAX_DETECTED:
            break
    return sorted(found)


_SKILL_PROMPT = """List the professional and technical skills that this resume demonstrates.

Return ONLY a valid JSON object: {"skills": ["Skill Name", "..."]}

Rules:
- 5-15 skills maximum, most relevant first.
- Use clean, conventional skill names (e.g. "Python", "REST API", "SQL").
- Only include skills actually evidenced in the resume text — never invent any.
- No URLs, no descriptions. JSON only.

RESUME TEXT:
"""


def ai_detect_skills(resume_text: str) -> list:
    """AI-assisted skill detection. Best-effort: returns [] on any AI failure."""
    try:
        raw = call_ai(_SKILL_PROMPT + resume_text[:6000],
                      system="You always reply with a single valid JSON object.",
                      temperature=0.1)
        data = parse_ai_json(raw)
    except AIServiceError as exc:
        logger.info("AI skill detection unavailable: %s", exc.message)
        return []
    except Exception:
        logger.warning("AI skill detection failed unexpectedly", exc_info=True)
        return []

    skills: list = []
    seen: set = set()
    raw_list = data.get("skills") if isinstance(data, dict) else None
    if isinstance(raw_list, list):
        for entry in raw_list:
            if not isinstance(entry, str):
                continue
            name = entry.strip()[:60]
            key = name.lower()
            if name and key not in seen and len(key) > 1:
                seen.add(key)
                skills.append(name)
    return skills[:15]


def preview_detection(user, text: str, use_ai: bool = False) -> dict:
    """Detection preview for a resume: which skills were found, which are new.

    Deterministic detection runs instantly; AI detection is opt-in so normal
    page loads never spend an API call.
    """
    found = detect_skills_in_text(text)
    ai_names = ai_detect_skills(text) if use_ai else []
    owned = set(user_skill_map(user))

    merged, seen = [], set()
    for name in list(found) + list(ai_names):
        label = str(name).strip()
        key = label.lower()
        if label and key not in seen:
            seen.add(key)
            merged.append(label)

    return {
        "detected": merged,
        "new": [n for n in merged if n.lower() not in owned],
        "already_saved": [n for n in merged if n.lower() in owned],
        "ai_used": bool(ai_names),
    }
