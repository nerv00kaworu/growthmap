"""Shared transactional optimistic-concurrency primitives for canonical mutations.

`claim_project_revision` is an atomic compare-and-swap.  On SQLite the UPDATE also
serializes competing writers, so independent connections never pass the same
project revision.  Callers must keep the claim, entity checks, canonical writes,
action log, and final commit in one AsyncSession transaction.
"""
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from models.models import Project


def revision_conflict(*, entity: str, entity_id: str, expected: int, current: int | None):
    raise HTTPException(409, {"code": "REVISION_CONFLICT", "entity": entity,
                              "entity_id": entity_id, "expected": expected,
                              "current": current})


async def claim_project_revision(db: AsyncSession, project_id: str, expected: int) -> Project:
    """Atomically claim expected revision and increment project exactly once."""
    result = await db.execute(
        update(Project).where(Project.id == project_id, Project.revision == expected)
        .values(revision=Project.revision + 1, updated_at=datetime.now(timezone.utc))
    )
    if result.rowcount != 1:
        await db.rollback()
        current = await db.get(Project, project_id)
        if not current:
            raise HTTPException(404, "Project not found")
        revision_conflict(entity="project", entity_id=project_id,
                          expected=expected, current=current.revision)
    # SQLAlchemy synchronizes matching identity-map objects for this ORM UPDATE.
    # Do not expire the whole map: callers deliberately loaded target entities
    # before claiming, and implicit async lazy reload would raise MissingGreenlet.
    project = await db.get(Project, project_id)
    assert project is not None
    return project


def check_entity_revision(entity, expected: int, *, kind: str | None = None) -> None:
    current = entity.revision or 1
    if expected != current:
        revision_conflict(entity=kind or entity.__class__.__name__.lower(),
                          entity_id=str(entity.id), expected=expected, current=current)


def bump_existing(*entities) -> None:
    """Increment each touched pre-existing revision once (deduplicated by type/id)."""
    seen: set[tuple[type, str]] = set()
    for entity in entities:
        if entity is None:
            continue
        key = (type(entity), str(entity.id))
        if key in seen:
            continue
        seen.add(key)
        entity.revision = (entity.revision or 1) + 1
