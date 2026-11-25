"""SQLAlchemy ORM models for the Face ID & Attendance domain.

Defines tenant-isolated `AttendanceRecord` entries and an immutable
`AttendanceEditAudit` trail with database-level lock integrity and fail-closed
guardrails for high-risk `attendance.post_lock_edit` actions.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, TenantMixin, TimestampMixin, utc_now

ATTENDANCE_STATUSES: tuple[str, ...] = ("checked_in", "checked_out")


def _new_edit_audit_id() -> str:
    """Generate a prefixed unique identifier for a post-lock edit audit record."""
    return f"aea_{uuid4().hex[:12]}"


class AttendanceRecord(Base, TenantMixin, TimestampMixin):
    """Tenant-scoped employee check-in/check-out attendance record."""

    __tablename__ = "attendance_records"
    __table_args__ = (
        CheckConstraint(
            "status IN ('checked_in', 'checked_out')",
            name="valid_status",
        ),
        CheckConstraint(
            "check_out IS NULL OR check_out >= check_in",
            name="valid_shift_window",
        ),
        CheckConstraint(
            "(status = 'checked_in' AND check_out IS NULL) OR "
            "(status = 'checked_out' AND check_out IS NOT NULL)",
            name="status_matches_checkout",
        ),
        CheckConstraint(
            "(NOT is_locked) OR (locked_at IS NOT NULL AND locked_by IS NOT NULL)",
            name="lock_requires_actor_and_timestamp",
        ),
        # Database-level fail-closed guardrail for high-risk `attendance.post_lock_edit`.
        CheckConstraint(
            "last_edited_by IS NULL OR ("
            "is_locked "
            "AND last_edited_at IS NOT NULL "
            "AND approval_id IS NOT NULL "
            "AND approved_by IS NOT NULL "
            "AND edit_reason IS NOT NULL "
            "AND approved_by != last_edited_by "
            "AND last_edited_by != employee_id"
            ")",
            name="post_lock_edit_requires_non_self_approval",
        ),
        Index(
            "ix_attendance_tenant_employee_checkin",
            "tenant_id",
            "employee_id",
            "check_in",
        ),
        Index(
            "ix_attendance_tenant_employee_status",
            "tenant_id",
            "employee_id",
            "status",
        ),
        Index(
            "ix_attendance_tenant_locked",
            "tenant_id",
            "is_locked",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    employee_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    check_in: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )
    check_out: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    verification_source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="Face ID",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="checked_in",
        index=True,
    )

    # Payroll & Audit Lock Metadata
    is_locked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Latest Approved Post-Lock Edit Metadata
    last_edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_edited_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    edit_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Historical audit entries for post-lock edits
    edit_audits: Mapped[list[AttendanceEditAudit]] = relationship(
        "AttendanceEditAudit",
        back_populates="attendance_record",
        cascade="all, delete-orphan",
        order_by="AttendanceEditAudit.created_at",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<AttendanceRecord id={self.id!r} tenant_id={self.tenant_id!r} "
            f"employee_id={self.employee_id!r} status={self.status!r} "
            f"is_locked={self.is_locked!r}>"
        )


class AttendanceEditAudit(Base, TenantMixin, TimestampMixin):
    """Immutable audit log capturing before/after values of post-lock edits."""

    __tablename__ = "attendance_edit_audits"
    __table_args__ = (
        CheckConstraint(
            "approved_by != edited_by",
            name="no_self_approval",
        ),
        CheckConstraint(
            "new_check_out IS NULL OR new_check_out >= new_check_in",
            name="valid_new_shift_window",
        ),
        Index(
            "ix_attendance_edit_audits_tenant_record",
            "tenant_id",
            "attendance_record_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=_new_edit_audit_id,
    )
    attendance_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("attendance_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    previous_check_in: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    previous_check_out: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    new_check_in: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    new_check_out: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    edited_by: Mapped[str] = mapped_column(String(100), nullable=False)
    approval_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    approved_by: Mapped[str] = mapped_column(String(100), nullable=False)
    edit_reason: Mapped[str] = mapped_column(String(500), nullable=False)

    attendance_record: Mapped[AttendanceRecord] = relationship(
        "AttendanceRecord",
        back_populates="edit_audits",
    )

    def __repr__(self) -> str:
        return (
            f"<AttendanceEditAudit id={self.id!r} "
            f"attendance_record_id={self.attendance_record_id!r} "
            f"approval_id={self.approval_id!r}>"
        )


__all__ = [
    "ATTENDANCE_STATUSES",
    "AttendanceRecord",
    "AttendanceEditAudit",
]