"""Database models for the AI Career Command Center.

Design rules:
- db.create_all() only ever CREATES missing tables; nothing is dropped, so
  existing local data always survives an upgrade.
- SQLite for zero-config local development; set DATABASE_URL to a PostgreSQL
  URL for production (SQLAlchemy makes this a config change only).
- Every user-owned row carries a user_id FK; the API layer always filters by
  the session user, so data isolation is enforced server-side.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite-friendly)."""
    return datetime.utcnow()


def dump_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def load_json(text, default=None):
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class User(db.Model, TimestampMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    profile = db.relationship("CareerProfile", back_populates="user",
                              uselist=False, cascade="all, delete-orphan")
    skills = db.relationship("UserSkill", back_populates="user",
                             cascade="all, delete-orphan")
    resumes = db.relationship("Resume", back_populates="user",
                              cascade="all, delete-orphan")
    analyses = db.relationship("ResumeAnalysis", back_populates="user",
                               cascade="all, delete-orphan")
    roadmaps = db.relationship("CareerRoadmap", back_populates="user",
                               cascade="all, delete-orphan")
    progress_entries = db.relationship("Progress", back_populates="user",
                                       cascade="all, delete-orphan")
    activities = db.relationship("Activity", back_populates="user",
                                 cascade="all, delete-orphan")
    notifications = db.relationship("Notification", back_populates="user",
                                    cascade="all, delete-orphan")
    coach_messages = db.relationship("CoachMessage", back_populates="user",
                                     cascade="all, delete-orphan")
    reset_tokens = db.relationship("PasswordResetToken", back_populates="user",
                                   cascade="all, delete-orphan")
    skill_history = db.relationship("SkillHistory", back_populates="user",
                                    cascade="all, delete-orphan")
    gap_guidance = db.relationship("GapGuidance", back_populates="user",
                                   cascade="all, delete-orphan")
    generated_resumes = db.relationship("GeneratedResume", back_populates="user",
                                        cascade="all, delete-orphan")

    def to_public(self) -> dict:
        return {"id": self.id, "full_name": self.full_name, "email": self.email,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class CareerProfile(db.Model, TimestampMixin):
    __tablename__ = "career_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False,
                        unique=True, index=True)
    education = db.Column(db.String(200), default="")
    college = db.Column(db.String(200), default="")
    degree = db.Column(db.String(120), default="")
    graduation_year = db.Column(db.String(10), default="")
    experience = db.Column(db.Text, default="")
    target_role = db.Column(db.String(120), default="")
    career_goal = db.Column(db.Text, default="")
    preferred_job_type = db.Column(db.String(60), default="")

    user = db.relationship("User", back_populates="profile")

    def to_dict(self) -> dict:
        return {"education": self.education or "", "college": self.college or "",
                "degree": self.degree or "", "graduation_year": self.graduation_year or "",
                "experience": self.experience or "", "target_role": self.target_role or "",
                "career_goal": self.career_goal or "",
                "preferred_job_type": self.preferred_job_type or ""}


class Skill(db.Model):
    """Global skill catalog — normalised skill names shared by all users."""

    __tablename__ = "skills"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    category = db.Column(db.String(60), default="Technical", nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class UserSkill(db.Model, TimestampMixin):
    __tablename__ = "user_skills"
    __table_args__ = (db.UniqueConstraint("user_id", "skill_id", name="uq_user_skill"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=False, index=True)
    # resume | manually_added | AI_suggested
    source = db.Column(db.String(20), default="manually_added", nullable=False)
    proficiency = db.Column(db.Integer, default=40, nullable=False)  # 0-100

    user = db.relationship("User", back_populates="skills")
    skill = db.relationship("Skill")

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.skill.name if self.skill else "",
                "category": self.skill.category if self.skill else "Technical",
                "source": self.source, "proficiency": self.proficiency,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}

class Resume(db.Model, TimestampMixin):
    __tablename__ = "resumes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    target_role = db.Column(db.String(120), default="")
    extracted_text = db.Column(db.Text, default="")
    file_data = db.Column(db.LargeBinary)  # original PDF bytes — private, per-user
    ats_score = db.Column(db.Integer)      # latest analysis score (denormalised)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)
    # skills detected from the resume text (JSON list), used by the Skills page
    detected_skills = db.Column(db.Text, default="")

    user = db.relationship("User", back_populates="resumes")
    analyses = db.relationship("ResumeAnalysis", back_populates="resume",
                               cascade="all, delete-orphan")

    def to_dict(self, include_detected: bool = False) -> dict:
        data = {"id": self.id, "filename": self.filename, "version": self.version,
                "target_role": self.target_role, "ats_score": self.ats_score,
                "is_primary": self.is_primary, "has_file": bool(self.file_data),
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}
        if include_detected:
            data["detected_skills"] = load_json(self.detected_skills, [])
        return data


class ResumeAnalysis(db.Model, TimestampMixin):
    __tablename__ = "resume_analyses"

    id = db.Column(db.Integer, primary_key=True)
    resume_id = db.Column(db.Integer, db.ForeignKey("resumes.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    target_role = db.Column(db.String(120), default="")
    ats_score = db.Column(db.Integer, nullable=False)
    keyword_score = db.Column(db.Float, default=0, nullable=False)
    skills_score = db.Column(db.Float, default=0, nullable=False)
    experience_score = db.Column(db.Float, default=0, nullable=False)
    education_score = db.Column(db.Float, default=0, nullable=False)
    formatting_score = db.Column(db.Float, default=0, nullable=False)
    sections_score = db.Column(db.Float, default=0, nullable=False)
    breakdown_json = db.Column(db.Text, default="")
    insights_json = db.Column(db.Text, default="")
    ai_enhanced = db.Column(db.Boolean, default=False, nullable=False)

    resume = db.relationship("Resume", back_populates="analyses")
    user = db.relationship("User", back_populates="analyses")

    @property
    def breakdown(self) -> list:
        """Parsed ATS factor breakdown (never stored as raw JSON in responses)."""
        return load_json(self.breakdown_json, []) or []

    @property
    def insights(self) -> dict:
        """Parsed AI/deterministic insight payload."""
        return load_json(self.insights_json, {}) or {}

    def to_dict(self, include_insights: bool = True) -> dict:
        data = {
            "id": self.id, "resume_id": self.resume_id, "target_role": self.target_role,
            "ats_score": self.ats_score,
            "keyword_score": self.keyword_score, "skills_score": self.skills_score,
            "experience_score": self.experience_score, "education_score": self.education_score,
            "formatting_score": self.formatting_score, "sections_score": self.sections_score,
            "breakdown": load_json(self.breakdown_json, []),
            "ai_enhanced": self.ai_enhanced,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_insights:
            data["insights"] = load_json(self.insights_json, {})
        return data


class CareerRoadmap(db.Model, TimestampMixin):
    __tablename__ = "career_roadmaps"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    target_role = db.Column(db.String(120), default="")
    # "ai" | "deterministic"
    source = db.Column(db.String(20), default="deterministic", nullable=False)
    roadmap_json = db.Column(db.Text, default="")
    progress_percent = db.Column(db.Integer, default=0, nullable=False)

    user = db.relationship("User", back_populates="roadmaps")


class Progress(db.Model, TimestampMixin):
    __tablename__ = "progress"
    __table_args__ = (db.UniqueConstraint("user_id", "skill", name="uq_progress_skill"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    skill = db.Column(db.String(120), nullable=False)
    progress = db.Column(db.Integer, default=0, nullable=False)
    completed_tasks = db.Column(db.Integer, default=0, nullable=False)

    user = db.relationship("User", back_populates="progress_entries")

    def to_dict(self) -> dict:
        return {"skill": self.skill, "progress": self.progress,
                "completed_tasks": self.completed_tasks,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}

class Activity(db.Model):
    __tablename__ = "activities"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    type = db.Column(db.String(40), default="info", nullable=False)
    message = db.Column(db.String(255), nullable=False)
    meta_json = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)

    user = db.relationship("User", back_populates="activities")

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "message": self.message,
                "meta": load_json(self.meta_json, {}),
                "created_at": self.created_at.isoformat() if self.created_at else None}


class Notification(db.Model, TimestampMixin):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    type = db.Column(db.String(20), default="info", nullable=False)  # info|success|warning
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)

    user = db.relationship("User", back_populates="notifications")

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "message": self.message,
                "is_read": self.is_read,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class CoachMessage(db.Model):
    __tablename__ = "coach_messages"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(12), nullable=False)  # user | assistant
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    user = db.relationship("User", back_populates="coach_messages")

    def to_dict(self) -> dict:
        return {"id": self.id, "role": self.role, "content": self.content,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class PasswordResetToken(db.Model):
    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)

    user = db.relationship("User", back_populates="reset_tokens")


class SkillHistory(db.Model):
    """Append-only log of skill changes — powers skill-growth tracking."""

    __tablename__ = "skill_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    skill_name = db.Column(db.String(120), nullable=False, index=True)
    from_value = db.Column(db.Integer, default=0, nullable=False)
    to_value = db.Column(db.Integer, default=0, nullable=False)
    # added | updated | removed
    change_type = db.Column(db.String(20), default="updated", nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)

    user = db.relationship("User", back_populates="skill_history")

    def to_dict(self) -> dict:
        return {"id": self.id, "skill": self.skill_name,
                "from_value": self.from_value, "to_value": self.to_value,
                "delta": (self.to_value or 0) - (self.from_value or 0),
                "change_type": self.change_type,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class GapGuidance(db.Model, TimestampMixin):
    """Cached AI guidance for one exact set of skill gaps.

    The cache key is a hash of (target role + sorted gap names), so repeat page
    visits never trigger another AI call — only genuinely new gap sets do.
    """

    __tablename__ = "gap_guidance"
    __table_args__ = (db.UniqueConstraint("user_id", "target_role", "signature",
                                          name="uq_gap_guidance"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    target_role = db.Column(db.String(120), default="", nullable=False)
    signature = db.Column(db.String(64), nullable=False, index=True)
    guidance_json = db.Column(db.Text, default="")

    user = db.relationship("User", back_populates="gap_guidance")


class GeneratedResume(db.Model, TimestampMixin):
    """A draft produced by the AI resume builder (never contains invented facts)."""

    __tablename__ = "generated_resumes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(120), default="", nullable=False)
    target_role = db.Column(db.String(120), default="", nullable=False)
    content_json = db.Column(db.Text, default="")

    user = db.relationship("User", back_populates="generated_resumes")

    def to_dict(self, include_content: bool = True) -> dict:
        data = {"id": self.id, "title": self.title, "target_role": self.target_role,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}
        if include_content:
            data["content"] = load_json(self.content_json, {})
        return data


# ---------------------------------------------------------------------------
# Initialisation: safe, additive, never drops anything.
# ---------------------------------------------------------------------------
_ADDED_COLUMNS = {
    # table: {column: "<DDL>"} — additive migrations for future versions.
    # Only ever ADDs columns; existing data is never modified or dropped.
    "resumes": {
        "is_primary": "BOOLEAN NOT NULL DEFAULT 0",
        "detected_skills": "TEXT DEFAULT ''",
    },
}


def init_db(app) -> None:
    """Bind SQLAlchemy, create missing tables, run safe migrations, seed data."""
    uri = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(BASE_DIR, "career_center.db").replace("\\", "/"))
    if uri.startswith("postgres://"):  # normalise legacy-style Postgres URLs
        uri = uri.replace("postgres://", "postgresql://", 1)
    app.config.setdefault("SQLALCHEMY_DATABASE_URI", uri)
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    db.init_app(app)

    with app.app_context():
        db.create_all()  # creates only missing tables — never drops data
        _ensure_sqlite_columns()
        _seed_skill_catalog()
        db.session.commit()


def _ensure_sqlite_columns() -> None:
    """Idempotent additive column migration (works on SQLite and PostgreSQL).

    Only ADDs missing columns — never alters or removes existing data, and the
    function name is kept for backward compatibility with previous versions.
    """
    driver = db.engine.url.drivername
    if driver.startswith("sqlite"):
        existing_columns = _sqlite_columns
    else:
        existing_columns = _inspector_columns
    for table, columns in _ADDED_COLUMNS.items():
        existing = existing_columns(table)
        if not existing:
            continue
        for column, ddl in columns.items():
            if column in existing:
                continue
            try:
                db.session.execute(db.text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                db.session.commit()
            except Exception:  # pragma: no cover - racing/concurrent create
                db.session.rollback()


def _sqlite_columns(table: str) -> set:
    try:
        rows = db.session.execute(db.text(f"PRAGMA table_info({table})")).fetchall()
    except Exception:
        return set()
    return {row[1] for row in rows}


def _inspector_columns(table: str) -> set:
    try:
        from sqlalchemy import inspect

        return {col["name"] for col in inspect(db.engine).get_columns(table)}
    except Exception:
        return set()


_SKILL_CATEGORIES = {
    "Languages": {"python", "java", "c++", "c#", "javascript", "typescript", "kotlin",
                  "golang", "ruby", "swift", "php", "bash", "r"},
    "Databases": {"sql", "mysql", "postgresql", "mongodb", "redis", "sqlite", "oracle",
                  "room database"},
    "Web & Frameworks": {"html", "css", "react", "angular", "vue", "node.js", "express",
                         "bootstrap", "jquery", "sass", "webpack", "rest api", "wordpress",
                         "django", "flask", "spring boot", "material design"},
    "Cloud & DevOps": {"aws", "azure", "gcp", "docker", "kubernetes", "jenkins", "terraform",
                       "ansible", "linux", "prometheus", "mlops", "ci/cd"},
    "Data & AI": {"pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "statistics",
                  "matplotlib", "seaborn", "jupyter", "machine learning", "deep learning",
                  "data visualization", "power bi", "tableau", "excel", "nlp",
                  "feature engineering", "exploratory data analysis"},
    "Tools": {"git", "github", "postman", "jira", "figma", "adobe xd", "android studio",
              "gradle", "firebase", "selenium", "pytest", "junit", "wireshark", "nmap",
              "burp suite", "siem"},
    "Soft Skills": {"communication", "teamwork", "problem solving", "time management",
                    "learning", "leadership", "stakeholder management", "documentation",
                    "user research", "usability testing"},
}
_KEEP_CASE = {"aws", "gcp", "api", "sql", "html", "css", "php", "sass", "nlp", "qa",
              "ui", "ux", "seo", "r"}


def _display_name(name: str) -> str:
    out = []
    for part in name.strip().lower().split():
        if part in _KEEP_CASE:
            out.append(part.upper())
        elif part in ("c++", "c#", "node.js", ".net", "ci/cd"):
            out.append(part.upper() if len(part) <= 3 else part.capitalize())
        else:
            out.append(part.capitalize())
    return " ".join(out)


def _guess_category(name: str) -> str:
    norm = name.strip().lower()
    for category, members in _SKILL_CATEGORIES.items():
        if norm in members:
            return category
    return "Technical"


def _seed_skill_catalog() -> int:
    """Populate the global skills catalog from data/role_keywords.json (idempotent)."""
    path = os.path.join(BASE_DIR, "data", "role_keywords.json")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    names: set = set()
    for profile in data.get("roles", {}).values():
        names.update(profile.get("skills", []))
    names.update(data.get("generic", {}).get("skills", []))

    created = 0
    existing = {s.name.lower() for s in Skill.query.all()}
    for name in sorted(names):
        norm = re.sub(r"\s+", " ", str(name).strip().lower())
        if not norm or norm in existing:
            continue
        db.session.add(Skill(name=_display_name(norm), category=_guess_category(norm)))
        existing.add(norm)
        created += 1
    return created



