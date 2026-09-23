"""AI resume builder.

Hard rule: the builder may only RE-WORD information the user has already
provided (profile, skills, resume text, analyses). It must never invent
companies, degrees, certifications, projects, metrics or job titles.

Every generated bullet is additionally verified against the source material:
any bullet that introduces a number which does not appear in the user's own
data is dropped before the draft is shown or exported.
"""

from __future__ import annotations

import logging
import re

from models import GeneratedResume, Resume, dump_json, load_json, db
from services.ai_client import AIServiceError, call_ai, parse_ai_json
from services.gap_engine import compute_gap_analysis
from services.resume_pdf import normalise_content
from services.skill_service import list_skills

logger = logging.getLogger("resume_builder")

MAX_RESUME_CHARS = 5000

SYSTEM_INSTRUCTION = (
    "You are an ATS-focused resume editor. You rewrite ONLY the facts supplied "
    "by the candidate. You never invent employers, job titles, dates, degrees, "
    "certifications, projects, technologies, metrics or achievements. If a "
    "detail is missing you leave it empty instead of guessing. You reply with a "
    "single valid JSON object and never include URLs."
)

PROMPT_TEMPLATE = """Improve this candidate's resume content for the target role "{role}".

FACTS SUPPLIED BY THE CANDIDATE (the ONLY information you may use):
{facts}

Return ONLY a valid JSON object with EXACTLY this shape:
{{
  "summary": "2-3 sentence professional summary using only the facts above",
  "skills": ["skill", "..."],
  "education": "one-line education line using only the facts above",
  "experience": [{{"title": "...", "org": "...", "period": "...", "bullets": ["achievement-focused bullet"]}}],
  "projects": [{{"title": "...", "org": "...", "period": "...", "bullets": ["bullet"]}}],
  "certifications": ["..."],
  "achievements": ["..."],
  "missing_info": ["facts the candidate still needs to provide"]
}}

Rules:
- Reword and organise the supplied facts; never add new facts.
- NEVER invent numbers. Only reuse numbers that appear in the facts above.
- Keep every bullet under 25 words, start with a strong action verb.
- If a section has no source facts, return an empty list or empty string.
- No markdown, no URLs, JSON only."""


def _collect_facts(user, resume: Resume | None = None) -> dict:
    """Everything the AI is allowed to use, taken from the user's own data."""
    profile = user.profile
    skills = [row["name"] for row in list_skills(user)]
    resume_text = (resume.extracted_text or "")[:MAX_RESUME_CHARS] if resume else ""

    return {
        "full_name": user.full_name or "",
        "target_role": (profile.target_role if profile else "")
                        or (resume.target_role if resume else ""),
        "education": (profile.education if profile else ""),
        "college": (profile.college if profile else ""),
        "degree": (profile.degree if profile else ""),
        "graduation_year": (profile.graduation_year if profile else ""),
        "experience_notes": (profile.experience if profile else ""),
        "career_goal": (profile.career_goal if profile else ""),
        "preferred_job_type": (profile.preferred_job_type if profile else ""),
        "skills": skills,
        "resume_text": resume_text,
    }


def _facts_block(facts: dict) -> str:
    return "\n".join(f"{key}: {value}" for key, value in facts.items() if value) \
        or "(no facts supplied yet)"


def _source_corpus(facts: dict) -> str:
    """Lower-cased text used to verify numbers/claims in generated output."""
    parts = [str(value) for value in facts.values() if isinstance(value, str)]
    parts.extend(str(item) for item in facts.get("skills", []))
    return " " + re.sub(r"\s+", " ", " ".join(parts).lower()) + " "


_NUMBER_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?\s*(?:%|\+|percent|k|m|users|students|records|projects|members|hours)?)")


def _numbers_in(text: str) -> set:
    found = set()
    for match in _NUMBER_RE.finditer(text or ""):
        token = match.group(1).strip().lower().replace(",", "")
        if token:
            found.add(token)
    return found


def _strip_unverifiable(items: list, corpus: str) -> tuple:
    """Drop generated strings whose numbers do not exist in the source facts."""
    kept, dropped = [], []
    for item in items:
        numbers = _numbers_in(item)
        if numbers and not all(num in corpus for num in numbers):
            dropped.append(item)
            continue
        kept.append(item)
    return kept, dropped


def _verify_entries(entries: list, corpus: str) -> tuple:
    """Apply the honesty gate to experience/project bullets."""
    kept_rows, dropped = [], []
    for row in entries:
        bullets, removed = _strip_unverifiable(row.get("bullets", []), corpus)
        dropped.extend(removed)
        if not bullets and row.get("bullets"):
            # Every bullet was unsupported: keep the entry only when its own
            # title was supplied by the user, otherwise drop it entirely.
            if row.get("title") and row["title"].lower() in corpus:
                kept_rows.append({**row, "bullets": []})
            continue
        kept_rows.append({**row, "bullets": bullets})
    return kept_rows, dropped


def _deterministic_draft(facts: dict) -> dict:
    """Fact-only fallback used when the AI is unavailable."""
    education_bits = [bit for bit in (facts["degree"], facts["college"],
                                      facts["graduation_year"]) if bit]
    return {
        "summary": "",
        "skills": list(facts["skills"])[:20],
        "education": ", ".join(education_bits),
        "experience": ([{"title": "Experience", "org": "", "period": "",
                         "bullets": [facts["experience_notes"]]}]
                       if facts["experience_notes"] else []),
        "projects": [],
        "certifications": [],
        "achievements": [],
        "missing_info": [],
    }


def _coerce_str_list(value, limit: int = 20) -> list:
    items = []
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, str) and entry.strip():
                items.append(entry.strip()[:240])
    return items[:limit]


def _coerce_entries(value, limit: int = 10) -> list:
    rows = []
    if not isinstance(value, list):
        return rows
    for entry in value:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()[:120]
        org = str(entry.get("org") or entry.get("company") or "").strip()[:160]
        period = str(entry.get("period") or "").strip()[:60]
        bullets = _coerce_str_list(entry.get("bullets"), 5)
        if title or org or bullets:
            rows.append({"title": title, "org": org, "period": period,
                         "bullets": bullets})
    return rows[:limit]


def _missing_fields(facts: dict, content: dict, ai_missing: list) -> list:
    """Concrete prompts for the information the user still has to provide."""
    prompts = []
    if not (facts.get("experience_notes") or content["experience"]):
        prompts.append("Add your internships, freelance or work experience (role, organisation, dates).")
    if not content["projects"]:
        prompts.append("Add 1-3 academic or personal projects with the tech stack you really used.")
    if not content["education"]:
        prompts.append("Add your degree, college and graduation year in your profile.")
    if not content["certifications"]:
        prompts.append("Add any certifications you have completed (leave empty if none).")
    if not content.get("achievements"):
        prompts.append("Add measurable achievements (only if you have real numbers).")
    seen = {p.lower() for p in prompts}
    for item in ai_missing:
        if isinstance(item, str) and item.strip() and item.strip().lower() not in seen:
            prompts.append(item.strip()[:200])
            seen.add(item.strip().lower())
    return prompts[:8]


# ---------------------------------------------------------------------------
# Public builder API
# ---------------------------------------------------------------------------

class BuilderError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _resume_for(user, resume_id: int | None) -> Resume | None:
    if resume_id is None:
        return None
    return Resume.query.filter_by(id=resume_id, user_id=user.id).first()


def _stringify(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def _contact_line(user, resume: Resume | None) -> str:
    """Contact details are taken from the resume text when present (never invented)."""
    text = (resume.extracted_text or "") if resume else ""
    parts = []
    for pattern in (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                    r"(?:\+?\d[\d\s().-]{7,}\d)"):
        match = re.search(pattern, text)
        if match:
            parts.append(match.group(0).strip())
    return "  •  ".join(parts)


def build_resume(user, resume_id: int | None = None, force_ai: bool = True) -> dict:
    """Generate (or regenerate) an ATS-friendly draft from the user's own facts.

    Returns {draft, content, missing_info, source, ai_enhanced, ai_notice}.
    AI output is validated and every numeric claim is re-checked against the
    source facts before it is accepted (see _verify_entries/_strip_unverifiable).
    """
    resume = _resume_for(user, resume_id)
    facts = _collect_facts(user, resume)
    corpus = _source_corpus(facts)

    content, source, ai_enhanced, ai_notice = None, "deterministic", False, None

    if force_ai:
        role = facts["target_role"] or "target role"
        try:
            raw = call_ai(_build_content_prompt(role, facts),
                          system=SYSTEM_INSTRUCTION, temperature=0.4)
            data = parse_ai_json(raw)
            content = {
                "summary": _stringify(data.get("summary")),
                "skills": _coerce_str_list(data.get("skills"), 20) or facts["skills"],
                "education": _stringify(data.get("education")),
                "experience": _coerce_entries(data.get("experience")),
                "projects": _coerce_entries(data.get("projects")),
                "certifications": _coerce_str_list(data.get("certifications"), 10),
                "achievements": _coerce_str_list(data.get("achievements"), 10),
            }
            content["experience"], _ = _verify_entries(content["experience"], corpus)
            content["projects"], _ = _verify_entries(content["projects"], corpus)
            content["certifications"], _ = _strip_unverifiable(
                content["certifications"], corpus)
            content["achievements"], _ = _strip_unverifiable(
                content["achievements"], corpus)
            # Skills may only be re-ordered / trimmed, never invented.
            owned = {name.lower() for name in facts["skills"]}
            kept = [s for s in content["skills"] if s.lower() in owned]
            content["skills"] = kept or facts["skills"]
            source, ai_enhanced = "ai", True
        except AIServiceError as exc:
            ai_notice = exc.message
        except Exception:
            logger.warning("Resume builder AI output unusable; using facts only",
                           exc_info=True)
            ai_notice = ("The AI service returned an unexpected response. "
                         "Showing a facts-only draft.")

    if content is None:
        content = _deterministic_draft(facts)

    content = normalise_content(content)
    content["name"] = user.full_name or ""
    if not content["contact"]:
        content["contact"] = _contact_line(user, resume)

    missing = _missing_fields(facts, content, [])

    # Persist as the user's current draft (one draft per user, reused).
    draft = (GeneratedResume.query.filter_by(user_id=user.id)
             .order_by(GeneratedResume.created_at.desc()).first())
    if draft is None:
        draft = GeneratedResume(user_id=user.id)
        db.session.add(draft)
    draft.title = f"Resume — {facts['target_role'] or 'General'}"
    draft.target_role = facts["target_role"] or ""
    draft.content_json = dump_json(content)
    db.session.commit()

    return {
        "draft": draft.to_dict(include_content=False),
        "content": content,
        "missing_info": missing,
        "source": source,
        "ai_enhanced": ai_enhanced,
        "ai_notice": ai_notice,
        "facts_used": {key: value for key, value in facts.items()
                       if key != "resume_text"},
    }


def _build_content_prompt(role: str, facts: dict) -> str:
    return PROMPT_TEMPLATE.format(role=role, facts=_facts_block(facts))
