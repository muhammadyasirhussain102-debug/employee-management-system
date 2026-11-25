"""Domain services package for the Employee Management module.

Provides shared, framework-agnostic service exceptions so business logic
remains decoupled from FastAPI HTTP transport concerns. Individual service
modules will be imported and re-exported here as they are implemented.
"""

from __future__ import annotations

PACKAGE_NAME: str = "employee_mgmt.services"

# Planned domain service modules for this package.
EXPECTED_SERVICE_MODULES: tuple[str, ...] = (
    "policy_service",
    "leave_service",
    "attendance_service",
    "ticket_service",
    "training_service",
    "complaint_service",
)


class ServiceError(Exception):
    """Base exception for all Employee Management domain service errors."""

    def __init__(self, detail: str, *, code: str = "service_error") -> None:
        super().__init__(detail)
        self.detail = detail
        self.code = code


class NotFoundError(ServiceError):
    """Raised when a requested tenant-scoped resource does not exist."""

    def __init__(self, detail: str = "Resource not found.") -> None:
        super().__init__(detail, code="not_found")


class ForbiddenError(ServiceError):
    """Raised when an actor lacks permission or fails a high-risk approval check."""

    def __init__(self, detail: str = "Action not permitted.") -> None:
        super().__init__(detail, code="forbidden")


class ConflictError(ServiceError):
    """Raised on invalid state transitions, duplicates, or locked records."""

    def __init__(self, detail: str = "Resource state conflict.") -> None:
        super().__init__(detail, code="conflict")


class ValidationError(ServiceError):
    """Raised when domain-level business rules are violated."""

    def __init__(self, detail: str = "Invalid domain input.") -> None:
        super().__init__(detail, code="validation_error")


__all__ = [
    "PACKAGE_NAME",
    "EXPECTED_SERVICE_MODULES",
    "ServiceError",
    "NotFoundError",
    "ForbiddenError",
    "ConflictError",
    "ValidationError",
]