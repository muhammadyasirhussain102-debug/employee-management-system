"""SQLAlchemy ORM models for the Policy Brain domain.

Defines tenant-isolated `Policy` documents and citation-ready `PolicyChunk`
records compatible with both local SQLite and PostgreSQL/pgvector deployments.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, TenantMixin, TimestampMixin

POLICY_VISIBILITIES: tuple[str, ...] = ("all", "manager", "hr", "admin")
POLICY_STATUSES: tuple[str, ...] = ("draft", "published", "archived")


def _new_policy_id() -> str:
    """Generate a prefixed unique identifier for a policy record."""
    return f"pol_{uuid4().hex[:12]}"


def _new_chunk_id() -> str:
    """Generate a prefixed unique identifier for a policy chunk record."""
    return f"chk_{uuid4().hex[:12]}"


class Policy(Base, TenantMixin, TimestampMixin):
    """Tenant-scoped company policy document with fail-closed publish audit fields."""

    __tablename__ = "policies"
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('all', 'manager', 'hr', 'admin')",
            name="valid_visibility",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="valid_status",
        ),
        CheckConstraint("version >= 1", name="positive_version"),
        # Database-level fail-closed guardrail for high-risk `policy.publish`.
        CheckConstraint(
            "status != 'published' OR ("
            "approval_id IS NOT NULL "
            "AND approved_by IS NOT NULL "
            "AND published_by IS NOT NULL "
            "AND approved_by != published_by"
            ")",
            name="published_requires_non_self_approval",
        ),
        Index("ix_policies_tenant_status_visibility", "tenant_id", "status", "visibility"),
        Index("ix_policies_tenant_category", "tenant_id", "category"),
    )

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=_new_policy_id,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="general",
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="all",
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Authoring & High-Risk Publication Audit Metadata
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    published_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    change_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Ordered citation chunks owned by this policy
    chunks: Mapped[list[PolicyChunk]] = relationship(
        "PolicyChunk",
        back_populates="policy",
        cascade="all, delete-orphan",
        order_by="PolicyChunk.chunk_index",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<Policy id={self.id!r} tenant_id={self.tenant_id!r} "
            f"status={self.status!r} version={self.version}>"
        )


class PolicyChunk(Base, TenantMixin, TimestampMixin):
    """Deterministic text chunk of a policy for citation-backed RAG retrieval."""

    __tablename__ = "policy_chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="non_negative_chunk_index"),
        UniqueConstraint("policy_id", "chunk_index", name="uq_policy_chunks_policy_idx"),
        Index("ix_policy_chunks_tenant_policy", "tenant_id", "policy_id"),
    )

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=_new_chunk_id,
    )
    policy_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("policies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # Portable JSON float vector for SQLite/PostgreSQL compatibility;
    # can be migrated to pgvector `Vector(...)` with an HNSW index via Alembic.
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)

    policy: Mapped[Policy] = relationship("Policy", back_populates="chunks")

    def __repr__(self) -> str:
        return (
            f"<PolicyChunk id={self.id!r} policy_id={self.policy_id!r} "
            f"chunk_index={self.chunk_index}>"
        )


__all__ = [
    "POLICY_VISIBILITIES",
    "POLICY_STATUSES",
    "Policy",
    "PolicyChunk",
]