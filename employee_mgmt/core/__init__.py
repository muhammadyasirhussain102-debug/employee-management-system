"""Core configuration and shared guardrail constants for Employee Management.

Configuration objects from `core/config.py` (such as `Settings` and `settings`)
will be exposed here once `core/config.py` is implemented.
"""

from __future__ import annotations

PACKAGE_NAME: str = "employee_mgmt.core"
DEFAULT_API_V1_PREFIX: str = "/api/v1"

# Standard RBAC roles enforced across all Employee Management routes.
VALID_USER_ROLES: frozenset[str] = frozenset(
    {
        "employee",
        "manager",
        "hr",
        "admin",
    }
)

# High-risk actions that must fail closed unless explicit non-self approval is present.
HIGH_RISK_ACTIONS: frozenset[str] = frozenset(
    {
        "policy.publish",
        "leave.exception",
        "attendance.post_lock_edit",
    }
)

__all__ = [
    "PACKAGE_NAME",
    "DEFAULT_API_V1_PREFIX",
    "VALID_USER_ROLES",
    "HIGH_RISK_ACTIONS",
]