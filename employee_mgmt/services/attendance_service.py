"""Domain service layer for the Face ID & Attendance feature.

Encapsulates tenant-scoped biometric check-in/check-out punches, payroll
locking, fail-closed high-risk `attendance.post_lock_edit` enforcement, and
immutable edit audit trails using SQLAlchemy 2.0 sessions.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..core.config import settings
from ..db.base import utc_now
from ..models.attendance import (
    ATTENDANCE_STATUSES,
    AttendanceEditAudit,
    AttendanceRecord,
)
from ..schemas import SessionUser
from . import ConflictError, ForbiddenError, NotFoundError, ValidationError

ATTENDANCE_SUPERVISOR_ROLES: frozenset[str] = frozenset({"manager", "hr", "admin"})
ATTENDANCE_ADMIN_ROLES: frozenset[str] = frozenset({"hr", "admin"})


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------


def _ensure_utc(dt: datetime) -> datetime:
    """Normalize naive or aware datetimes to timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _can_view_employee_attendance(
    current_user: SessionUser,
    target_employee_id: str,
) -> bool:
    """Allow employees to view their own records and supervisors to view tenant records."""
    if current_user.user_id == target_employee_id:
        return True
    return current_user.role in ATTENDANCE_SUPERVISOR_ROLES


# ---------------------------------------------------------------------------
# Service Operations
# ---------------------------------------------------------------------------


def record_punch(
    db: Session,
    current_user: SessionUser,
    *,
    employee_id: str | None = None,
    verification_source: str = "Face ID",
    face_detected: bool = True,
) -> tuple[AttendanceRecord, str]:
    """Record a check-in or check-out punch for an employee.

    If the employee has an open (`checked_in`) record in the current tenant,
    this closes the shift (`checked_out`). Otherwise, it starts a new shift.
    Returns `(record, message)`.
    """
    target_employee_id = (employee_id or current_user.user_id).strip()
    if not target_employee_id:
        raise ValidationError("employee_id cannot be blank.")

    if (
        target_employee_id != current_user.user_id
        and current_user.role not in ATTENDANCE_ADMIN_ROLES
    ):
        raise ForbiddenError(
            "You are only authorized to record attendance punches for yourself."
        )

    cleaned_source = verification_source.strip() or "Face ID"
    if cleaned_source.lower() == "face id" and not face_detected:
        raise ValidationError(
            "Face verification failed: no live face detected for Face ID punch."
        )

    open_stmt = (
        select(AttendanceRecord)
        .where(
            AttendanceRecord.tenant_id == current_user.tenant_id,
            AttendanceRecord.employee_id == target_employee_id,
            AttendanceRecord.status == "checked_in",
        )
        .order_by(AttendanceRecord.check_in.desc())
        .limit(1)
    )
    open_record = db.scalar(open_stmt)
    now = utc_now()

    if open_record is not None:
        if open_record.is_locked:
            raise ConflictError(
                "Active attendance record is locked and cannot be modified by a standard punch."
            )
        open_record.check_out = now
        open_record.status = "checked_out"
        db.commit()
        db.refresh(open_record)
        return open_record, "Check-out recorded successfully."

    new_record = AttendanceRecord(
        tenant_id=current_user.tenant_id,
        employee_id=target_employee_id,
        check_in=now,
        check_out=None,
        verification_source=cleaned_source,
        status="checked_in",
        is_locked=False,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)
    return new_record, "Check-in recorded successfully."


def list_attendance_records(
    db: Session,
    current_user: SessionUser,
    *,
    employee_id: str | None = None,
    status: str | None = None,
    is_locked: bool | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[int, list[AttendanceRecord]]:
    """List tenant-scoped attendance records visible to the authenticated user."""
    cleaned_employee_id = employee_id.strip() if employee_id else None
    if (
        cleaned_employee_id is not None
        and not _can_view_employee_attendance(current_user, cleaned_employee_id)
    ):
        raise ForbiddenError(
            "You are only authorized to view your own attendance records."
        )

    filters = [AttendanceRecord.tenant_id == current_user.tenant_id]

    if current_user.role not in ATTENDANCE_SUPERVISOR_ROLES:
        filters.append(AttendanceRecord.employee_id == current_user.user_id)
    elif cleaned_employee_id is not None:
        filters.append(AttendanceRecord.employee_id == cleaned_employee_id)

    if status is not None:
        normalized_status = status.strip().lower()
        if normalized_status not in ATTENDANCE_STATUSES:
            raise ValidationError(
                f"Invalid status {status!r}. Must be one of {ATTENDANCE_STATUSES}."
            )
        filters.append(AttendanceRecord.status == normalized_status)

    if is_locked is not None:
        filters.append(AttendanceRecord.is_locked == is_locked)

    total_stmt = select(func.count()).select_from(AttendanceRecord).where(*filters)
    total = int(db.scalar(total_stmt) or 0)

    items_stmt = (
        select(AttendanceRecord)
        .where(*filters)
        .order_by(AttendanceRecord.check_in.desc())
        .offset(offset)
        .limit(limit)
    )
    items = list(db.scalars(items_stmt).all())
    return total, items


def get_attendance_record(
    db: Session,
    current_user: SessionUser,
    record_id: int,
) -> AttendanceRecord:
    """Fetch a single tenant-scoped attendance record visible to the current user."""
    stmt = (
        select(AttendanceRecord)
        .options(selectinload(AttendanceRecord.edit_audits))
        .where(
            AttendanceRecord.id == record_id,
            AttendanceRecord.tenant_id == current_user.tenant_id,
        )
    )
    record = db.scalar(stmt)
    if record is None:
        raise NotFoundError("Attendance record not found.")

    if not _can_view_employee_attendance(current_user, record.employee_id):
        raise NotFoundError("Attendance record not found.")

    return record


def lock_attendance_record(
    db: Session,
    current_user: SessionUser,
    *,
    record_id: int,
) -> AttendanceRecord:
    """Lock an attendance record for payroll/audit freeze (HR/Admin only)."""
    if current_user.role not in ATTENDANCE_ADMIN_ROLES:
        raise ForbiddenError(
            "Only HR or Admin roles are authorized to lock attendance records."
        )

    stmt = select(AttendanceRecord).where(
        AttendanceRecord.id == record_id,
        AttendanceRecord.tenant_id == current_user.tenant_id,
    )
    record = db.scalar(stmt)
    if record is None:
        raise NotFoundError("Attendance record not found.")

    if record.is_locked:
        raise ConflictError("Attendance record is already locked.")

    record.is_locked = True
    record.locked_at = utc_now()
    record.locked_by = current_user.user_id

    db.commit()
    db.refresh(record)
    return record


def edit_locked_attendance_record(
    db: Session,
    current_user: SessionUser,
    *,
    record_id: int,
    check_in: datetime | None,
    check_out: datetime | None,
    approval_id: str,
    approved_by: str,
    edit_reason: str,
) -> AttendanceRecord:
    """Edit a locked attendance record with fail-closed `attendance.post_lock_edit` guardrails.

    Guardrails:
    - Actor must be HR or Admin.
    - Record must be locked (`is_locked=True`).
    - Explicit `approval_id`, `approved_by`, and `edit_reason` are required.
    - Forbids self-approval (`approved_by == current_user.user_id`) and
      self-edit (`record.employee_id == current_user.user_id`).
    - Persists an immutable `AttendanceEditAudit` entry capturing before/after timestamps.
    """
    if current_user.role not in ATTENDANCE_ADMIN_ROLES:
        raise ForbiddenError(
            "Only HR or Admin roles are authorized to perform post-lock attendance edits."
        )

    if check_in is None and check_out is None:
        raise ValidationError(
            "At least one of 'check_in' or 'check_out' must be provided."
        )

    cleaned_approval_id = approval_id.strip()
    cleaned_approved_by = approved_by.strip()
    cleaned_edit_reason = edit_reason.strip()

    if settings.HIGH_RISK_APPROVAL_REQUIRED:
        if len(cleaned_approval_id) < 4:
            raise ForbiddenError(
                "High-risk action 'attendance.post_lock_edit' requires a valid approval_id."
            )
        if len(cleaned_approved_by) < 2:
            raise ForbiddenError(
                "High-risk action 'attendance.post_lock_edit' requires a valid approved_by."
            )
        if len(cleaned_edit_reason) < 10:
            raise ForbiddenError(
                "High-risk action 'attendance.post_lock_edit' requires a detailed edit_reason."
            )
        if cleaned_approved_by == current_user.user_id:
            raise ForbiddenError(
                "Self-approval is forbidden for high-risk action 'attendance.post_lock_edit'."
            )

    stmt = select(AttendanceRecord).where(
        AttendanceRecord.id == record_id,
        AttendanceRecord.tenant_id == current_user.tenant_id,
    )
    record = db.scalar(stmt)
    if record is None:
        raise NotFoundError("Attendance record not found.")

    if not record.is_locked:
        raise ConflictError(
            "Post-lock edit is only applicable to locked attendance records."
        )

    if record.employee_id == current_user.user_id:
        raise ForbiddenError(
            "You cannot perform a post-lock edit on your own attendance record."
        )

    prev_check_in = _ensure_utc(record.check_in)
    prev_check_out = _ensure_utc(record.check_out) if record.check_out else None

    new_check_in = _ensure_utc(check_in) if check_in is not None else prev_check_in
    new_check_out = (
        _ensure_utc(check_out) if check_out is not None else prev_check_out
    )

    if new_check_out is not None and new_check_out < new_check_in:
        raise ValidationError("check_out timestamp cannot be earlier than check_in.")

    now = utc_now()
    audit_entry = AttendanceEditAudit(
        tenant_id=current_user.tenant_id,
        attendance_record_id=record.id,
        previous_check_in=prev_check_in,
        previous_check_out=prev_check_out,
        new_check_in=new_check_in,
        new_check_out=new_check_out,
        edited_by=current_user.user_id,
        approval_id=cleaned_approval_id,
        approved_by=cleaned_approved_by,
        edit_reason=cleaned_edit_reason,
    )

    record.check_in = new_check_in
    record.check_out = new_check_out
    record.status = "checked_out" if new_check_out is not None else "checked_in"
    record.last_edited_at = now
    record.last_edited_by = current_user.user_id
    record.approval_id = cleaned_approval_id
    record.approved_by = cleaned_approved_by
    record.edit_reason = cleaned_edit_reason

    db.add(audit_entry)
    db.commit()
    db.refresh(record)
    return record


def list_attendance_edit_audits(
    db: Session,
    current_user: SessionUser,
    *,
    record_id: int,
) -> list[AttendanceEditAudit]:
    """Return the immutable post-lock edit audit trail for a record (HR/Admin only)."""
    if current_user.role not in ATTENDANCE_ADMIN_ROLES:
        raise ForbiddenError(
            "Only HR or Admin roles are authorized to view attendance edit audits."
        )

    # Verify record exists within tenant before returning audits.
    exists_stmt = select(AttendanceRecord.id).where(
        AttendanceRecord.id == record_id,
        AttendanceRecord.tenant_id == current_user.tenant_id,
    )
    if db.scalar(exists_stmt) is None:
        raise NotFoundError("Attendance record not found.")

    audits_stmt = (
        select(AttendanceEditAudit)
        .where(
            AttendanceEditAudit.tenant_id == current_user.tenant_id,
            AttendanceEditAudit.attendance_record_id == record_id,
        )
        .order_by(AttendanceEditAudit.created_at.desc())
    )
    return list(db.scalars(audits_stmt).all())


__all__ = [
    "ATTENDANCE_SUPERVISOR_ROLES",
    "ATTENDANCE_ADMIN_ROLES",
    "record_punch",
    "list_attendance_records",
    "get_attendance_record",
    "lock_attendance_record",
    "edit_locked_attendance_record",
    "list_attendance_edit_audits",
]