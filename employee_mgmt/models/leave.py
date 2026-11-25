"""SQLAlchemy ORM models for the LeaveFlow domain.

Defines tenant-isolated `LeaveRequest` and `LeaveEntitlement` tables with
database-level integrity constraints, non-self-approval enforcement, and
fail-closed audit guardrails for high-risk `leave.exception` overrides.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TenantMixin, TimestampMixin

LEAVE_TYPES: tuple[str, ...] = ("annual", "sick", "casual", "unpaid")
LEAVE_STATUSES: tuple[str, ...] = ("pending", "approved", "rejected", "cancelled")

DEFAULT_ANNUAL_ENTITLEMENTS: dict[str, int | None] = {
    "annual": 20,
    "sick": 10,
    "casual": 5,
    "unpaid": None,
}


def _new_leave_request_id() -> str:
    """Generate a prefixed unique identifier for a leave request record."""
    return f"lvr_{uuid4().hex[:12]}"


def _new_entitlement_id() -> str:
    """Generate a prefixed unique identifier for a leave entitlement record."""
    return f"lve_{uuid4().hex[:12]}"


class LeaveRequest(Base, TenantMixin, TimestampMixin):
    """Tenant-scoped employee leave request and high-risk exception record."""

    __tablename__ = "leave_requests"
    __table_args__ = (
        CheckConstraint(
            "leave_type IN ('annual', 'sick', 'casual', 'unpaid')",
            name="valid_leave_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="valid_status",
        ),
        CheckConstraint("end_date >= start_date", name="valid_date_range"),
        CheckConstraint("business_days >= 1", name="positive_business_days"),
        # Prevent self-approval or self-rejection at the database level.
        CheckConstraint(
            "decided_by IS NULL OR decided_by != employee_id",
            name="no_self_decision",
        ),
        # Database-level fail-closed guardrail for high-risk `leave.exception`.
        CheckConstraint(
            "(NOT is_exception) OR ("
            "approval_id IS NOT NULL "
            "AND approved_by IS NOT NULL "
            "AND exception_reason IS NOT NULL "
            "AND approved_by != created_by "
            "AND employee_id != created_by"
            ")",
            name="exception_requires_non_self_approval",
        ),
        Index(
            "ix_leave_requests_tenant_employee_status",
            "tenant_id",
            "employee_id",
            "status",
        ),
        Index(
            "ix_leave_requests_tenant_employee_dates",
            "tenant_id",
            "employee_id",
            "start_date",
            "end_date",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=_new_leave_request_id,
    )
    employee_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    leave_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    business_days: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )
    is_exception: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )

    # Actor & Decision Audit Metadata
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    decision_comment: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # High-Risk `leave.exception` Approval Metadata
    approval_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exception_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<LeaveRequest id={self.id!r} tenant_id={self.tenant_id!r} "
            f"employee_id={self.employee_id!r} leave_type={self.leave_type!r} "
            f"status={self.status!r}>"
        )


class LeaveEntitlement(Base, TenantMixin, TimestampMixin):
    """Per-employee annual leave entitlement used for deterministic balance math."""

    __tablename__ = "leave_entitlements"
    __table_args__ = (
        CheckConstraint(
            "leave_type IN ('annual', 'sick', 'casual', 'unpaid')",
            name="valid_leave_type",
        ),
        CheckConstraint("year >= 2000 AND year <= 2100", name="valid_year"),
        CheckConstraint(
            "entitled_days IS NULL OR entitled_days >= 0",
            name="non_negative_entitled_days",
        ),
        UniqueConstraint(
            "tenant_id",
            "employee_id",
            "year",
            "leave_type",
            name="uq_leave_entitlements_tenant_emp_year_type",
        ),
        Index(
            "ix_leave_entitlements_tenant_emp_year",
            "tenant_id",
            "employee_id",
            "year",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=_new_entitlement_id,
    )
    employee_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    leave_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # `None` denotes no fixed paid-balance cap (e.g. unpaid leave).
    entitled_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<LeaveEntitlement id={self.id!r} tenant_id={self.tenant_id!r} "
            f"employee_id={self.employee_id!r} year={self.year} "
            f"leave_type={self.leave_type!r} entitled_days={self.entitled_days!r}>"
        )


__all__ = [
    "LEAVE_TYPES",
    "LEAVE_STATUSES",
    "DEFAULT_ANNUAL_ENTITLEMENTS",
    "LeaveRequest",
    "LeaveEntitlement",
]