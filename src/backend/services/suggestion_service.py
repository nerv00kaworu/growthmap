"""Suggestion service-layer business logic."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Node, Project, Suggestion
from models.schemas import SuggestionCreate, SuggestionUpdate
from services.exceptions import NotFoundError, ValidationError

VALID_STATUSES = {"pending", "approved", "rejected", "applied"}
REVIEWABLE_STATUSES = {"approved", "rejected"}


async def create_suggestion(db: AsyncSession, data: SuggestionCreate) -> Suggestion:
    """Create a new suggestion, validating project and node exist."""
    project = await db.get(Project, data.project_id)
    if not project:
        raise NotFoundError("Project not found")

    node = await db.get(Node, data.target_node_id)
    if not node:
        raise NotFoundError("Target node not found")
    if node.project_id != data.project_id:
        raise ValidationError("Target node does not belong to the specified project")

    suggestion = Suggestion(
        project_id=data.project_id,
        target_node_id=data.target_node_id,
        action_type=data.action_type,
        payload=data.payload,
        provider_id=data.provider_id or "",
        provider_model=data.provider_model or "",
        cost_estimate=data.cost_estimate or 0,
    )
    db.add(suggestion)
    await db.commit()
    await db.refresh(suggestion)
    return suggestion


async def list_suggestions(
    db: AsyncSession,
    project_id: str,
    status: str | None = None,
    node_id: str | None = None,
) -> list[Suggestion]:
    """List suggestions for a project with optional filters."""
    query = select(Suggestion).where(Suggestion.project_id == project_id)
    if status:
        query = query.where(Suggestion.status == status)
    if node_id:
        query = query.where(Suggestion.target_node_id == node_id)
    query = query.order_by(Suggestion.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_suggestion(db: AsyncSession, suggestion_id: str) -> Suggestion:
    """Get a single suggestion by ID."""
    suggestion = await db.get(Suggestion, suggestion_id)
    if not suggestion:
        raise NotFoundError("Suggestion not found")
    return suggestion


async def review_suggestion(
    db: AsyncSession, suggestion_id: str, data: SuggestionUpdate
) -> Suggestion:
    """Review a suggestion (approve/reject). Only pending suggestions can be reviewed."""
    suggestion = await get_suggestion(db, suggestion_id)

    if suggestion.status != "pending":
        raise ValidationError(
            f"Cannot review suggestion with status '{suggestion.status}'; only pending suggestions can be reviewed"
        )

    if data.status and data.status not in REVIEWABLE_STATUSES:
        raise ValidationError(
            f"Invalid review status '{data.status}'; must be 'approved' or 'rejected'"
        )

    if data.status:
        suggestion.status = data.status
    if data.reviewed_by is not None:
        suggestion.reviewed_by = data.reviewed_by
    suggestion.reviewed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(suggestion)
    return suggestion


async def batch_review(
    db: AsyncSession,
    suggestion_ids: list[str],
    status: str,
    reviewed_by: str | None = None,
) -> list[Suggestion]:
    """Batch review multiple suggestions. All must be pending."""
    if status not in REVIEWABLE_STATUSES:
        raise ValidationError(
            f"Invalid review status '{status}'; must be 'approved' or 'rejected'"
        )

    if not suggestion_ids:
        raise ValidationError("No suggestion IDs provided")

    suggestions = []
    for sid in suggestion_ids:
        suggestion = await db.get(Suggestion, sid)
        if not suggestion:
            raise NotFoundError(f"Suggestion '{sid}' not found")
        if suggestion.status != "pending":
            raise ValidationError(
                f"Suggestion '{sid}' has status '{suggestion.status}'; only pending suggestions can be reviewed"
            )
        suggestions.append(suggestion)

    now = datetime.now(timezone.utc)
    for suggestion in suggestions:
        suggestion.status = status
        suggestion.reviewed_at = now
        if reviewed_by is not None:
            suggestion.reviewed_by = reviewed_by

    await db.commit()
    for suggestion in suggestions:
        await db.refresh(suggestion)
    return suggestions


async def delete_suggestion(db: AsyncSession, suggestion_id: str) -> None:
    """Delete a suggestion."""
    suggestion = await get_suggestion(db, suggestion_id)
    await db.delete(suggestion)
    await db.commit()
