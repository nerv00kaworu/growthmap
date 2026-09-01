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
from models.revisions import MAX_SAFE_REVISION


def revision_conflict(*, entity: str, entity_id: str, expected: int, current: int | None):
    raise HTTPException(409, {"code": "REVISION_CONFLICT", "entity": entity,
                              "entity_id": entity_id, "expected": expected,
                              "current": current})


async def claim_project_revision(db: AsyncSession, project_id: str, expected: int) -> Project:
    """Atomically claim expected revision and increment project exactly once."""
    result = await db.execute(
        update(Project).where(Project.id == project_id, Project.revision == expected, Project.revision < MAX_SAFE_REVISION)
        .values(revision=Project.revision + 1, updated_at=datetime.now(timezone.utc))
    )
    if result.rowcount != 1:
        await db.rollback()
        current = await db.get(Project, project_id)
        if not current:
            raise HTTPException(404, "Project not found")
        if current.revision >= MAX_SAFE_REVISION:
            raise HTTPException(409, {"code":"REVISION_EXHAUSTED","entity":"project","entity_id":project_id,"current":current.revision})
        revision_conflict(entity="project", entity_id=project_id,
                          expected=expected, current=current.revision)
    # SQLAlchemy synchronizes matching identity-map objects for this ORM UPDATE.
    # Do not expire the whole map: callers deliberately loaded target entities
    # before claiming, and implicit async lazy reload would raise MissingGreenlet.
    project = await db.get(Project, project_id)
    assert project is not None
    return project


def check_entity_revision(entity, expected: int, *, kind: str | None = None) -> None:
    current = entity.revision
    entity_kind = kind or entity.__class__.__name__.lower()
    if expected != current:
        revision_conflict(entity=entity_kind, entity_id=str(entity.id), expected=expected, current=current)
    if not isinstance(current, int) or isinstance(current, bool) or current >= MAX_SAFE_REVISION:
        raise HTTPException(409, {"code": "REVISION_EXHAUSTED", "entity": entity_kind,
                                  "entity_id": str(entity.id), "current": current})


class TouchedEntities:
    """Transaction-local collector that bumps every existing canonical row once.

    Routes add rows whenever their canonical state or owned relationship changes.
    Applying at the end avoids accidental double bumps when helpers overlap.
    """
    def __init__(self) -> None:
        self._entities: dict[tuple[type, str], object] = {}

    def add(self, *entities) -> None:
        for entity in entities:
            if entity is not None:
                self._entities[(type(entity), str(entity.id))] = entity

    def apply(self) -> None:
        # Preflight the complete unique set before changing the first object.
        # This keeps multi-entity mutations atomic even before session rollback.
        for entity in self._entities.values():
            current = entity.revision
            if not isinstance(current, int) or isinstance(current, bool) or current >= MAX_SAFE_REVISION:
                raise HTTPException(409, {"code": "REVISION_EXHAUSTED",
                    "entity": entity.__class__.__name__.lower(),
                    "entity_id": str(entity.id), "current": current})
        for entity in self._entities.values():
            entity.revision += 1


def bump_existing(*entities) -> None:
    """Compatibility wrapper; prefer one TouchedEntities collector per route."""
    touched = TouchedEntities()
    touched.add(*entities)
    touched.apply()
