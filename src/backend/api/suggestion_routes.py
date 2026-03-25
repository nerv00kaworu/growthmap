"""Suggestion management API routes."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from models.schemas import SuggestionCreate, SuggestionOut, SuggestionUpdate
from services.exceptions import NotFoundError, ValidationError
from services.suggestion_service import (
    batch_review as batch_review_service,
    create_suggestion as create_suggestion_service,
    delete_suggestion as delete_suggestion_service,
    get_suggestion as get_suggestion_service,
    list_suggestions as list_suggestions_service,
    review_suggestion as review_suggestion_service,
)

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


class BatchReviewRequest(BaseModel):
    suggestion_ids: list[str]
    status: str  # "approved" or "rejected"
    reviewed_by: str | None = None


def _handle_service_error(exc: Exception) -> None:
    if isinstance(exc, NotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, ValidationError):
        raise HTTPException(422, str(exc)) from exc
    raise exc


@router.post("", response_model=SuggestionOut, status_code=201)
async def create_suggestion(data: SuggestionCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await create_suggestion_service(db, data)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.get("", response_model=list[SuggestionOut])
async def list_suggestions(
    project_id: str,
    status: str | None = None,
    node_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await list_suggestions_service(db, project_id, status=status, node_id=node_id)


@router.get("/{suggestion_id}", response_model=SuggestionOut)
async def get_suggestion(suggestion_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await get_suggestion_service(db, suggestion_id)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.patch("/{suggestion_id}", response_model=SuggestionOut)
async def review_suggestion(
    suggestion_id: str, data: SuggestionUpdate, db: AsyncSession = Depends(get_db)
):
    try:
        return await review_suggestion_service(db, suggestion_id, data)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.post("/batch-review", response_model=list[SuggestionOut])
async def batch_review(data: BatchReviewRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await batch_review_service(
            db, data.suggestion_ids, data.status, data.reviewed_by
        )
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.delete("/{suggestion_id}", status_code=204)
async def delete_suggestion(suggestion_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await delete_suggestion_service(db, suggestion_id)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)
