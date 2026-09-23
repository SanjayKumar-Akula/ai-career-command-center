"""Career Guide service: prompt construction, AI call, response validation."""

import logging

from services.ai_client import AIResponseError, call_ai, parse_ai_json
from services.resources import get_job_portals, get_learning_resources

logger = logging.getLogger("career_guide")

SYSTEM_INSTRUCTION = (
    "You are an encouraging, highly practical career coach for students and "
    "early-career job seekers. You always reply with a single valid JSON "
    "object and nothing else. You never include URLs or links."
)

PROMPT_TEMPLATE = """Create a personalized career plan for this candidate.

Candidate name: {name}
Current skills: {skills}
Target role: {role}

Return ONLY a valid JSON object with EXACTLY this shape:
{{
  "career_overview": "2-3 sentences: where this candidate stands and the overall path to the target role",
  "target_role": "{role}",
  "skills_analysis": [{{"skill": "...", "level": "beginner|intermediate|advanced", "comment": "one short sentence"}}],
  "skill_gaps": [{{"skill": "...", "why": "why it matters for the target role", "priority": "high|medium|low"}}],
  "roadmap": {{
    "week_1": [{{"topic": "...", "tasks": "concrete tasks", "practice": "hands-on practice idea"}}],
    "week_2": [{{"topic": "...", "tasks": "...", "practice": "..."}}],
    "week_3": [{{"topic": "...", "tasks": "...", "practice": "..."}}],
    "week_4": [{{"topic": "...", "tasks": "...", "practice": "..."}}]
  }},
    "pro_tips": ["3-5 short practical tips"]
}}

Rules:
- skills_analysis: one entry per skill the candidate listed (if there are more than 8, pick the 8 most relevant).
- skill_gaps: 4-8 skills the candidate should add for the target role.
- roadmap: exactly 4 weeks with 2-4 items per week, progressing from fundamentals to interview readiness.
- Do NOT include any URLs, links, a "resources" key or a "job_portals" key.
- Keep every string under 25 words. No markdown, no code fences — JSON only."""


def _stringify(value) -> str:
    return value.strip() if isinstance(value, str) else ("" if value is None else str(value).strip())


def _coerce_list(value, key: str) -> list:
    """Normalise an AI list field into a list of non-empty dicts."""
    items: list = []
    if not isinstance(value, list):
        return items
    for entry in value:
        if isinstance(entry, str) and entry.strip():
            items.append({key: entry.strip()})
        elif isinstance(entry, dict) and entry:
            cleaned = {}
            for item_key, item_value in entry.items():
                text = _stringify(item_value)
                if text:
                    cleaned[str(item_key).strip()] = text
            if cleaned:
                items.append(cleaned)
    return items


def _coerce_string_list(value, limit: int = 12) -> list:
    result: list = []
    if isinstance(value, list):
        for entry in value:
            text = _stringify(entry)
            if text:
                result.append(text)
    return result[:limit]


def _validate_and_shape(data: dict, fallback_role: str) -> dict:
    """Validate the AI JSON and force it into the documented response shape."""
    overview = _stringify(data.get("career_overview"))
    if not overview:
        raise AIResponseError()

    roadmap_raw = data.get("roadmap") if isinstance(data.get("roadmap"), dict) else {}
    roadmap = {week: _coerce_list(roadmap_raw.get(week), "topic")
               for week in ("week_1", "week_2", "week_3", "week_4")}
    if not any(roadmap.values()):
        raise AIResponseError()

    # Static, curated links are merged from data/resources.json — the AI is
    # never asked to invent URLs.
    return {
        "career_overview": overview,
        "target_role": _stringify(data.get("target_role")) or fallback_role,
        "skills_analysis": _coerce_list(data.get("skills_analysis"), "skill"),
        "skill_gaps": _coerce_list(data.get("skill_gaps"), "skill"),
        "roadmap": roadmap,
        "pro_tips": _coerce_string_list(data.get("pro_tips") or data.get("tips"), 6),
        "resources": get_learning_resources(),
        "job_portals": get_job_portals(),
    }


def generate_career_plan(form_data: dict) -> dict:
    """Build the prompt, call the AI, validate the JSON and merge static links."""
    name = form_data["full_name"]
    skills = form_data["skills"]
    role = form_data["target_role"]

    prompt = PROMPT_TEMPLATE.format(name=name, skills=skills, role=role)
    raw = call_ai(prompt, system=SYSTEM_INSTRUCTION)

    try:
        data = parse_ai_json(raw)
    except AIResponseError:
        logger.warning("Career guide AI output was not valid JSON")
        raise

    result = _validate_and_shape(data, role)
    logger.info("Career plan generated for role=%r", role)
    return result
