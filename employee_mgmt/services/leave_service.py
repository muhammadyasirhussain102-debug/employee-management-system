"""Domain service layer for the LeaveFlow feature.

Encapsulates tenant-scoped leave requests, deterministic business-day and
balance calculations, overlap prevention, non-self approval/rejection, and
fail-closed high-risk `leave.exception` overrides using SQLAlchemy 2.0.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..db.base import utc_now
from ..models.leave import (
    DEFAULT_ANNUAL_ENTITLEMENTS,
    LEAVE_STATUSES,
    LEAVE_TYPES,
    LeaveEntitlement,
    LeaveRequest,
)
from ..schemas import SessionUser
from ..schemas.leave import LeaveBalanceResponse, LeaveTypeBalance
from . import ConflictError, ForbiddenError, NotFoundError, ValidationError

LEAVE_APPROVER_ROLES: frozenset[str] = frozenset({"manager", "hr", "admin"})
LEAVE_ADMIN_ROLES: frozenset[str] = frozenset({"hr", "admin"})


# ---------------------------------------------------------------------------
# Deterministic Calculation & Guardrail Helpers
# ---------------------------------------------------------------------------


def calculate_business_days(start_date: date, end_date: date) -> int:
    """Count inclusive weekdays (Monday-Friday) between start_date and end_date."""
    if end_date < start_date:
        raise ValidationError("end_date cannot be earlier than start_date.")
    if start_date.year != end_date.year:
        raise ValidationError(
            "Leave requests cannot span across calendar years. "
            "Please submit separate requests for each year."
        )

    business_days = 0
    cursor = start_date
    while cursor <= end_date:
        if cursor.weekday() < 5:  # 0=Monday .. 4=Friday
            business_days += 1
        cursor += timedelta(days=1)

    if business_days < 1:
        raise ValidationError(
            "Selected date range must include at least one business day (Mon-Fri)."
        )
    return business_days


def _validate_leave_type(leave_type: str) -> str:
    """Normalize and validate leave_type against supported domain values."""
    normalized = leave_type.strip().lower()
    if normalized not in LEAVE_TYPES:
        raise ValidationError(
            f"Invalid leave_type {leave_type!r}. Must be one of {LEAVE_TYPES}."
        )
    return normalized


def _has_overlapping_request(
    db: Session,
    *,
    tenant_id: str,
    employee_id: str,
    start_date: date,
    end_date: date,
    exclude_request_id: str | None = None,
) -> bool:
    """Return True if an active (pending/approved) leave overlaps the date range."""
    filters = [
        LeaveRequest.tenant_id == tenant_id,
        LeaveRequest.employee_id == employee_id,
        LeaveRequest.status.in_(("pending", "approved")),
        LeaveRequest.start_date <= end_date,
        LeaveRequest.end_date >= start_date,
    ]
    if exclude_request_id is not None:
        filters.append(LeaveRequest.id != exclude_request_id)

    stmt = select(func.count()).select_from(LeaveRequest).where(and_(*filters))
    return int(db.scalar(stmt) or 0) > 0


def _load_entitlement_map(
    db: Session,
    *,
    tenant_id: str,
    employee_id: str,
    year: int,
) -> dict[str, int | None]:
    """Build per-leave-type annual entitlements (DB overrides + defaults)."""
    entitlements: dict[str, int | None] = dict(DEFAULT_ANNUAL_ENTITLEMENTS)

    stmt = select(LeaveEntitlement).where(
        LeaveEntitlement.tenant_id == tenant_id,
        LeaveEntitlement.employee_id == employee_id,
        LeaveEntitlement.year == year,
    )
    for row in db.scalars(stmt).all():
        entitlements[row.leave_type] = row.entitled_days

    return entitlements


def _can_view_employee_leave(
    current_user: SessionUser,
    target_employee_id: str,
) -> bool:
    """Allow employees to view their own records and supervisors to view tenant records."""
    if current_user.user_id == target_employee_id:
        return True
    return current_user.role in LEAVE_APPROVER_ROLES


# ---------------------------------------------------------------------------
# Service Operations
# ---------------------------------------------------------------------------


def get_leave_balance(
    db: Session,
    current_user: SessionUser,
    *,
    employee_id: str | None = None,
    year: int | None = None,
) -> LeaveBalanceResponse:
    """Compute deterministic code-calculated leave balances for an employee."""
    target_employee_id = (employee_id or current_user.user_id).strip()
    target_year = year or utc_now().year

    if not _can_view_employee_leave(current_user, target_employee_id):
        raise ForbiddenError(
            "You are only authorized to view your own leave balances."
        )

    if target_year < 2000 or target_year > 2100:
        raise ValidationError("Year must be between 2000 and 2100.")

    entitlements = _load_entitlement_map(
        db,
        tenant_id=current_user.tenant_id,
        employee_id=target_employee_id,
        year=target_year,
    )

    year_start = date(target_year, 1, 1)
    year_end = date(target_year, 12, 31)

    stmt = select(LeaveRequest).where(
        LeaveRequest.tenant_id == current_user.tenant_id,
        LeaveRequest.employee_id == target_employee_id,
        LeaveRequest.start_date >= year_start,
        LeaveRequest.end_date <= year_end,
        LeaveRequest.status.in_(("approved", "pending")),
    )
    requests = list(db.scalars(stmt).all())

    used_by_type: dict[str, int] = {lt: 0 for lt in LEAVE_TYPES}
    pending_by_type: dict[str, int] = {lt: 0 for lt in LEAVE_TYPES}

    for req in requests:
        if req.status == "approved":
            used_by_type[req.leave_type] += req.business_days
        elif req.status == "pending":
            pending_by_type[req.leave_type] += req.business_days

    balances: list[LeaveTypeBalance] = []
    for lt in LEAVE_TYPES:
        entitled = entitlements.get(lt)
        used = used_by_type[lt]
        pending = pending_by_type[lt]
        remaining = None if entitled is None else max(entitled - used - pending, 0)
        balances.append(
            LeaveTypeBalance(
                leave_type=lt,  # type: ignore[arg-type]
                entitled_days=entitled,
                used_days=used,
                pending_days=pending,
                remaining_days=remaining,
            )
        )

    return LeaveBalanceResponse(
        tenant_id=current_user.tenant_id,
        employee_id=target_employee_id,
        year=target_year,
        balances=balances,
    )


def upsert_leave_entitlement(
    db: Session,
    current_user: SessionUser,
    *,
    employee_id: str,
    year: int,
    leave_type: str,
    entitled_days: int | None,
) -> LeaveEntitlement:
    """Create or update an employee's annual leave entitlement (HR/Admin only)."""
    if current_user.role not in LEAVE_ADMIN_ROLES:
        raise ForbiddenError(
            "Only HR or Admin roles can configure employee leave entitlements."
        )

    normalized_type = _validate_leave_type(leave_type)
    cleaned_employee_id = employee_id.strip()
    if not cleaned_employee_id:
        raise ValidationError("employee_id cannot be blank.")
    if year < 2000 or year > 2100:
        raise ValidationError("Year must be between 2000 and 2100.")
    if entitled_days is not None and entitled_days < 0:
        raise ValidationError("entitled_days cannot be negative.")

    stmt = select(LeaveEntitlement).where(
        LeaveEntitlement.tenant_id == current_user.tenant_id,
        LeaveEntitlement.employee_id == cleaned_employee_id,
        LeaveEntitlement.year == year,
        LeaveEntitlement.leave_type == normalized_type,
    )
    record = db.scalar(stmt)
    if record is None:
        record = LeaveEntitlement(
            tenant_id=current_user.tenant_id,
            employee_id=cleaned_employee_id,
            year=year,
            leave_type=normalized_type,
            entitled_days=entitled_days,
        )
        db.add(record)
    else:
        record.entitled_days = entitled_days

    db.commit()
    db.refresh(record)
    return record


def create_leave_request(
    db: Session,
    current_user: SessionUser,
    *,
    leave_type: str,
    start_date: date,
    end_date: date,
    reason: str,
) -> LeaveRequest:
    """Submit a standard leave request for the authenticated employee."""
    normalized_type = _validate_leave_type(leave_type)
    cleaned_reason = reason.strip()
    if len(cleaned_reason) < 5:
        raise ValidationError("Reason must be at least 5 characters long.")

    business_days = calculate_business_days(start_date, end_date)

    if _has_overlapping_request(
        db,
        tenant_id=current_user.tenant_id,
        employee_id=current_user.user_id,
        start_date=start_date,
        end_date=end_date,
    ):
        raise ConflictError(
            "You already have a pending or approved leave request overlapping these dates."
        )

    balance_summary = get_leave_balance(
        db,
        current_user,
        employee_id=current_user.user_id,
        year=start_date.year,
    )
    type_balance = next(
        item for item in balance_summary.balances if item.leave_type == normalized_type
    )
    if (
        type_balance.remaining_days is not None
        and business_days > type_balance.remaining_days
    ):
        raise ConflictError(
            f"Insufficient '{normalized_type}' leave balance. "
            f"Requested {business_days} business day(s), "
            f"remaining {type_balance.remaining_days} day(s)."
        )

    record = LeaveRequest(
        tenant_id=current_user.tenant_id,
        employee_id=current_user.user_id,
        leave_type=normalized_type,
        start_date=start_date,
        end_date=end_date,
        business_days=business_days,
        reason=cleaned_reason,
        status="pending",
        is_exception=False,
        created_by=current_user.user_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_leave_requests(
    db: Session,
    current_user: SessionUser,
    *,
    employee_id: str | None = None,
    status: str | None = None,
    leave_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[int, list[LeaveRequest]]:
    """List tenant-scoped leave requests visible to the authenticated user."""
    cleaned_employee_id = employee_id.strip() if employee_id else None
    if (
        cleaned_employee_id is not None
        and not _can_view_employee_leave(current_user, cleaned_employee_id)
    ):
        raise ForbiddenError(
            "You are only authorized to view your own leave requests."
        )

    filters = [LeaveRequest.tenant_id == current_user.tenant_id]

    if current_user.role not in LEAVE_APPROVER_ROLES:
        filters.append(LeaveRequest.employee_id == current_user.user_id)
    elif cleaned_employee_id is not None:
        filters.append(LeaveRequest.employee_id == cleaned_employee_id)

    if status is not None:
        normalized_status = status.strip().lower()
        if normalized_status not in LEAVE_STATUSES:
            raise ValidationError(
                f"Invalid status {status!r}. Must be one of {LEAVE_STATUSES}."
            )
        filters.append(LeaveRequest.status == normalized_status)

    if leave_type is not None:
        filters.append(LeaveRequest.leave_type == _validate_leave_type(leave_type))

    total_stmt = select(func.count()).select_from(LeaveRequest).where(*filters)
    total = int(db.scalar(total_stmt) or 0)

    items_stmt = (
        select(LeaveRequest)
        .where(*filters)
        .order_by(LeaveRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = list(db.scalars(items_stmt).all())
    return total, items


def get_leave_request(
    db: Session,
    current_user: SessionUser,
    request_id: str,
) -> LeaveRequest:
    """Fetch a single tenant-scoped leave request visible to the current user."""
    stmt = select(LeaveRequest).where(
        LeaveRequest.id == request_id,
        LeaveRequest.tenant_id == current_user.tenant_id,
    )
    record = db.scalar(stmt)
    if record is None:
        raise NotFoundError("Leave request not found.")

    if not _can_view_employee_leave(current_user, record.employee_id):
        raise NotFoundError("Leave request not found.")

    return record


def decide_leave_request(
    db: Session,
    current_user: SessionUser,
    *,
    request_id: str,
    action: str,
    comment: str | None = None,
) -> LeaveRequest:
    """Approve or reject a pending leave request (non-self Manager/HR/Admin only)."""
    if current_user.role not in LEAVE_APPROVER_ROLES:
        raise ForbiddenError(
            "Only Manager, HR, or Admin roles can approve or reject leave requests."
        )

    normalized_action = action.strip().lower()
    if normalized_action not in {"approve", "reject"}:
        raise ValidationError("Action must be either 'approve' or 'reject'.")

    stmt = select(LeaveRequest).where(
        LeaveRequest.id == request_id,
        LeaveRequest.tenant_id == current_user.tenant_id,
    )
    record = db.scalar(stmt)
    if record is None:
        raise NotFoundError("Leave request not found.")

    if record.employee_id == current_user.user_id:
        raise ForbiddenError(
            "Self-approval or self-rejection of your own leave request is forbidden."
        )

    if record.status != "pending":
        raise ConflictError(
            f"Cannot {normalized_action} a leave request in '{record.status}' status."
        )

    record.status = "approved" if normalized_action == "approve" else "rejected"
    record.decided_by = current_user.user_id
    record.decided_at = utc_now()
    record.decision_comment = comment.strip() if comment else None

    db.commit()
    db.refresh(record)
    return record


def cancel_leave_request(
    db: Session,
    current_user: SessionUser,
    *,
    request_id: str,
) -> LeaveRequest:
    """Cancel a pending leave request (owner or HR/Admin)."""
    stmt = select(LeaveRequest).where(
        LeaveRequest.id == request_id,
        LeaveRequest.tenant_id == current_user.tenant_id,
    )
    record = db.scalar(stmt)
    if record is None:
        raise NotFoundError("Leave request not found.")

    is_owner = record.employee_id == current_user.user_id
    is_admin = current_user.role in LEAVE_ADMIN_ROLES
    if not (is_owner or is_admin):
        raise ForbiddenError(
            "You are not authorized to cancel this leave request."
        )

    if record.status != "pending":
        raise ConflictError(
            f"Only pending leave requests can be cancelled (current status: '{record.status}')."
        )

    record.status = "cancelled"
    db.commit()
    db.refresh(record)
    return record


def create_leave_exception(
    db: Session,
    current_user: SessionUser,
    *,
    employee_id: str,
    leave_type: str,
    start_date: date,
    end_date: date,
    reason: str,
    approval_id: str,
    approved_by: str,
    exception_reason: str,
) -> LeaveRequest:
    """Grant a high-risk `leave.exception` override with fail-closed approval checks.

    Guardrails:
    - Actor must be HR or Admin.
    - Requires explicit `approval_id`, `approved_by`, and `exception_reason`.
    - Forbids self-approval (`approved_by == current_user.user_id`) and
      self-targeted exceptions (`employee_id == current_user.user_id`).
    """
    if current_user.role not in LEAVE_ADMIN_ROLES:
        raise ForbiddenError(
            "Only HR or Admin roles can grant high-risk leave exceptions."
        )

    cleaned_employee_id = employee_id.strip()
    cleaned_reason = reason.strip()
    cleaned_approval_id = approval_id.strip()
    cleaned_approved_by = approved_by.strip()
    cleaned_exception_reason = exception_reason.strip()

    if settings.HIGH_RISK_APPROVAL_REQUIRED:
        if len(cleaned_approval_id) < 4:
            raise ForbiddenError(
                "High-risk action 'leave.exception' requires a valid approval_id."
            )
        if len(cleaned_approved_by) < 2:
            raise ForbiddenError(
                "High-risk action 'leave.exception' requires a valid approved_by."
            )
        if len(cleaned_exception_reason) < 10:
            raise ForbiddenError(
                "High-risk action 'leave.exception' requires a detailed exception_reason."
            )
        if cleaned_approved_by == current_user.user_id:
            raise ForbiddenError(
                "Self-approval is forbidden for high-risk action 'leave.exception'."
            )
        if cleaned_employee_id == current_user.user_id:
            raise ForbiddenError(
                "You cannot grant a leave exception to yourself."
            )

    normalized_type = _validate_leave_type(leave_type)
    business_days = calculate_business_days(start_date, end_date)
    now = utc_now()

    record = LeaveRequest(
        tenant_id=current_user.tenant_id,
        employee_id=cleaned_employee_id,
        leave_type=normalized_type,
        start_date=start_date,
        end_date=end_date,
        business_days=business_days,
        reason=cleaned_reason,
        status="approved",
        is_exception=True,
        created_by=current_user.user_id,
        decided_by=current_user.user_id,
        decided_at=now,
        decision_comment=f"Exception approved ({cleaned_approval_id})",
        approval_id=cleaned_approval_id,
        approved_by=cleaned_approved_by,
        exception_reason=cleaned_exception_reason,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


__all__ = [
    "LEAVE_APPROVER_ROLES",
    "LEAVE_ADMIN_ROLES",
    "calculate_business_days",
    "get_leave_balance",
    "upsert_leave_entitlement",
    "create_leave_request",
    "list_leave_requests",
    "get_leave_request",
    "decide_leave_request",
    "cancel_leave_request",
    "create_leave_exception",
]