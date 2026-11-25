"""SQLAlchemy ORM models package for the Employee Management module.

Individual domain model modules (`policy`, `leave`, `attendance`, `ticket`,
`training`, and `complaint`) will be imported and re-exported here as each
model file is implemented so `Base.metadata` and Alembic can discover all
tables reliably.
"""

from __future__ import annotations

from ..db.base import Base

PACKAGE_NAME: str = "employee_mgmt.models"

# Planned domain model modules for this package.
EXPECTED_MODEL_MODULES: tuple[str, ...] = (
    "policy",
    "leave",
    "attendance",
    "ticket",
    "training",
    "complaint",
)

# Model classes will be added here as each model file is implemented.
REGISTERED_MODELS: tuple[type[Base], ...] = ()


def get_registered_table_names() -> list[str]:
    """Return a sorted list of table names currently registered on Base.metadata."""
    return sorted(Base.metadata.tables.keys())


__all__ = [
    "PACKAGE_NAME",
    "Base",
    "EXPECTED_MODEL_MODULES",
    "REGISTERED_MODELS",
    "get_registered_table_names",
]