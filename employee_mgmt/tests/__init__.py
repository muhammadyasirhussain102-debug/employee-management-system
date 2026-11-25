"""Test suite package for the Employee Management backend module.

Marks `employee_mgmt/tests` as a Python package for deterministic
`pytest` discovery and defines shared test-only tenant and environment
constants.
"""

from __future__ import annotations

PACKAGE_NAME: str = "employee_mgmt.tests"

# Shared isolated test defaults (never used in production).
TEST_TENANT_ID: str = "tenant_test_primary"
TEST_OTHER_TENANT_ID: str = "tenant_test_secondary"
TEST_DATABASE_URL: str = "sqlite:///:memory:"

__all__ = [
    "PACKAGE_NAME",
    "TEST_TENANT_ID",
    "TEST_OTHER_TENANT_ID",
    "TEST_DATABASE_URL",
]