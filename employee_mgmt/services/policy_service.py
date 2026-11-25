"""Domain service layer for the Policy Brain feature.

Encapsulates tenant-scoped policy CRUD, deterministic chunking, fail-closed
`policy.publish` approval enforcement, and citation-backed retrieval using
SQLAlchemy 2.0 sessions.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..core.config import settings
from ..db.base import utc_now
from ..models.policy import (
    POLICY_STATUSES,
    POLICY_VISIBILITIES,
    Policy,
    PolicyChunk,
)
from ..schemas import SessionUser
from . import ConflictError, ForbiddenError, NotFoundError, ValidationError

POLICY_ADMIN_ROLES: frozenset[str] = frozenset({"hr", "admin"})

ROLE_ALLOWED_VISIBILITIES: dict[str, frozenset[str]] = {
    "employee": frozenset({"all"}),
    "manager": frozenset({"all", "manager"}),
    "hr": frozenset({"all", "manager", "hr"}),
    "admin": frozenset({"all", "manager", "hr", "admin"}),
}

_TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}")


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------


def _require_policy_admin(current_user: SessionUser) -> None:
    """Ensure only HR or Admin roles can author, publish, or archive policies."""
    if current_user.role not in POLICY_ADMIN_ROLES:
        raise ForbiddenError(
            "Only HR or Admin roles are authorized to manage company policies."
        )


def _allowed_visibilities_for(current_user: SessionUser) -> frozenset[str]:
    """Return the set of policy visibility levels readable by the current user."""
    return ROLE_ALLOWED_VISIBILITIES.get(current_user.role, frozenset({"all"}))


def _tokenize(text: str) -> set[str]:
    """Extract normalized alphanumeric search tokens from text."""
    return set(_TOKEN_PATTERN.findall(text.lower()))


def chunk_policy_text(
    content: str,
    *,
    max_chars: int | None = None,
) -> list[str]:
    """Deterministically split policy content into citation-ready text chunks."""
    limit = max_chars or settings.POLICY_CHUNK_MAX_CHARS
    cleaned = content.strip()
    if not cleaned:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
    chunks: list[str] = []
    current_buffer = ""

    for paragraph in paragraphs:
        if len(paragraph) > limit:
            if current_buffer:
                chunks.append(current_buffer)
                current_buffer = ""
            words = paragraph.split()
            line = ""
            for word in words:
                candidate = f"{line} {word}".strip() if line else word
                if len(candidate) <= limit:
                    line = candidate
                else:
                    if line:
                        chunks.append(line)
                    line = word
            if line:
                chunks.append(line)
            continue

        candidate = (
            f"{current_buffer}\n\n{paragraph}" if current_buffer else paragraph
        )
        if len(candidate) <= limit:
            current_buffer = candidate
        else:
            if current_buffer:
                chunks.append(current_buffer)
            current_buffer = paragraph

    if current_buffer:
        chunks.append(current_buffer)

    return chunks


def _rebuild_policy_chunks(policy: Policy) -> None:
    """Replace a policy's chunks deterministically from its current content."""
    chunk_texts = chunk_policy_text(policy.content)
    policy.chunks.clear()
    for idx, text_segment in enumerate(chunk_texts):
        policy.chunks.append(
            PolicyChunk(
                tenant_id=policy.tenant_id,
                chunk_index=idx,
                text=text_segment,
                embedding=None,
            )
        )


# ---------------------------------------------------------------------------
# Service Operations
# ---------------------------------------------------------------------------


def create_policy_draft(
    db: Session,
    current_user: SessionUser,
    *,
    title: str,
    content: str,
    category: str = "general",
    visibility: str = "all",
    change_summary: str | None = None,
) -> Policy:
    """Create a new tenant-scoped policy draft with deterministic chunks."""
    _require_policy_admin(current_user)

    normalized_visibility = visibility.strip().lower()
    if normalized_visibility not in POLICY_VISIBILITIES:
        raise ValidationError(
            f"Invalid visibility {visibility!r}. Must be one of {POLICY_VISIBILITIES}."
        )

    cleaned_title = title.strip()
    cleaned_content = content.strip()
    cleaned_category = category.strip().lower() or "general"

    if len(cleaned_title) < 3:
        raise ValidationError("Policy title must be at least 3 characters long.")
    if len(cleaned_content) < 20:
        raise ValidationError("Policy content must be at least 20 characters long.")

    policy = Policy(
        tenant_id=current_user.tenant_id,
        title=cleaned_title,
        category=cleaned_category,
        content=cleaned_content,
        visibility=normalized_visibility,
        status="draft",
        version=1,
        created_by=current_user.user_id,
        change_summary=change_summary.strip() if change_summary else None,
    )
    _rebuild_policy_chunks(policy)

    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


def list_policies(
    db: Session,
    current_user: SessionUser,
    *,
    category: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[int, list[Policy]]:
    """List tenant-scoped policies visible to the authenticated user."""
    allowed_visibilities = _allowed_visibilities_for(current_user)
    is_admin = current_user.role in POLICY_ADMIN_ROLES

    filters = [
        Policy.tenant_id == current_user.tenant_id,
        Policy.visibility.in_(allowed_visibilities),
    ]

    if category:
        filters.append(Policy.category == category.strip().lower())

    if status:
        normalized_status = status.strip().lower()
        if normalized_status not in POLICY_STATUSES:
            raise ValidationError(
                f"Invalid status {status!r}. Must be one of {POLICY_STATUSES}."
            )
        if not is_admin and normalized_status != "published":
            raise ForbiddenError(
                "Only HR or Admin roles can view draft or archived policies."
            )
        filters.append(Policy.status == normalized_status)
    elif not is_admin:
        filters.append(Policy.status == "published")

    total_stmt = select(func.count()).select_from(Policy).where(*filters)
    total = int(db.scalar(total_stmt) or 0)

    items_stmt = (
        select(Policy)
        .options(selectinload(Policy.chunks))
        .where(*filters)
        .order_by(Policy.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = list(db.scalars(items_stmt).all())
    return total, items


def get_policy(
    db: Session,
    current_user: SessionUser,
    policy_id: str,
) -> Policy:
    """Fetch a single policy if it is within the user's tenant and visibility."""
    stmt = (
        select(Policy)
        .options(selectinload(Policy.chunks))
        .where(
            Policy.id == policy_id,
            Policy.tenant_id == current_user.tenant_id,
        )
    )
    policy = db.scalar(stmt)
    if policy is None:
        raise NotFoundError("Policy not found.")

    allowed_visibilities = _allowed_visibilities_for(current_user)
    if policy.visibility not in allowed_visibilities:
        raise NotFoundError("Policy not found.")

    if policy.status != "published" and current_user.role not in POLICY_ADMIN_ROLES:
        raise NotFoundError("Policy not found.")

    return policy


def publish_policy(
    db: Session,
    current_user: SessionUser,
    *,
    policy_id: str,
    approval_id: str,
    approved_by: str,
    change_summary: str | None = None,
) -> Policy:
    """Publish a policy with fail-closed high-risk approval enforcement.

    Enforces `policy.publish` guardrails:
    - Actor must be HR or Admin.
    - Explicit `approval_id` and `approved_by` are required.
    - Self-approval (`approved_by == current_user.user_id`) is forbidden.
    """
    _require_policy_admin(current_user)

    cleaned_approval_id = approval_id.strip()
    cleaned_approved_by = approved_by.strip()

    if settings.HIGH_RISK_APPROVAL_REQUIRED:
        if len(cleaned_approval_id) < 4:
            raise ForbiddenError(
                "High-risk action 'policy.publish' requires a valid approval_id."
            )
        if len(cleaned_approved_by) < 2:
            raise ForbiddenError(
                "High-risk action 'policy.publish' requires a valid approved_by."
            )
        if cleaned_approved_by == current_user.user_id:
            raise ForbiddenError(
                "Self-approval is forbidden for high-risk action 'policy.publish'."
            )

    stmt = (
        select(Policy)
        .options(selectinload(Policy.chunks))
        .where(
            Policy.id == policy_id,
            Policy.tenant_id == current_user.tenant_id,
        )
    )
    policy = db.scalar(stmt)
    if policy is None:
        raise NotFoundError("Policy not found.")

    if policy.status == "archived":
        raise ConflictError("Archived policies cannot be published directly.")

    if policy.status == "published":
        policy.version += 1

    policy.status = "published"
    policy.published_at = utc_now()
    policy.published_by = current_user.user_id
    policy.approval_id = cleaned_approval_id
    policy.approved_by = cleaned_approved_by
    if change_summary is not None:
        policy.change_summary = change_summary.strip() or policy.change_summary

    _rebuild_policy_chunks(policy)

    db.commit()
    db.refresh(policy)
    return policy


def archive_policy(
    db: Session,
    current_user: SessionUser,
    policy_id: str,
) -> Policy:
    """Archive a tenant-scoped policy (HR/Admin only)."""
    _require_policy_admin(current_user)

    stmt = select(Policy).where(
        Policy.id == policy_id,
        Policy.tenant_id == current_user.tenant_id,
    )
    policy = db.scalar(stmt)
    if policy is None:
        raise NotFoundError("Policy not found.")

    if policy.status == "archived":
        raise ConflictError("Policy is already archived.")

    policy.status = "archived"
    db.commit()
    db.refresh(policy)
    return policy


def search_policy_chunks(
    db: Session,
    current_user: SessionUser,
    *,
    query: str,
    category: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Retrieve citation-backed chunks from published policies visible to the user."""
    query_tokens = _tokenize(query)
    if not query_tokens:
        raise ValidationError(
            "Search query must contain at least one meaningful keyword."
        )

    allowed_visibilities = _allowed_visibilities_for(current_user)
    filters = [
        Policy.tenant_id == current_user.tenant_id,
        Policy.status == "published",
        Policy.visibility.in_(allowed_visibilities),
    ]
    if category:
        filters.append(Policy.category == category.strip().lower())

    stmt = (
        select(PolicyChunk, Policy)
        .join(Policy, PolicyChunk.policy_id == Policy.id)
        .where(*filters)
    )
    rows = db.execute(stmt).all()

    scored_results: list[dict[str, Any]] = []
    for chunk, policy in rows:
        chunk_tokens = _tokenize(f"{policy.title} {chunk.text}")
        overlap = query_tokens.intersection(chunk_tokens)
        if not overlap:
            continue

        score = round(len(overlap) / len(query_tokens), 4)
        scored_results.append(
            {
                "policy_id": policy.id,
                "policy_title": policy.title,
                "category": policy.category,
                "version": policy.version,
                "chunk_id": chunk.id,
                "chunk_index": chunk.chunk_index,
                "excerpt": chunk.text,
                "score": score,
            }
        )

    scored_results.sort(
        key=lambda item: (item["score"], item["version"]),
        reverse=True,
    )
    return scored_results[: max(1, min(limit, 20))]


__all__ = [
    "POLICY_ADMIN_ROLES",
    "ROLE_ALLOWED_VISIBILITIES",
    "chunk_policy_text",
    "create_policy_draft",
    "list_policies",
    "get_policy",
    "publish_policy",
    "archive_policy",
    "search_policy_chunks",
]