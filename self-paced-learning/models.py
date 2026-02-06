"""Database models for authentication, classes, and lesson progress tracking."""

from datetime import datetime
import uuid

from sqlalchemy import Enum
from sqlalchemy.types import JSON

from extensions import db


class User(db.Model):
    """Application user with student/teacher roles."""

    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    email = db.Column(db.String(100), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(Enum("student", "teacher", name="user_roles"), nullable=False)
    code = db.Column(db.String(10), nullable=True, unique=True)
    token_balance = db.Column(db.Integer, nullable=False, default=10)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    classes = db.relationship("Class", back_populates="teacher", lazy=True)
    registrations = db.relationship(
        "ClassRegistration", back_populates="student", lazy=True
    )
    lesson_progress = db.relationship(
        "LessonProgress",
        back_populates="student",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"


class Class(db.Model):
    """Teacher managed class grouping students."""

    __tablename__ = "class"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(10), nullable=False, unique=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    teacher = db.relationship("User", back_populates="classes")
    registrations = db.relationship(
        "ClassRegistration",
        back_populates="class_",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Class {self.name} ({self.code})>"


class ClassRegistration(db.Model):
    """Link between students and classes."""

    __tablename__ = "class_registration"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("class.id"), nullable=False)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship("User", back_populates="registrations")
    class_ = db.relationship("Class", back_populates="registrations")

    __table_args__ = (
        db.UniqueConstraint("student_id", "class_id", name="_student_class_uc"),
    )

    def __repr__(self) -> str:
        return f"<Registration Student:{self.student_id} Class:{self.class_id}>"


class LessonProgress(db.Model):
    """Persistent record of lesson and video completion."""

    __tablename__ = "lesson_progress"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    subject = db.Column(db.String(100), nullable=False)
    subtopic = db.Column(db.String(100), nullable=False)
    item_id = db.Column(db.String(255), nullable=False)
    item_type = db.Column(
        Enum("lesson", "video", name="progress_item_types"), nullable=False
    )
    completed = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    student = db.relationship("User", back_populates="lesson_progress")

    __table_args__ = (
        db.UniqueConstraint(
            "student_id",
            "subject",
            "subtopic",
            "item_id",
            "item_type",
            name="uq_student_progress",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<LessonProgress Student:{self.student_id} "
            f"{self.subject}/{self.subtopic}/{self.item_id} ({self.item_type})>"
        )


class AnonUser(db.Model):
    """Stable pseudonymous user identity (no PII)."""

    __tablename__ = "users_anon"

    anon_user_id = db.Column(db.String(64), primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    attempts = db.relationship(
        "Attempt",
        back_populates="anon_user",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<AnonUser {self.anon_user_id}>"


class Attempt(db.Model):
    """One row per module attempt/run, independent of login/logout."""

    __tablename__ = "attempts"

    attempt_id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    anon_user_id = db.Column(
        db.String(64), db.ForeignKey("users_anon.anon_user_id"), nullable=False
    )
    course_id = db.Column(db.String(100), nullable=False)
    module_id = db.Column(db.String(100), nullable=False)
    threshold_percent = db.Column(db.SmallInteger, nullable=False)
    max_cycles_allowed = db.Column(db.SmallInteger, nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)
    end_reason = db.Column(
        db.String(20),
        nullable=True,
        default=None,
    )
    # If you add new end reasons for a session-end route, update both the
    # check constraint below and any related migrations.
    last_activity_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    anon_user = db.relationship("AnonUser", back_populates="attempts")
    cycles = db.relationship(
        "Cycle", back_populates="attempt", lazy=True, cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.CheckConstraint(
            "end_reason IN ('passed','max_cycles','abandoned','system_error')",
            name="ck_attempts_end_reason",
        ),
        db.Index("idx_attempts_anon_user_id", "anon_user_id"),
        db.Index("idx_attempts_module_id", "module_id"),
        db.Index("idx_attempts_last_activity_at", "last_activity_at"),
    )

    def __repr__(self) -> str:
        return f"<Attempt {self.attempt_id} {self.module_id}>"


class Cycle(db.Model):
    """One row per cycle within an attempt (0=diagnostic, 1..n=remedial)."""

    __tablename__ = "cycles"

    cycle_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    attempt_id = db.Column(
        db.String(36), db.ForeignKey("attempts.attempt_id"), nullable=False
    )
    cycle_index = db.Column(db.SmallInteger, nullable=False)
    quiz_id = db.Column(db.String(100), nullable=False)
    quiz_type = db.Column(db.String(20), nullable=False)
    quiz_submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    score_percent = db.Column(db.Numeric(5, 2), nullable=False)
    passed_threshold = db.Column(db.Boolean, nullable=False)
    diagnosis_at = db.Column(db.DateTime, nullable=True)
    diagnosis_model_name = db.Column(db.String(100), nullable=True)
    diagnosed_concept_ids = db.Column(JSON, nullable=True)
    intervention_issued_at = db.Column(db.DateTime, nullable=True)
    lesson_concept_ids = db.Column(JSON, nullable=True)
    micro_lesson_count = db.Column(db.SmallInteger, nullable=True)

    attempt = db.relationship("Attempt", back_populates="cycles")

    __table_args__ = (
        db.CheckConstraint(
            "quiz_type IN ('diagnostic','remedial')",
            name="ck_cycles_quiz_type",
        ),
        db.UniqueConstraint("attempt_id", "cycle_index", name="uq_cycle_attempt_index"),
        db.Index("idx_cycles_attempt_id", "attempt_id"),
        db.Index("idx_cycles_quiz_type", "quiz_type"),
        db.Index("idx_cycles_submitted_at", "quiz_submitted_at"),
    )

    def __repr__(self) -> str:
        return f"<Cycle {self.attempt_id}:{self.cycle_index}>"
