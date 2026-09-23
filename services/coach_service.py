"""AI Career Coach: a private, per-user assistant grounded in stored data.

The coach receives ONLY the signed-in user's own profile, skills, gap analysis
and roadmap progress. Conversation history is stored per user so no user can
ever see another user's chat. When the AI is unavailable, a deterministic
answer built from the user's data is returned instead — the page never breaks.
"""

from __future__ import annotations

import logging

from models import CareerRoadmap, CoachMessage, Resume, db
from services.ai_client import AIServiceError, call_ai
from services.gap_engine import compute_gap_analysis

logger = logging.getLogger("coach")

MAX_HISTORY = 12          # prior messages sent as context
MAX_QUESTION = 600        # characters

SYSTEM_INSTRUCTION = (
    "You are the AI Career Coach inside a career-intelligence app. You give "
    "short, concrete, encouraging advice (max 120 words) about resumes, ATS "
    "scores, skills, roadmaps and interviews. You never invent facts about "
    "the user beyond the context provided — if information is missing, ask "
    "the user to add it in their profile. You never include URLs or markdown "
    "headers — plain text with short paragraphs or simple bullet lists only."
)


def _context_block(user) -> str:
    """Build the private context packet from the user's own stored data."""
    from services.skill_service import list_skills

    profile = user.profile
    try:
        skills = [row["name"] for row in list_skills(user)]
    except Exception:  # pragma: no cover - skill list must not break the coach
        skills = []

    gap = compute_gap_analysis(user)
    latest = (Resume.query.filter_by(user_id=user.id)
              .order_by(Resume.created_at.desc()).first())
    ats = latest.ats_score if latest and latest.ats_score is not None else None

    lines = [f"Name: {user.full_name or 'unknown'}"]
    if profile:
        for label, value in (("Target role", profile.target_role),
                             ("Education", profile.education),
                             ("Degree", profile.degree),
                             ("Graduation year", profile.graduation_year),
                             ("Experience notes", profile.experience),
                             ("Career goal", profile.career_goal),
                             ("Preferred job type", profile.preferred_job_type)):
            if value:
                lines.append(f"{label}: {value}")
    lines.append(f"Skills ({len(skills)}): "
                 f"{', '.join(skills[:25]) or 'none saved yet'}")
    lines.append("Latest ATS score: "
                 f"{ats if ats is not None else 'no resume analyzed yet'}")
    if gap["has_role"]:
        lines.append("Strong for " + gap["target_role"] + ": "
                     + (", ".join(s["name"] for s in gap["strong"][:8]) or "none"))
        lines.append("Missing for " + gap["target_role"] + ": "
                     + (", ".join(g["name"] for g in gap["missing"][:8]) or "none"))
    row = (CareerRoadmap.query.filter_by(user_id=user.id)
           .order_by(CareerRoadmap.updated_at.desc()).first())
    if row:
        lines.append(f"Roadmap progress: {row.progress_percent}% for {row.target_role}")
    return "\n".join(lines)


def get_history(user, limit: int = 40) -> list:
    rows = (CoachMessage.query.filter_by(user_id=user.id)
            .order_by(CoachMessage.created_at.desc()).limit(limit).all())
    return [row.to_dict() for row in reversed(rows)]


def clear_history(user) -> int:
    count = CoachMessage.query.filter_by(user_id=user.id).delete()
    db.session.commit()
    return count


def ask(user, question: str) -> dict:
    """Persist the question, call the AI with private context, persist the reply.

    Never raises: if the AI is unavailable a deterministic answer built from
    the user's own data is returned with a notice.
    """
    text = (question or "").strip()[:MAX_QUESTION]
    if not text:
        return {"reply": "", "error": "Please type a question.",
                "history": get_history(user)}

    db.session.add(CoachMessage(user_id=user.id, role="user", content=text))
    db.session.commit()

    context = _context_block(user)
    recent = (CoachMessage.query.filter_by(user_id=user.id)
              .order_by(CoachMessage.id.desc()).limit(MAX_HISTORY).all())
    transcript = "\n".join(
        f"{'User' if row.role == 'user' else 'Coach'}: {row.content}"
        for row in reversed(recent))

    reply, notice, ai_ok = "", None, False
    prompt = (f"CAREER CONTEXT (private to this user):\n{context}\n\n"
              f"CONVERSATION:\n{transcript}\n\nReply to the user's latest message.")
    try:
        reply = (call_ai(prompt, system=SYSTEM_INSTRUCTION, temperature=0.6) or "").strip()
        ai_ok = bool(reply)
        if not reply:
            notice = "The AI returned an empty response."
    except AIServiceError as exc:
        notice = exc.message
    except Exception:  # pragma: no cover - the coach must never crash the page
        logger.warning("Coach AI call failed", exc_info=True)
        notice = "The AI service is temporarily unavailable."

    if not reply:
        reply = _fallback_answer(user, text)

    db.session.add(CoachMessage(user_id=user.id, role="assistant",
                                content=reply[:4000]))
    db.session.commit()
    return {"reply": reply[:4000], "ai_enhanced": ai_ok, "ai_notice": notice,
            "history": get_history(user)}


def _fallback_answer(user, question: str) -> str:
    """Deterministic reply drawn only from the user's stored data."""
    q = question.lower()
    profile = user.profile
    role = (profile.target_role if profile and profile.target_role
            else "your target role")
    gap = compute_gap_analysis(user)
    missing = [g["name"] for g in gap.get("missing", [])] if gap["has_role"] else []
    latest = (Resume.query.filter_by(user_id=user.id)
              .order_by(Resume.created_at.desc()).first())

    if any(word in q for word in ("ats", "score", "resume", "improve", "low")):
        if latest and latest.ats_score is not None:
            return (f"The AI service is temporarily unavailable, but your latest "
                    f"resume scores {latest.ats_score}/100 for "
                    f"{latest.target_role or role}. Open the Resume page for the full "
                    f"factor breakdown — keyword match, skills, formatting and "
                    f"sections are all shown there with concrete fixes.")
        return ("Your saved data and deterministic ATS analysis remain available. "
                "Upload a resume on the Resume page to get an instant "
                "breakdown-style score without the AI.")

    if any(word in q for word in ("learn", "next", "skill", "missing", "gap")):
        if missing:
            top = ", ".join(missing[:3])
            return (f"The AI service is temporarily unavailable, so here is your "
                    f"stored skill-gap data: for {role} you are missing {top}. "
                    f"Start with {missing[0]} — one focused week of fundamentals "
                    f"plus a small project is the fastest way to close it.")
        if gap["has_role"]:
            return (f"Your skills already cover the core of {role}. Push depth next: "
                    f"pick one advanced topic from the Roadmap page and build a "
                    f"project with it.")
        return ("Set a target role on the Profile page and I can compare your "
                "skills against it to show exactly what is missing.")

    if any(word in q for word in ("project", "build", "portfolio")):
        focus = missing[0] if missing else "your strongest skill"
        return (f"Build one small, complete project around {focus}: a real problem, "
                f"a README with setup steps, tests if possible, and code pushed to "
                f"GitHub. One project explained deeply beats five shallow tutorials.")

    if any(word in q for word in ("interview", "prepare", "placement")):
        return (f"For {role} interviews: revise core fundamentals of "
                f"{(missing[0] if missing else 'your main stack')}, rehearse "
                f"explaining one project end-to-end with decisions and trade-offs, "
                f"and practise 2-3 aptitude or coding questions daily. Curated "
                f"practice links are on the Jobs & Resources page.")

    if any(word in q for word in ("summary", "objective", "about")):
        return ("Keep your summary to 3 lines: the role you target, your strongest "
                "2-3 skills, and one concrete outcome you can prove. The Resume "
                "Builder writes one from your saved profile — it never invents "
                "experience you did not provide.")

    return (f"The AI service is temporarily unavailable, so I am working from your "
            f"saved data only. Your target role is {role}, you have "
            f"{len(user.skills)} saved skills, and your latest ATS score is "
            f"{latest.ats_score if latest and latest.ats_score is not None else 'not set'}. "
            f"Ask me about skills, ATS scores, projects or interview prep.")

