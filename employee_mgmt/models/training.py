"""SQLAlchemy ORM models for the Training & Quizzes domain.

Defines tenant-isolated `TrainingPlan`, `TrainingQuestion`,
`TrainingAssignment`, and `QuizAttempt` tables with database-level integrity
constraints for deterministic server-side grading and completion tracking.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, TenantMixin, TimestampMixin, utc_now

ASSIGNMENT_STATUSES: tuple[str, ...] = ("assigned", "in_progress", "completed")


def _new_plan_id() -> str:
    """Generate a prefixed unique identifier for a training plan."""
    return f"trn_{uuid4().hex[:12]}"


def _new_question_id() -> str:
    """Generate a prefixed unique identifier for a training quiz question."""
    return f"trq_{uuid4().hex[:12]}"


def _new_assignment_id() -> str:
    """Generate a prefixed unique identifier for a training assignment."""
    return f"asg_{uuid4().hex[:12]}"


def _new_attempt_id() -> str:
    """Generate a prefixed unique identifier for a graded quiz attempt."""
    return f"att_{uuid4().hex[:12]}"


class TrainingPlan(Base, TenantMixin, TimestampMixin):
    """Tenant-scoped training plan and quiz definition."""

    __tablename__ = "training_plans"
    __table_args__ = (
        CheckConstraint(
            "passing_score_percent >= 1 AND passing_score_percent <= 100",
            name="valid_passing_score_percent",
        ),
        Index("ix_training_plans_tenant_active", "tenant_id", "is_active"),
        Index("ix_training_plans_tenant_category", "tenant_id", "category"),
    )

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=_new_plan_id,
    )
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="compliance",
        index=True,
    )
    passing_score_percent: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=80,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relationships
    questions: Mapped[list[TrainingQuestion]] = relationship(
        "TrainingQuestion",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="TrainingQuestion.question_order",
        passive_deletes=True,
    )
    assignments: Mapped[list[TrainingAssignment]] = relationship(
        "TrainingAssignment",
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    attempts: Mapped[list[QuizAttempt]] = relationship(
        "QuizAttempt",
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<TrainingPlan id={self.id!r} tenant_id={self.tenant_id!r} "
            f"title={self.title!r} is_active={self.is_active!r}>"
        )


class TrainingQuestion(Base, TenantMixin, TimestampMixin):
    """Multiple-choice quiz question with server-side answer key."""

    __tablename__ = "training_questions"
    __table_args__ = (
        CheckConstraint("question_order >= 0", name="non_negative_question_order"),
        CheckConstraint(
            "correct_option_index >= 0",
            name="non_negative_correct_option_index",
        ),
        UniqueConstraint(
            "plan_id",
            "question_key",
            name="uq_training_questions_plan_key",
        ),
        UniqueConstraint(
            "plan_id",
            "question_order",
            name="uq_training_questions_plan_order",
        ),
        Index("ix_training_questions_tenant_plan", "tenant_id", "plan_id"),
    )

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=_new_question_id,
    )
    plan_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("training_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_key: Mapped[str] = mapped_column(String(50), nullable=False)
    question_order: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(String(500), nullable=False)
    options: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    # Stored strictly server-side; never serialized to learner-facing responses.
    correct_option_index: Mapped[int] = mapped_column(Integer, nullable=False)

    plan: Mapped[TrainingPlan] = relationship(
        "TrainingPlan",
        back_populates="questions",
    )

    def __repr__(self) -> str:
        return (
            f"<TrainingQuestion id={self.id!r} plan_id={self.plan_id!r} "
            f"question_key={self.question_key!r}>"
        )


class TrainingAssignment(Base, TenantMixin, TimestampMixin):
    """Tracks employee assignment, attempts count, best score, and completion."""

    __tablename__ = "training_assignments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('assigned', 'in_progress', 'completed')",
            name="valid_assignment_status",
        ),
        CheckConstraint("attempts_count >= 0", name="non_negative_attempts_count"),
        CheckConstraint(
            "best_score_percent IS NULL OR "
            "(best_score_percent >= 0.0 AND best_score_percent <= 100.0)",
            name="valid_best_score_percent",
        ),
        CheckConstraint(
            "status != 'completed' OR (passed AND completed_at IS NOT NULL)",
            name="completed_requires_pass_and_timestamp",
        ),
        UniqueConstraint(
            "tenant_id",
            "plan_id",
            "employee_id",
            name="uq_training_assignments_tenant_plan_employee",
        ),
        Index(
            "ix_training_assignments_tenant_employee_status",
            "tenant_id",
            "employee_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=_new_assignment_id,
    )
    plan_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("training_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    assigned_by: Mapped[str] = mapped_column(String(100), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="assigned",
        index=True,
    )
    attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    best_score_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    plan: Mapped[TrainingPlan] = relationship(
        "TrainingPlan",
        back_populates="assignments",
    )

    def __repr__(self) -> str:
        return (
            f"<TrainingAssignment id={self.id!r} plan_id={self.plan_id!r} "
            f"employee_id={self.employee_id!r} status={self.status!r}>"
        )


class QuizAttempt(Base, TenantMixin, TimestampMixin):
    """Immutable record of a deterministically graded employee quiz attempt."""

    __tablename__ = "quiz_attempts"
    __table_args__ = (
        CheckConstraint("correct_answers >= 0", name="non_negative_correct_answers"),
        CheckConstraint("total_questions >= 1", name="positive_total_questions"),
        CheckConstraint(
            "correct_answers <= total_questions",
            name="correct_not_exceeds_total",
        ),
        CheckConstraint(
            "score_percent >= 0.0 AND score_percent <= 100.0",
            name="valid_score_percent",
        ),
        CheckConstraint(
            "passing_score_percent >= 1 AND passing_score_percent <= 100",
            name="valid_passing_score_percent",
        ),
        Index(
            "ix_quiz_attempts_tenant_employee_plan",
            "tenant_id",
            "employee_id",
            "plan_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=_new_attempt_id,
    )
    plan_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("training_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    correct_answers: Mapped[int] = mapped_column(Integer, nullable=False)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False)
    score_percent: Mapped[float] = mapped_column(Float, nullable=False)
    passing_score_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )

    plan: Mapped[TrainingPlan] = relationship(
        "TrainingPlan",
        back_populates="attempts",
    )

    def __repr__(self) -> str:
        return (
            f"<QuizAttempt id={self.id!r} plan_id={self.plan_id!r} "
            f"employee_id={self.employee_id!r} score_percent={self.score_percent}>"
        )


__all__ = [
    "ASSIGNMENT_STATUSES",
    "TrainingPlan",
    "TrainingQuestion",
    "TrainingAssignment",
    "QuizAttempt",
]