"""Pydantic v2 schemas for the LeaveFlow domain.

Provides validated request payloads and ORM-compatible response models for
leave requests, manager/HR decisions, fail-closed leave exceptions, and
deterministic code-calculated leave balances.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from . import ORMModel, PaginatedResponse, SchemaBase

LeaveType = Literal["annual", "sick", "casual", "unpaid"]
LeaveStatus = Literal["pending", "approved", "rejected", "cancelled"]
DecisionAction = Literal["approve", "reject"]


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------


class LeaveRequestCreate(SchemaBase):
    """Payload to submit a standard employee leave request."""

    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: str = Field(..., min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if len(value) < 5:
            raise ValueError("Reason must be at least 5 characters long.")
        return value

    @model_validator(mode="after")
    def validate_date_range(self) -> LeaveRequestCreate:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date.")
        if self.start_date.year != self.end_date.year:
            raise ValueError(
                "Leave requests cannot span across calendar years. "
                "Please submit separate requests for each year."
            )
        return self


class LeaveDecisionRequest(SchemaBase):
    """Payload for Manager/HR/Admin to approve or reject a pending request."""

    action: DecisionAction
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value or None


class LeaveExceptionCreate(SchemaBase):
    """Approval-backed payload for the high-risk `leave.exception` action."""

    employee_id: str = Field(..., min_length=1, max_length=100)
    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: str = Field(..., min_length=5, max_length=500)
    approval_id: str = Field(
        ...,
        min_length=4,
        max_length=100,
        description="Verified approval reference authorizing this leave exception.",
    )
    approved_by: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="User ID of the approver (must differ from the acting user).",
    )
    exception_reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Audit justification for overriding normal leave rules.",
    )

    @model_validator(mode="after")
    def validate_date_range(self) -> LeaveExceptionCreate:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date.")
        if self.start_date.year != self.end_date.year:
            raise ValueError(
                "Leave exceptions cannot span across calendar years."
            )
        return self


class LeaveEntitlementUpsert(SchemaBase):
    """HR/Admin payload to set an employee's annual entitlement for a leave type."""

    employee_id: str = Field(..., min_length=1, max_length=100)
    year: int = Field(..., ge=2000, le=2100)
    leave_type: LeaveType
    entitled_days: int | None = Field(
        default=None,
        ge=0,
        le=366,
        description="Annual business-day quota, or None for uncapped unpaid leave.",
    )


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class LeaveRequestResponse(ORMModel):
    """Full representation of a leave request or exception record."""

    id: str
    tenant_id: str
    employee_id: str
    leave_type: LeaveType
    start_date: date
    end_date: date
    business_days: int = Field(..., ge=1)
    reason: str
    status: LeaveStatus
    is_exception: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_comment: str | None = None
    approval_id: str | None = None
    approved_by: str | None = None
    exception_reason: str | None = None


class LeaveRequestListResponse(PaginatedResponse[LeaveRequestResponse]):
    """Paginated list of leave requests."""


class LeaveTypeBalance(SchemaBase):
    """Deterministic balance breakdown for a single leave type."""

    leave_type: LeaveType
    entitled_days: int | None = None
    used_days: int = Field(..., ge=0)
    pending_days: int = Field(..., ge=0)
    remaining_days: int | None = None


class LeaveBalanceResponse(SchemaBase):
    """Code-calculated leave balance summary for an employee in a given year."""

    tenant_id: str
    employee_id: str
    year: int = Field(..., ge=2000, le=2100)
    balances: list[LeaveTypeBalance]


class LeaveEntitlementResponse(ORMModel):
    """Serialized representation of a stored annual leave entitlement."""

    id: str
    tenant_id: str
    employee_id: str
    year: int
    leave_type: LeaveType
    entitled_days: int | None = None
    created_at: datetime
    updated_at: datetime


__all__ = [
    "LeaveType",
    "LeaveStatus",
    "DecisionAction",
    "LeaveRequestCreate",
    "LeaveDecisionRequest",
    "LeaveExceptionCreate",
    "LeaveEntitlementUpsert",
    "LeaveRequestResponse",
    "LeaveRequestListResponse",
    "LeaveTypeBalance",
    "LeaveBalanceResponse",
    "LeaveEntitlementResponse",
]