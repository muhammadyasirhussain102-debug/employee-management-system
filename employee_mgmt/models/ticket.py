"""SQLAlchemy ORM models for the IT Support Tickets domain.

Defines tenant-isolated `Ticket` records and an immutable `TicketAuditEvent`
history table with database-level lifecycle and lock integrity constraints.
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
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, TenantMixin, TimestampMixin

TICKET_CATEGORIES: tuple[str, ...] = (
    "hardware",
    "software",
    "access",
    "network",
    "other",
)
TICKET_PRIORITIES: tuple[str, ...] = ("low", "medium", "high", "urgent")
TICKET_STATUSES: tuple[str, ...] = ("open", "in_progress", "resolved", "closed")
TICKET_EVENT_TYPES: tuple[str, ...] = (
    "created",
    "status_changed",
    "assigned",
    "locked",
)


def _new_ticket_id() -> str:
    """Generate a prefixed unique identifier for an IT support ticket."""
    return f"tkt_{uuid4().hex[:12]}"


def _new_ticket_event_id() -> str:
    """Generate a prefixed unique identifier for a ticket audit event."""
    return f"tke_{uuid4().hex[:12]}"


class Ticket(Base, TenantMixin, TimestampMixin):
    """Tenant-scoped IT support ticket with lock and closure integrity rules."""

    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "category IN ('hardware', 'software', 'access', 'network', 'other')",
            name="valid_category",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')",
            name="valid_priority",
        ),
        CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'closed')",
            name="valid_status",
        ),
        CheckConstraint(
            "status != 'resolved' OR resolution_note IS NOT NULL",
            name="resolved_requires_resolution_note",
        ),
        CheckConstraint(
            "status != 'closed' OR (is_locked AND closed_at IS NOT NULL)",
            name="closed_ticket_must_be_locked",
        ),
        CheckConstraint(
            "(NOT is_locked) OR ("
            "locked_at IS NOT NULL "
            "AND locked_by IS NOT NULL "
            "AND lock_reason IS NOT NULL"
            ")",
            name="lock_requires_actor_timestamp_and_reason",
        ),
        Index(
            "ix_tickets_tenant_status_priority",
            "tenant_id",
            "status",
            "priority",
        ),
        Index(
            "ix_tickets_tenant_requester",
            "tenant_id",
            "requester_id",
        ),
        Index(
            "ix_tickets_tenant_locked",
            "tenant_id",
            "is_locked",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=_new_ticket_id,
    )
    requester_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="other",
        index=True,
    )
    priority: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="medium",
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="open",
        index=True,
    )
    assigned_to: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    # Immutable Lock & Closure Metadata
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
    lock_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Ordered audit trail for lifecycle transitions and lock events
    audit_events: Mapped[list[TicketAuditEvent]] = relationship(
        "TicketAuditEvent",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketAuditEvent.created_at",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<Ticket id={self.id!r} tenant_id={self.tenant_id!r} "
            f"status={self.status!r} priority={self.priority!r} "
            f"is_locked={self.is_locked!r}>"
        )


class TicketAuditEvent(Base, TenantMixin, TimestampMixin):
    """Immutable audit entry recording ticket lifecycle and lock events."""

    __tablename__ = "ticket_audit_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'status_changed', 'assigned', 'locked')",
            name="valid_event_type",
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('open', 'in_progress', 'resolved', 'closed')",
            name="valid_from_status",
        ),
        CheckConstraint(
            "to_status IS NULL OR to_status IN ('open', 'in_progress', 'resolved', 'closed')",
            name="valid_to_status",
        ),
        Index(
            "ix_ticket_audit_events_tenant_ticket",
            "tenant_id",
            "ticket_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=_new_ticket_event_id,
    )
    ticket_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    ticket: Mapped[Ticket] = relationship("Ticket", back_populates="audit_events")

    def __repr__(self) -> str:
        return (
            f"<TicketAuditEvent id={self.id!r} ticket_id={self.ticket_id!r} "
            f"event_type={self.event_type!r}>"
        )


__all__ = [
    "TICKET_CATEGORIES",
    "TICKET_PRIORITIES",
    "TICKET_STATUSES",
    "TICKET_EVENT_TYPES",
    "Ticket",
    "TicketAuditEvent",
]