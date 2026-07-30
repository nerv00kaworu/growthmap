"""Entry-point-neutral canonical node updates.

Wire parsing, authorization, project/entity CAS, idempotency, transaction commit and
response shaping remain adapter responsibilities.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy import null
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import ActionLog, Node
from services.maturity import MATURITY_ORDER, auto_advance_maturity
from services.revisions import TouchedEntities

SHARED_UPDATE_FIELDS = frozenset({
    "title", "summary", "status", "maturity", "priority", "confidence",
    "description", "rules_text", "constraints_text", "examples_text",
    "questions_text", "decision_notes", "tags", "workflow_status", "file_paths",
})
GUI_UPDATE_FIELDS = frozenset({"node_type", "position_x", "position_y"})
_TEXT_LIMITS = {"title": 500, "summary": 500, **{key: 16_384 for key in (
    "description", "rules_text", "constraints_text", "examples_text",
    "questions_text", "decision_notes")}}
_ENUMS = {
    "status": {"active", "paused", "archived", "completed"},
    "maturity": set(MATURITY_ORDER),
    "workflow_status": {"draft", "review", "approved", "archived"},
    "node_type": {"idea", "concept", "task", "question", "decision", "risk",
                  "resource", "note", "module", "spec"},
}

@dataclass(frozen=True)
class UpdateNodeInput:
    project_id: str
    node_id: str
    changes: dict[str, Any]
    actor_type: str
    actor_id: str | None
    last_edited_by: str
    provenance: dict[str, Any] = field(default_factory=dict)
    adapter_changes: dict[str, Any] = field(default_factory=dict)

@dataclass
class ValidatedUpdateNode:
    data: UpdateNodeInput
    node: Node
    changes: dict[str, Any]
    adapter_changes: dict[str, Any]


def _invalid(message: str) -> None:
    raise HTTPException(422, {"code": "INVALID_NODE_UPDATE", "message": message})


def _validate_changes(changes: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    unknown = set(changes) - allowed
    if unknown: _invalid(f"Unknown or immutable fields: {', '.join(sorted(unknown))}")
    for key, value in changes.items():
        if value is None: _invalid(f"{key} cannot be null; omit it to leave unchanged")
        if key in _TEXT_LIMITS:
            if not isinstance(value, str) or len(value) > _TEXT_LIMITS[key]: _invalid(f"{key} is invalid")
            if key == "title" and not value.strip(): _invalid("title cannot be blank")
        elif key in _ENUMS and value not in _ENUMS[key]: _invalid(f"{key} is invalid")
        elif key == "priority" and (type(value) is not int or not -100 <= value <= 100): _invalid("priority is invalid")
        elif key == "confidence" and (isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1): _invalid("confidence is invalid")
        elif key in {"position_x", "position_y"} and (isinstance(value, bool) or not isinstance(value, (int, float))): _invalid(f"{key} is invalid")
        elif key in {"tags", "file_paths"}:
            limit, item_limit = ((50, 100) if key == "tags" else (100, 1024))
            if not isinstance(value, list) or len(value) > limit or any(not isinstance(x, str) or len(x) > item_limit for x in value):
                _invalid(f"{key} is invalid")
    return deepcopy(changes)


async def validate_update_node(db: AsyncSession, data: UpdateNodeInput) -> ValidatedUpdateNode:
    if not data.changes and not data.adapter_changes: _invalid("update_node fields cannot be empty")
    node = await db.get(Node, data.node_id)
    if not node: raise HTTPException(404, "Node not found")
    if node.project_id != data.project_id:
        raise HTTPException(422, {"code": "INVALID_REFERENCE", "message": "Node must exist in project"})
    changes = _validate_changes(data.changes, SHARED_UPDATE_FIELDS)
    adapter_changes = _validate_changes(data.adapter_changes, GUI_UPDATE_FIELDS)
    if "title" in changes: changes["title"] = changes["title"].strip()
    return ValidatedUpdateNode(data, node, changes, adapter_changes)


async def apply_update_node(db: AsyncSession, validated: ValidatedUpdateNode, *,
                            touched: TouchedEntities, defer_maturity: bool = False) -> Node:
    node, data = validated.node, validated.data
    for key, value in {**validated.changes, **validated.adapter_changes}.items():
        setattr(node, key, deepcopy(value))
    node.last_edited_by = data.last_edited_by
    touched.add(node)
    payload: dict[str, Any] = {"changes": deepcopy({**validated.changes, **validated.adapter_changes})}
    if data.provenance: payload["provenance"] = deepcopy(data.provenance)
    db.add(ActionLog(project_id=data.project_id, node_id=node.id,
                     actor_type=data.actor_type,
                     # Column has a legacy empty-string default; SQL NULL keeps
                     # GUI's deliberately anonymous actor identity distinguishable.
                     actor_id=data.actor_id if data.actor_id is not None else null(),
                     action_type="update_node", payload=payload))
    if not defer_maturity and "maturity" not in validated.changes:
        await auto_advance_maturity(node.id, db, touched=touched)
    return node


async def finalize_update_maturity(db: AsyncSession, node_ids: set[str], *,
                                   manual_maturity_node_ids: set[str],
                                   touched: TouchedEntities) -> None:
    """Evaluate once after all staged batch fields; any manual maturity wins."""
    for node_id in node_ids - manual_maturity_node_ids:
        await auto_advance_maturity(node_id, db, touched=touched)
