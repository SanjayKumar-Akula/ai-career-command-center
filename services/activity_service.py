"""Activity timeline, in-app notifications and the career readiness score."""

from __future__ import annotations

from models import Activity, Notification, Resume, dump_json, db


def log_activity(user, activity_type: str, message: str, meta: dict | None = None) -> None:
    db.session.add(Activity(user_id=user.id, type=activity_type[:40],
                            message=message[:255],
                            meta_json=dump_json(meta or {})))


def notify(user, message: str, ntype: str = "info") -> None:
    db.session.add(Notification(user_id=user.id, type=ntype, message=message[:255]))


def push_notification(user, message: str, ntype: str = "info") -> None:
    """Committing variant used by API handlers after other writes are done."""
    db.session.add(Notification(user_id=user.id, type=ntype, message=message[:255]))
    db.session.commit()


def list_activities(user, limit: int = 15) -> list:
    rows = (Activity.query.filter_by(user_id=user.id)
            .order_by(Activity.created_at.desc()).limit(limit).all())
    return [row.to_dict() for row in rows]


def list_notifications(user, limit: int = 20) -> list:
    rows = (Notification.query.filter_by(user_id=user.id)
            .order_by(Notification.created_at.desc()).limit(limit).all())
    return [row.to_dict() for row in rows]


def unread_count(user) -> int:
    return Notification.query.filter_by(user_id=user.id, is_read=False).count()


def mark_notification_read(user, notification_id: int) -> bool:
    from models import Notification as N
    row = N.query.filter_by(id=notification_id, user_id=user.id).first()
    if not row:
        return False
    row.is_read = True
    db.session.commit()
    return True


def mark_all_read(user) -> int:
    count = Notification.query.filter_by(user_id=user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return count


def generate_score_improvement_notification(user, old_score: int, new_score: int) -> None:
    if new_score > old_score:
        notify(user, f"Your ATS score improved from {old_score} to {new_score}.", "success")


def generate_gap_notification(user, gap_count: int, role: str) -> None:
    if gap_count > 0:
        notify(user, f"You have {gap_count} important skill gaps for {role}.", "warning")


def career_readiness(user) -> dict:
    """Composite 0-100 readiness score (deterministic):
    40% latest ATS score, 40% average skill proficiency vs role requirements,
    20% roadmap progress."""
    from models import CareerRoadmap
    from services.gap_engine import compute_gap_analysis

    latest = (Resume.query.filter_by(user_id=user.id)
              .order_by(Resume.created_at.desc()).first())
    ats = latest.ats_score if latest and latest.ats_score is not None else 0
    ats_component = ats * 0.4

    gap = compute_gap_analysis(user)
    if gap["has_role"]:
        required = gap["required_count"] or 1
        covered = (len(gap["strong"]) + 0.5 * len(gap["developing"])) / required
        skill_component = min(covered, 1.0) * 100 * 0.4
        gaps_count = len(gap["missing"])
        role = gap["target_role"]
    else:
        skills = getattr(user, "skills", [])
        skill_component = (min(len(skills), 10) / 10) * 40
        gaps_count, role = 0, ""

    roadmap = (CareerRoadmap.query.filter_by(user_id=user.id)
               .order_by(CareerRoadmap.updated_at.desc()).first())
    roadmap_component = ((roadmap.progress_percent if roadmap else 0) / 100) * 20

    readiness = round(ats_component + skill_component + roadmap_component)
    return {
        "readiness": min(readiness, 100),
        "ats_score": ats,
        "components": {
            "ats": round(ats_component),
            "skills": round(skill_component),
            "roadmap": round(roadmap_component),
        },
        "skill_gaps": gaps_count,
        "target_role": role,
    }
