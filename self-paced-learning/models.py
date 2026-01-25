"""Database models for authentication, classes, and lesson progress tracking."""

from datetime import datetime
from sqlalchemy import Enum

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
