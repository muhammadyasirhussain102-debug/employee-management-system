"""Pydantic v2 schemas package for the Employee Management module.

Provides shared base models and session identity schemas. Individual domain
schema modules (`policy`, `leave`, `attendance`, `ticket`, `training`, and
`complaint`) will be imported and re-exported here as they are implemented.
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

PACKAGE_NAME: str = "employee_mgmt.schemas"

UserRole = Literal["employee", "manager", "hr", "admin"]

# Planned domain schema modules for this package.
EXPECTED_SCHEMA_MODULES: tuple[str, ...] = (
    "policy",
    "leave",
    "attendance",
    "ticket",
    "training",
    "complaint",
)

T = TypeVar("T")


class SchemaBase(BaseModel):
    """Base Pydantic schema with consistent whitespace and validation behavior."""

    model_config = ConfigDict(str_strip_whitespace=True)


class ORMModel(SchemaBase):
    """Base response schema supporting direct SQLAlchemy ORM serialization."""

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
    )


class SessionUser(BaseModel):
    """Verified user identity loaded strictly from server-side session state."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(..., min_length=1, max_length=100)
    tenant_id: str = Field(..., min_length=1, max_length=100)
    role: UserRole


class PaginatedResponse(SchemaBase, Generic[T]):
    """Standard paginated list envelope shared across domain endpoints."""

    total: int = Field(..., ge=0)
    limit: int = Field(..., ge=1, le=100)
    offset: int = Field(..., ge=0)
    items: list[T]


__all__ = [
    "PACKAGE_NAME",
    "EXPECTED_SCHEMA_MODULES",
    "UserRole",
    "SchemaBase",
    "ORMModel",
    "SessionUser",
    "PaginatedResponse",
]