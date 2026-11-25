"""SQLAlchemy declarative base and reusable ORM mixins for Employee Management.

All ORM models in `modules/employee_mgmt/models/` inherit from `Base` defined
here so metadata, constraint naming conventions, and Alembic autogeneration
stay consistent across SQLite and PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

try:
    from . import DB_NAMING_CONVENTION
except ImportError:
    DB_NAMING_CONVENTION = {
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }


def utc_now() -> datetime:
    """Return a timezone-aware UTC datetime for ORM defaults."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base declarative class for all Employee Management SQLAlchemy models."""

    metadata = MetaData(naming_convention=dict(DB_NAMING_CONVENTION))

    def to_dict(self) -> dict[str, Any]:
        """Serialize mapped column attributes into a plain dictionary."""
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }


class TenantMixin:
    """Mixin enforcing indexed multi-tenant scoping on domain tables.

    Intentionally excludes any user-identifying columns so privacy-sensitive
    models (such as anonymous complaints) can remain tenant-scoped without
    storing submitter identity.
    """

    tenant_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )


class TimestampMixin:
    """Mixin providing timezone-aware UTC creation and update timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


__all__ = [
    "Base",
    "TenantMixin",
    "TimestampMixin",
    "utc_now",
]