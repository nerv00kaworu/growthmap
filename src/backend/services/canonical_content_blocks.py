"""Entry-point-neutral canonical content-block creation.

Adapters retain authorization, wire vocabulary/bounds, CAS, idempotency,
transaction and commit ownership. This service validates canonical references,
stages the block and sanitized per-block history, and registers its owner touch.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import ActionLog, ContentBlock, Node
from services.maturity import auto_advance_maturity
from services.revisions import TouchedEntities


@dataclass(frozen=True)
class CreateContentBlockInput:
    project_id: str
    node_id: str
    block_id: str | None
    block_type: str
    content: Any
    order_index: int
    actor_type: str
    actor_id: str | None
    created_by: str
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidatedCreateContentBlock:
    data: CreateContentBlockInput
    node: Node


def _safe_provenance(value: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("entry", "operation_index"):
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)) and len(str(item)) <= 128:
            out[key] = item
    return out


async def validate_create_content_block(
    db: AsyncSession, data: CreateContentBlockInput
) -> ValidatedCreateContentBlock:
    node = await db.get(Node, data.node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    if node.project_id != data.project_id:
        raise HTTPException(422, {"code": "INVALID_REFERENCE", "message": "Owner node must exist in project"})
    if data.block_id and await db.get(ContentBlock, data.block_id):
        raise HTTPException(409, {"code": "ID_CONFLICT", "message": "Entity id already exists"})
    return ValidatedCreateContentBlock(data, node)


async def apply_create_content_block(
    db: AsyncSession,
    validated: ValidatedCreateContentBlock,
    *,
    touched: TouchedEntities,
    touch_owner_ids: set[str] | None = None,
) -> ContentBlock:
    """Stage one block and safe history; never claims CAS or commits."""
    d = validated.data
    block = ContentBlock(
        id=d.block_id, node_id=d.node_id, block_type=d.block_type,
        content=deepcopy(d.content), order_index=d.order_index,
        created_by=d.created_by, revision=1,
    )
    db.add(block)
    await db.flush()
    if touch_owner_ids is None or validated.node.id in touch_owner_ids:
        touched.add(validated.node)
    payload: dict[str, Any] = {
        "block_id": block.id,
        "node_id": block.node_id,
        "block_type": block.block_type,
        "order_index": block.order_index,
    }
    if isinstance(d.content, dict):
        payload["content_shape"] = "object"
        payload["content_key_count"] = len(d.content)
    elif isinstance(d.content, list):
        payload["content_shape"] = "array"
        payload["content_item_count"] = len(d.content)
    elif d.content is None:
        payload["content_shape"] = "null"
    else:
        payload["content_shape"] = type(d.content).__name__
    provenance = _safe_provenance(d.provenance)
    if provenance:
        payload["provenance"] = provenance
    db.add(ActionLog(
        project_id=d.project_id, node_id=d.node_id, actor_type=d.actor_type,
        actor_id=d.actor_id,
        action_type="create_content_block", payload=payload,
    ))
    await db.flush()
    return block


async def finalize_content_block_maturity(
    db: AsyncSession, node_ids: set[str], *, touched: TouchedEntities
) -> None:
    """Evaluate owner maturity once all transaction-local blocks are visible."""
    for node_id in node_ids:
        await auto_advance_maturity(node_id, db, touched=touched)
