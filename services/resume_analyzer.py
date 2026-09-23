"""Resume Analyzer service.

The ATS score is computed DETERMINISTICALLY in Python (never invented by
the AI) using a fixed, explainable weighting:

    Keyword match          30
    Skills match           20
    Experience/projects    15
    Education              10
    ATS formatting         15
    Section completeness   10
    Total                 100

The AI is used only for qualitative insights (strengths, weaknesses,
missing skills, improvement areas, extra ATS checks, role match,
recommended keywords). All links shown in the UI come from
data/resources.json — the AI is never asked to invent URLs.
"""

from __future__ import annotations

import json
import logging
import os
import re

from services.ai_client import AIServiceError, AIResponseError, call_ai, parse_ai_json
from services.resources import get_job_portals, get_resume_builders

logger = logging.getLogger("resume_analyzer")

_KEYWORD_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "role_keywords.json",
)

RESUME_TEXT_LIMIT = 9000  # characters sent to the AI

_keyword_db: dict | None = None


class ResumeServiceError(Exception):
    """Raised for resume-analysis failures with a user-friendly message."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


def _load_keyword_db() -> dict:
    global _keyword_db
    if _keyword_db is None:
        with open(_KEYWORD_DB_PATH, "r", encoding="utf-8") as fh:
            _keyword_db = json.load(fh)
    return _keyword_db


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9+/ ]+", " ", (value or "").lower()).strip()


def _contains_term(haystack: str, term: str) -> bool:
    """Whole-term containment on a normalised haystack (not raw substring)."""
    pattern = r"(?<![a-z0-9])" + re.escape(term.strip()) + r"(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def match_role(role: str):
    """Match a free-text role to a keyword entry from role_keywords.json."""
    role_text = _norm(role)
    db = _load_keyword_db()
    roles: dict = db.get("roles", {})

    # Pass 1: exact match on key or alias.
    for name, entry in roles.items():
        if role_text == _norm(name):
            return entry, name
        for alias in entry.get("aliases", []):
            if role_text == _norm(alias):
                return entry, name

    # Pass 2: role text contains a known key (longest keys first).
    for name in sorted(roles, key=len, reverse=True):
        if _norm(name) and _norm(name) in role_text:
            return roles[name], name

    # Pass 3: role text contains a known multi-word alias.
    for name, entry in roles.items():
        for alias in entry.get("aliases", []):
            alias_norm = _norm(alias)
            if " " in alias_norm and alias_norm in role_text:
                return entry, name

    return db.get("generic", {}), role


# --- canonical resume sections --------------------------------------------
SECTION_PATTERNS = {
    "summary": (r"\b(summary|objective|profile|about me)\b",),
    "education": (r"\b(education|academic|qualifications?|academics)\b",),
    "skills": (r"\b(skills?|technical skills|technologies|tech stack)\b",),
    "experience": (r"\b(experience|work experience|employment|internships?)\b",),
    "projects": (r"\b(projects?|portfolio|academic projects)\b",),
    "certifications": (r"\b(certifications?|licenses|courses)\b",),
}
SECTION_WEIGHTS = {"summary": 1, "education": 2, "skills": 2,
                   "experience": 2, "projects": 2, "certifications": 1}


def detect_sections(text: str) -> set:
    found = set()
    for section, patterns in SECTION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                found.add(section)
                break
    return found


def detect_contact(text: str) -> dict:
    email = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    phone = re.search(r"(?:\+?\d[\d\s().-]{7,}\d)", text)
    linkedin = re.search(r"linkedin\.com|github\.com", text, re.IGNORECASE)
    return {"email": bool(email), "phone": bool(phone), "profile_links": bool(linkedin)}


_METRICS_RE = re.compile(r"\d+(?:\.\d+)?\s*%|\b\d+[kKmM]?\s*\+?\s*(users|students|records|downloads|requests|customers)\b")


def has_metrics(text: str) -> int:
    """Count occurrences of quantified achievements (%, users, etc.)."""
    return len(_METRICS_RE.findall(text))


def compute_ats_score(text: str, role: str) -> dict:
    """Deterministic, explainable ATS score out of 100.

    Every factor is scored against a fixed rubric so the same resume always
    produces the same score — the number is never invented by the AI.
    """
    role_entry, matched_role_name = match_role(role)
    haystack = _norm(text)
    words = haystack.split()
    word_count = len(words)
    details: dict = {}

    # --- 1. Target-role keyword match (30) --------------------------------
    keywords = role_entry.get("keywords", [])
    keyword_hits = [k for k in keywords if _contains_term(haystack, _norm(k))]
    keyword_missed = [k for k in keywords if k not in keyword_hits]
    keyword_ratio = (len(keyword_hits) / len(keywords)) if keywords else 0.0
    details["keyword_match"] = {
        "label": "Keyword Match",
        "max": 30,
        "score": round(30 * keyword_ratio, 1),
        "hits": keyword_hits,
        "missed": keyword_missed[:12],
        "note": f"Matched {len(keyword_hits)} of {len(keywords)} common target-role keywords.",
    }

    # --- 2. Required skills match (20) ------------------------------------
    skills = role_entry.get("skills", [])
    skill_hits = [s for s in skills if _contains_term(haystack, _norm(s))]
    skill_missed = [s for s in skills if s not in skill_hits]
    skill_ratio = (len(skill_hits) / len(skills)) if skills else 0.0
    details["skills_match"] = {
        "label": "Skills Match",
        "max": 20,
        "score": round(20 * skill_ratio, 1),
        "hits": skill_hits,
        "missed": skill_missed[:12],
        "note": f"{len(skill_hits)} of {len(skills)} commonly required skills found.",
    }

    # --- 3. Experience / project relevance (15) ----------------------------
    has_projects = "projects" in detect_sections(text)
    has_experience = "experience" in detect_sections(text)
    metrics = has_metrics(text)
    if has_experience and has_projects:
        exp_base = 11.0
    elif has_projects or has_experience:
        exp_base = 8.0
    else:
        exp_base = 4.0
    exp_base += min(metrics, 4) * 1.0  # +1 per quantified achievement, max +4
    details["experience_projects"] = {
        "label": "Experience / Projects",
        "max": 15,
        "score": round(min(exp_base, 15), 1),
        "note": (
            f"Experience section: {'yes' if has_experience else 'not found'}; "
            f"Projects section: {'yes' if has_projects else 'not found'}; "
            f"quantified achievements detected: {metrics}."
        ),
    }

    # --- 4. Education (10) --------------------------------------------------
    db = _load_keyword_db()
    edu_hits = [e for e in db.get("education_keywords", []) if _contains_term(haystack, _norm(e))]
    if "education" in detect_sections(text) and edu_hits:
        edu_score = 10.0
    elif edu_hits:
        edu_score = 7.0
    elif "education" in detect_sections(text):
        edu_score = 5.0
    else:
        edu_score = 0.0
    details["education"] = {
        "label": "Education",
        "max": 10,
        "score": edu_score,
        "note": (
            f"Education section: {'yes' if 'education' in detect_sections(text) else 'not found'}; "
            f"education details detected: {len(edu_hits)}."
        ),
    }

    # --- 5. ATS formatting (15) ---------------------------------------------
    # Text-based proxies only. A parsed PDF text stream cannot reliably show
    # tables/graphics, so we only report what we can honestly measure.
    bullets = len(re.findall(r"(?:^|\n)\s*(?:[-\u2022*]|\d+\.)\s", text))
    emails = detect_contact(text)
    fmt_score = 0.0
    fmt_checks = []
    if word_count >= 200:
        fmt_score += 5
        fmt_checks.append(("pass", "Sufficient content (200+ words)"))
    else:
        fmt_checks.append(("fail", f"Low content ({word_count} words) — aim for 250+"))
    if bullets >= 5:
        fmt_score += 4
        fmt_checks.append(("pass", f"{bullets} bullet points found"))
    else:
        fmt_checks.append(("fail", f"Few bullet points ({bullets}) — use 8+ concise bullets"))
    if emails["email"] and emails["phone"]:
        fmt_score += 3
        fmt_checks.append(("pass", "Email and phone contact details found"))
    else:
        fmt_checks.append(("fail", "Missing email or phone number"))
    if emails["profile_links"]:
        fmt_score += 2
        fmt_checks.append(("pass", "LinkedIn/GitHub profile link found"))
    else:
        fmt_checks.append(("fail", "No LinkedIn/GitHub link found"))
    # penalise likely ligature/encoding artefacts from odd PDF export
    artefacts = len(re.findall(r"[\ufb01\ufb02\ufffd]", text))
    if artefacts == 0:
        fmt_score += 1
        fmt_checks.append(("pass", "No text-encoding artefacts detected"))
    else:
        fmt_checks.append(("fail", f"{artefacts} encoding artefacts — re-export the PDF"))
    details["ats_formatting"] = {
        "label": "ATS Formatting",
        "max": 15,
        "score": round(fmt_score, 1),
        "checks": fmt_checks,
        "note": "Based on measurable text signals only; tables/graphics cannot be reliably detected from parsed PDF text.",
    }

    # --- 6. Section completeness (10) ----------------------------------------
    found_sections = detect_sections(text)
    section_score = sum(SECTION_WEIGHTS.get(s, 0) for s in found_sections)
    max_section = sum(SECTION_WEIGHTS.values())
    details["section_completeness"] = {
        "label": "Section Completeness",
        "max": 10,
        "score": round(10 * section_score / max_section, 1),
        "found": sorted(found_sections),
        "missing": sorted(set(SECTION_WEIGHTS) - found_sections),
        "note": f"Found sections: {', '.join(sorted(found_sections)) or 'none'}.",
    }

    total = round(sum(d["score"] for d in details.values()))
    return {"total": min(total, 100), "details": details}


SYSTEM_INSTRUCTION = (
    "You are an expert technical recruiter and ATS (Applicant Tracking System) "
    "specialist. You always reply with a single valid JSON object and nothing "
    "else. You base every statement strictly on the resume text provided and "
    "never invent experience."
)

PROMPT_TEMPLATE = """Analyze this resume for the target role "{role}".

An automated checker already scored the resume {score}/100. Its findings:
- Keywords matched: {matched}
- Keywords missing: {missed}
- Sections found: {sections_found}
- Sections missing: {sections_missing}
- Word count: {words}

Return ONLY a valid JSON object with EXACTLY this shape:
{{
  "target_role_match": "2-4 sentences on how well this resume fits the {role} role",
  "strengths": ["4-6 specific strengths evidenced in the resume"],
  "weaknesses": ["4-6 specific, actionable weaknesses"],
  "missing_skills": [{{"skill": "...", "why": "why it matters for this role"}}],
  "improvement_areas": [{{"area": "...", "suggestion": "specific actionable fix"}}],
  "ats_checks": [{{"label": "...", "status": "pass|fail|warn", "note": "one short sentence"}}],
  "recommended_keywords": ["5-10 role keywords or skills to add where relevant"]
}}

Rules:
- missing_skills: 4-8 skills commonly required for a {role} that are NOT in the resume.
- ats_checks: only checks verifiable from the TEXT itself (headings, keywords, contact info). Never claim to see tables/graphics — you cannot.
- improvement_areas: 4-6 items, concrete and specific (e.g. "Add measurable outcomes to project bullets").
- Do NOT include any URLs or links. Keep every string under 30 words. JSON only.

RESUME TEXT:
"""


def _build_prompt(resume_text: str, role: str, score_result: dict) -> str:
    details = score_result["details"]
    header = PROMPT_TEMPLATE.format(
        role=role,
        score=score_result["total"],
        matched=", ".join(details["keyword_match"]["hits"][:12]) or "none",
        missed=", ".join(details["keyword_match"]["missed"][:12]) or "none",
        sections_found=", ".join(details["section_completeness"]["found"]) or "none",
        sections_missing=", ".join(details["section_completeness"]["missing"]) or "none",
        words=len(_norm(resume_text).split()),
    )
    return header + resume_text[:RESUME_TEXT_LIMIT]


def _stringify(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def _coerce_string_list(value, limit: int = 12) -> list:
    result: list = []
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, str) and entry.strip():
                result.append(entry.strip())
            elif isinstance(entry, dict):
                for key in ("skill", "label", "name", "point", "keyword", "text"):
                    if _stringify(entry.get(key)):
                        result.append(_stringify(entry[key]))
                        break
    return result[:limit]


def _coerce_dict_list(value, text_key: str, alt_keys=("name",), limit: int = 10) -> list:
    """Normalise a list of dicts/strings into [{text_key: ..., extra...}]."""
    items: list = []
    if not isinstance(value, list):
        return items
    for entry in value:
        if isinstance(entry, str) and entry.strip():
            items.append({text_key: entry.strip()})
        elif isinstance(entry, dict) and entry:
            cleaned = {str(k).strip(): _stringify(v)
                       for k, v in entry.items() if _stringify(v)}
            if cleaned and text_key not in cleaned:
                for alt in alt_keys:
                    if alt in cleaned:
                        cleaned[text_key] = cleaned.pop(alt)
                        break
            if cleaned and text_key in cleaned:
                items.append(cleaned)
    return items[:limit]


def _coerce_checks(value, limit: int = 6) -> list:
    items: list = []
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict):
                label = _stringify(entry.get("label") or entry.get("name") or entry.get("check"))
                if not label:
                    continue
                status = _stringify(entry.get("status")).lower()
                if status not in ("pass", "fail", "warn"):
                    status = "warn"
                items.append({"label": label, "status": status,
                              "note": _stringify(entry.get("note") or entry.get("detail"))})
            elif isinstance(entry, str) and entry.strip():
                items.append({"label": entry.strip(), "status": "warn", "note": ""})
    return items[:limit]


def _get_ai_insights(resume_text: str, role: str, score_result: dict) -> dict:
    prompt = _build_prompt(resume_text, role, score_result)
    raw = call_ai(prompt, system=SYSTEM_INSTRUCTION)
    try:
        data = parse_ai_json(raw)
    except AIResponseError:
        logger.warning("Resume analyzer AI output was not valid JSON")
        raise

    missing_skills = _coerce_dict_list(data.get("missing_skills"), "skill", ("name",), 10)
    if not missing_skills:
        # Sensible fallback: use the deterministic skill-gap list.
        missing_skills = [{"skill": s, "why": "Commonly required for this role and not found in your resume."}
                          for s in score_result["details"]["skills_match"]["missed"][:6]]

    return {
        "target_role_match": _stringify(data.get("target_role_match")),
        "strengths": _coerce_string_list(data.get("strengths"), 8),
        "weaknesses": _coerce_string_list(data.get("weaknesses"), 8),
        "missing_skills": missing_skills,
        "improvement_areas": _coerce_dict_list(data.get("improvement_areas"), "area", ("title",), 10),
        "ats_checks": _coerce_checks(data.get("ats_checks")),
        "recommended_keywords": _coerce_string_list(data.get("recommended_keywords"), 12),
    }


_FMT_CHECK_LABELS = ("Enough content", "Bullet points", "Contact details",
                     "Profile links", "Clean text encoding")


def _fallback_insights(role: str, details: dict) -> dict:
    """Deterministic insights used when the AI is unavailable."""
    kw_hits = details["keyword_match"]["hits"]
    kw_missed = details["keyword_match"]["missed"]
    sk_missed = details["skills_match"]["missed"]

    strengths = []
    if kw_hits:
        strengths.append("Already mentions target-role keywords: " + ", ".join(kw_hits[:5]) + ".")
    if details["section_completeness"]["found"]:
        strengths.append("Standard sections present: "
                         + ", ".join(details["section_completeness"]["found"]) + ".")
    strengths.append("Text extracts cleanly, so ATS software can read this resume.")

    weaknesses = []
    if kw_missed:
        weaknesses.append("Target-role keywords missing: " + ", ".join(kw_missed[:6]) + ".")
    if sk_missed:
        weaknesses.append("Commonly required skills not evident: " + ", ".join(sk_missed[:6]) + ".")
    if not details["section_completeness"]["found"]:
        weaknesses.append("No standard section headings detected.")

    improvement = [{"area": d["label"], "suggestion": d["note"]}
                   for d in details.values() if d["score"] < d["max"] * 0.7]
    improvement = improvement or [{"area": "General polish",
                                   "suggestion": "Add measurable achievements to your bullet points."}]

    coverage = int(round(details["keyword_match"]["score"] / 30 * 100))
    return {
        "target_role_match": (
            f"The automated check matched about {coverage}% of common keywords for {role}. "
            "Adding the missing keywords, projects and standard sections will raise your score."
        ),
        "strengths": strengths[:6],
        "weaknesses": weaknesses[:6] or ["No critical issues detected by the automated check."],
        "missing_skills": [{"skill": s, "why": "Commonly required for this role."} for s in sk_missed[:6]],
        "improvement_areas": improvement[:6],
        "ats_checks": [],
        "recommended_keywords": (kw_missed + sk_missed)[:10],
    }


def analyze_resume(resume_text: str, target_role: str) -> dict:
    """Full analysis: deterministic score + AI insights + curated static links.

    If the AI call fails, the deterministic analysis is still returned with a
    friendly notice — the feature degrades gracefully instead of erroring out.
    """
    _, matched_role = match_role(target_role)
    score_result = compute_ats_score(resume_text, target_role)
    details = score_result["details"]

    ai_notice = None
    try:
        ai = _get_ai_insights(resume_text, matched_role, score_result)
    except AIServiceError as exc:
        ai_notice = exc.message
        logger.warning("Resume AI insights unavailable: %s", exc.message)
        ai = None
    except Exception:
        logger.exception("Unexpected error during AI insights")
        ai_notice = "AI insights could not be generated right now — showing the automated ATS analysis only."
        ai = None

    insights = ai if ai is not None else _fallback_insights(matched_role, details)

    # Deterministic checks first, then AI checks (de-duplicated by label).
    fmt_checks = details["ats_formatting"]["checks"]
    checks = [{"label": "Readable text extracted", "status": "pass",
               "note": f"{len(resume_text)} characters of text parsed from the PDF."}]
    checks += [{"label": _FMT_CHECK_LABELS[i], "status": fmt_checks[i][0], "note": fmt_checks[i][1]}
               for i in range(min(len(_FMT_CHECK_LABELS), len(fmt_checks)))]
    seen = {c["label"].lower() for c in checks}
    for check in insights["ats_checks"]:
        if check["label"].lower() not in seen:
            checks.append(check)

    checks.append({
        "label": "Tables / graphics / columns",
        "status": "warn",
        "note": "Cannot be reliably detected from extracted PDF text — visually confirm your "
                "layout uses no tables, text boxes or images for critical content.",
    })

    return {
        "ats_score": score_result["total"],
        "score_breakdown": [
            {key: d[key] for key in ("label", "score", "max", "note")}
            for d in details.values()
        ],
        "matched_keywords": details["keyword_match"]["hits"],
        "missing_keywords": details["keyword_match"]["missed"],
        "strengths": insights["strengths"],
        "weaknesses": insights["weaknesses"],
        "missing_skills": insights["missing_skills"],
        "improvement_areas": insights["improvement_areas"],
        "ats_checks": checks,
        "target_role_match": insights["target_role_match"],
        "recommended_keywords": insights["recommended_keywords"],
        "target_role": matched_role,
        "word_count": len(_norm(resume_text).split()),
        "job_portals": get_job_portals(),
        "resume_builder_links": get_resume_builders(),
        "ai_enhanced": ai is not None,
        "ai_notice": ai_notice,
    }



