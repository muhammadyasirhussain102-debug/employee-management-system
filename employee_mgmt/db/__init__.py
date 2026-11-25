"""Database package for the Employee Management backend module.

Provides package metadata and deterministic SQLAlchemy/Alembic constraint
naming conventions. Database declarative base (`base.py`) and session helpers
(`session.py`) will be exposed here once those files are implemented.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

PACKAGE_NAME: str = "employee_mgmt.db"

# Standard naming convention for deterministic SQLAlchemy & Alembic migrations.
DB_NAMING_CONVENTION: Mapping[str, str] = MappingProxyType(
    {
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

__all__ = [
    "PACKAGE_NAME",
    "DB_NAMING_CONVENTION",
]