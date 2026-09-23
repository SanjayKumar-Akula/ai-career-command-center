"""Skill-gap engine: compares user skills against target-role requirements.

The comparison is fully deterministic (uses the same role database as the
ATS scorer). AI enrichment (why / resource / project / practice) is optional
and always references trusted resource names from data/resources.json —
URLs are attached server-side, never invented by the AI.
"""

from __future__ import annotations

import logging

from services.ai_client import AIServiceError, call_ai, parse_ai_json
from services.resources import get_learning_resources
from services.resume_analyzer import match_role
from services.skill_service import user_skill_map

logger = logging.getLogger("gap_engine")

STRONG_THRESHOLD = 65  # proficiency % considered "strong"


def compute_gap_analysis(user, target_role: str | None = None) -> dict:
    """Deterministic gap analysis for the user's current target role."""
    role = (target_role or "").strip()
    if not role:
        profile = getattr(user, "profile", None)
        role = profile.target_role if profile else ""
    if not role:
        return {"target_role": "", "matched_role": "", "has_role": False,
                "strong": [], "developing": [], "missing": [], "coverage": 0}

    entry, matched_role = match_role(role)
    required = entry.get("skills", [])
    owned = user_skill_map(user)

    strong, developing = [], []
    required_lower = {s.lower() for s in required}
    for name, proficiency in owned.items():
        if name in required_lower:
            bucket = strong if proficiency >= STRONG_THRESHOLD else developing
            bucket.append({"name": name.title() if len(name) > 4 else name.upper(),
                           "proficiency": proficiency})

    missing = [{"name": s, "category": "required"} for s in required
               if s.lower() not in owned]
    strong.sort(key=lambda x: -x["proficiency"])
    developing.sort(key=lambda x: -x["proficiency"])
    coverage = round(100 * (len(strong) + len(developing)) / len(required)) if required else 0

    return {
        "target_role": role,
        "matched_role": matched_role,
        "has_role": True,
        "strong": strong,
        "developing": developing,
        "missing": missing,
        "coverage": coverage,
        "required_count": len(required),
    }


_GAP_PROMPT = """For a candidate targeting "{role}", explain how to close these skill gaps.

Already-known skills: {known}
Missing skills: {missing}
Developing skills (low proficiency): {developing}

Return ONLY valid JSON:
{{
  "gaps": [{{"skill": "...", "why": "why it matters for this role", "resource": "one resource name from the trusted list", "project": "a small hands-on project idea", "practice": "a daily/weekly practice habit"}}]
}}

Rules:
- One entry per missing skill, then developing skills (max 8 total).
- "resource" MUST be copied verbatim from this trusted list: {resources}
- Never invent websites or URLs. Keep every string under 25 words. JSON only.
"""


def enrich_gaps_with_ai(analysis: dict) -> dict:
    """Attach why/resource/project/practice guidance to gaps (best effort).

    Resource URLs are resolved locally from data/resources.json; if the AI
    names something unknown, the field is simply omitted.
    """
    if not analysis["has_role"] or not (analysis["missing"] or analysis["developing"]):
        return analysis

    trusted = get_learning_resources()
    trusted_names = [r["name"] for r in trusted]
    missing_names = [g["name"] for g in analysis["missing"]][:6]
    developing_names = [g["name"] for g in analysis["developing"]][:4]
    known = ", ".join(g["name"] for g in analysis["strong"][:10]) or "none listed"

    prompt = _GAP_PROMPT.format(
        role=analysis["matched_role"], known=known,
        missing=", ".join(missing_names) or "none",
        developing=", ".join(developing_names) or "none",
        resources="; ".join(trusted_names))
    try:
        raw = call_ai(prompt, system="You always reply with a single valid JSON object.",
                      temperature=0.3)
        data = parse_ai_json(raw)
    except AIServiceError as exc:
        logger.info("Gap enrichment unavailable: %s", exc.message)
        analysis["ai_notice"] = exc.message
        return analysis
    except Exception:
        logger.warning("Gap enrichment failed unexpectedly", exc_info=True)
        analysis["ai_notice"] = "AI guidance is temporarily unavailable."
        return analysis

    by_lower = {r["name"].lower(): r for r in trusted}
    details: dict = {}
    for gap in (data.get("gaps") or []):
        if not isinstance(gap, dict):
            continue
        name = str(gap.get("skill") or "").strip()
        if not name:
            continue
        resource = str(gap.get("resource") or "").strip()
        link = by_lower.get(resource.lower())
        details[name.lower()] = {
            "why": str(gap.get("why") or "")[:200],
            "resource": {"name": resource, "url": link["url"]} if link else None,
            "project": str(gap.get("project") or "")[:200],
            "practice": str(gap.get("practice") or "")[:200],
        }

    for bucket in ("missing", "developing"):
        for item in analysis[bucket]:
            extra = details.get(item["name"].lower())
            if extra:
                item["guidance"] = extra
    analysis["ai_enhanced"] = bool(details)
    return analysis


def _signature(role: str, names) -> str:
    import hashlib

    payload = "|".join([role.lower().strip()] + sorted(str(n).lower() for n in names))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:48]


def _attach_cached(analysis: dict, guidance: dict) -> dict:
    for bucket in ("missing", "developing"):
        for item in analysis[bucket]:
            entry = guidance.get(item["name"].lower())
            if entry:
                item["guidance"] = entry
    analysis["ai_enhanced"] = bool(guidance)
    analysis["cached"] = True
    return analysis


def gap_analysis_cached(user, target_role: str | None = None) -> dict:
    """Public entry point used by the API: compute gaps, then enrich them with
    AI guidance AT MOST ONCE per (role, gap-set) — repeat visits are instant and
    cost no API calls (performance requirement)."""
    from models import GapGuidance, dump_json, db, load_json

    analysis = compute_gap_analysis(user, target_role)
    if not analysis["has_role"]:
        return analysis
    gap_names = [g["name"] for g in analysis["missing"]] + \
                [g["name"] for g in analysis["developing"]]
    if not gap_names:
        analysis["ai_enhanced"] = False
        return analysis

    signature = _signature(analysis["matched_role"] or analysis["target_role"], gap_names)
    row = GapGuidance.query.filter_by(user_id=user.id,
                                      target_role=analysis["target_role"],
                                      signature=signature).first()
    if row:
        return _attach_cached(analysis, load_json(row.guidance_json, {}) or {})

    analysis = enrich_gaps_with_ai(analysis)
    guidance = {}
    for bucket in ("missing", "developing"):
        for item in analysis[bucket]:
            if item.get("guidance"):
                guidance[item["name"].lower()] = item["guidance"]

    notice = analysis.pop("ai_notice", None)
    if guidance:
        try:
            db.session.add(GapGuidance(user_id=user.id,
                                       target_role=analysis["target_role"],
                                       signature=signature,
                                       guidance_json=dump_json(guidance)))
            db.session.commit()
        except Exception:  # pragma: no cover - caching is best effort
            logger.warning("Could not cache gap guidance", exc_info=True)
            db.session.rollback()
    elif notice:
        analysis["ai_notice"] = notice
    return analysis
