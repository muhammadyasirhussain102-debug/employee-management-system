"""SQLAlchemy ORM models for the Anonymous Complaint Box domain.

Enforces strict whistleblower privacy at the database schema level:
- Zero submitter-identifying columns (`user_id`, `employee_id`, `email`,
  `ip_address`, `user_agent`, or session IDs are intentionally absent).
- Only the SHA-256 hex digest of the tracking token is persisted.
- HR/Admin triage actions are audited separately without storing submitter PII.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, TenantMixin, TimestampMixin, utc_now

COMPLAINT_CATEGORIES: tuple[str, ...] = (
    "harassment",
    "discrimination",
    "safety",
    "ethics",
    "retaliation",
    "policy_violation",
    "other",
)
COMPLAINT_STATUSES: tuple[str, ...] = (
    "submitted",
    "under_review",
    "action_taken",
    "resolved",
    "dismissed",
)


def _new_complaint_id() -> str:
    """Generate a prefixed unique identifier for an anonymous complaint."""
    return f"cmp_{uuid4().hex[:12]}"


def _new_complaint_event_id() -> str:
    """Generate a prefixed unique identifier for a complaint triage audit event."""
    return f"cme_{uuid4().hex[:12]}"


class AnonymousComplaint(Base, TenantMixin, TimestampMixin):
    """Tenant-scoped whistleblower complaint with zero submitter-tracking data."""

    __tablename__ = "anonymous_complaints"
    __table_args__ = (
        CheckConstraint(
            "category IN ("
            "'harassment', 'discrimination', 'safety', 'ethics', "
            "'retaliation', 'policy_violation', 'other'"
            ")",
            name="valid_category",
        ),
        CheckConstraint(
            "status IN ("
            "'submitted', 'under_review', 'action_taken', 'resolved', 'dismissed'"
            ")",
            name="valid_status",
        ),
        # Enforce that only a 64-character SHA-256 hex digest is stored.
        CheckConstraint(
            "length(tracking_token_hash) = 64",
            name="sha256_tracking_token_hash_length",
        ),
        # Any triaged state must record the HR/Admin reviewer and timestamp.
        CheckConstraint(
            "status = 'submitted' OR ("
            "reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL"
            ")",
            name="triaged_status_requires_reviewer",
        ),
        # Terminal states must include a public update and resolution timestamp.
        CheckConstraint(
            "status NOT IN ('resolved', 'dismissed') OR ("
            "resolved_at IS NOT NULL AND public_update IS NOT NULL"
            ")",
            name="terminal_status_requires_resolution_details",
        ),
        Index(
            "ix_anonymous_complaints_tenant_status_category",
            "tenant_id",
            "status",
            "category",
        ),
        Index(
            "ix_anonymous_complaints_tenant_submitted",
            "tenant_id",
            "submitted_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=_new_complaint_id,
    )
    category: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="other",
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="submitted",
        index=True,
    )

    # SHA-256 hex digest of the one-time tracking token (never store raw token).
    tracking_token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )

    # HR/Admin Triage & Public Status Fields (no submitter metadata)
    public_update: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Ordered HR/Admin triage audit trail
    audit_events: Mapped[list[ComplaintAuditEvent]] = relationship(
        "ComplaintAuditEvent",
        back_populates="complaint",
        cascade="all, delete-orphan",
        order_by="ComplaintAuditEvent.created_at",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<AnonymousComplaint id={self.id!r} tenant_id={self.tenant_id!r} "
            f"category={self.category!r} status={self.status!r}>"
        )


class ComplaintAuditEvent(Base, TenantMixin, TimestampMixin):
    """Immutable HR/Admin triage audit trail (contains zero submitter PII)."""

    __tablename__ = "complaint_audit_events"
    __table_args__ = (
        CheckConstraint(
            "from_status IN ("
            "'submitted', 'under_review', 'action_taken', 'resolved', 'dismissed'"
            ")",
            name="valid_from_status",
        ),
        CheckConstraint(
            "to_status IN ("
            "'submitted', 'under_review', 'action_taken', 'resolved', 'dismissed'"
            ")",
            name="valid_to_status",
        ),
        Index(
            "ix_complaint_audit_events_tenant_complaint",
            "tenant_id",
            "complaint_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=_new_complaint_event_id,
    )
    complaint_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("anonymous_complaints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer_id: Mapped[str] = mapped_column(String(100), nullable=False)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    public_update: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    complaint: Mapped[AnonymousComplaint] = relationship(
        "AnonymousComplaint",
        back_populates="audit_events",
    )

    def __repr__(self) -> str:
        return (
            f"<ComplaintAuditEvent id={self.id!r} "
            f"complaint_id={self.complaint_id!r} "
            f"from_status={self.from_status!r} to_status={self.to_status!r}>"
        )


__all__ = [
    "COMPLAINT_CATEGORIES",
    "COMPLAINT_STATUSES",
    "AnonymousComplaint",
    "ComplaintAuditEvent",
]