"""Pydantic v2 schemas for the Face ID & Attendance domain.

Provides validated request payloads and ORM-compatible response models for
biometric check-in/check-out punches, attendance records, fail-closed
post-lock edits, and immutable post-lock edit audit entries.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from . import ORMModel, PaginatedResponse, SchemaBase

AttendanceStatus = Literal["checked_in", "checked_out"]
AllowedVerificationSource = Literal["Face ID", "Web Kiosk", "Manual Override"]


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------


class AttendancePunchRequest(SchemaBase):
    """Payload matching frontend `client.ts` PunchPayload."""

    employee_id: str = Field(..., min_length=1, max_length=100)
    verification_source: str = Field(
        default="Face ID",
        min_length=2,
        max_length=50,
    )
    face_detected: bool = Field(default=True)


class PostLockEditRequest(SchemaBase):
    """Approval-backed payload for the high-risk `attendance.post_lock_edit` action."""

    check_in: datetime | None = Field(
        default=None,
        description="Updated check-in timestamp (UTC ISO-8601).",
    )
    check_out: datetime | None = Field(
        default=None,
        description="Updated check-out timestamp (UTC ISO-8601).",
    )
    approval_id: str = Field(
        ...,
        min_length=4,
        max_length=100,
        description="Verified approval reference authorizing post-lock edit.",
    )
    approved_by: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="User ID of the approver (must differ from acting user).",
    )
    edit_reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Audit justification for editing a locked attendance record.",
    )

    @model_validator(mode="after")
    def validate_updates(self) -> PostLockEditRequest:
        if self.check_in is None and self.check_out is None:
            raise ValueError(
                "At least one of 'check_in' or 'check_out' must be provided."
            )
        if (
            self.check_in is not None
            and self.check_out is not None
            and self.check_out < self.check_in
        ):
            raise ValueError("check_out timestamp cannot be earlier than check_in.")
        return self


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class AttendancePunchResponse(ORMModel):
    """Response matching frontend `client.ts` PunchResponse."""

    id: int
    tenant_id: str
    employee_id: str
    check_in: datetime
    check_out: datetime | None = None
    verification_source: str
    is_locked: bool
    status: AttendanceStatus
    message: str


class AttendanceEditAuditResponse(ORMModel):
    """Serialized immutable audit entry for a post-lock attendance edit."""

    id: str
    tenant_id: str
    attendance_record_id: int
    previous_check_in: datetime
    previous_check_out: datetime | None = None
    new_check_in: datetime
    new_check_out: datetime | None = None
    edited_by: str
    approval_id: str
    approved_by: str
    edit_reason: str
    created_at: datetime


class AttendanceRecordResponse(ORMModel):
    """Full representation of an attendance record with lock and audit metadata."""

    id: int
    tenant_id: str
    employee_id: str
    check_in: datetime
    check_out: datetime | None = None
    verification_source: str
    status: AttendanceStatus
    is_locked: bool
    locked_at: datetime | None = None
    locked_by: str | None = None
    last_edited_at: datetime | None = None
    last_edited_by: str | None = None
    approval_id: str | None = None
    approved_by: str | None = None
    edit_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AttendanceListResponse(PaginatedResponse[AttendanceRecordResponse]):
    """Paginated list of attendance records."""


__all__ = [
    "AttendanceStatus",
    "AllowedVerificationSource",
    "AttendancePunchRequest",
    "PostLockEditRequest",
    "AttendancePunchResponse",
    "AttendanceEditAuditResponse",
    "AttendanceRecordResponse",
    "AttendanceListResponse",
]