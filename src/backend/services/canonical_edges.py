"""Entry-point-neutral canonical edge creation and metadata updates.

Adapters own authorization, vocabulary/field bounds, project/entity CAS,
idempotency, commit and rollback. This module owns canonical validation, rows,
touches and sanitized per-edge history.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy import null, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import ActionLog, Edge, Node
from services.revisions import TouchedEntities


@dataclass(frozen=True)
class CreateEdgeInput:
    project_id: str
    edge_id: str | None
    from_node_id: str
    to_node_id: str
    relation_type: str
    weight: float = 1.0
    note: str = ""
    is_mainline: bool = False
    actor_type: str = "human"
    actor_id: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidatedCreateEdge:
    data: CreateEdgeInput
    from_node: Node
    to_node: Node


@dataclass(frozen=True)
class UpdateEdgeInput:
    project_id: str
    edge_id: str
    changes: dict[str, Any]
    actor_type: str = "human"
    actor_id: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidatedUpdateEdge:
    data: UpdateEdgeInput
    edge: Edge
    changes: dict[str, Any]


@dataclass(frozen=True)
class DeleteEdgeInput:
    project_id: str
    edge_id: str
    actor_type: str = "human"
    actor_id: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidatedDeleteEdge:
    data: DeleteEdgeInput
    edge: Edge


@dataclass(frozen=True)
class PromoteMainlineInput:
    project_id: str
    edge_id: str
    expected_revision: int
    expected_sibling_revisions: dict[str, int]
    actor_type: str = "human"
    actor_id: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidatedPromoteMainline:
    data: PromoteMainlineInput
    edge: Edge
    mainline_siblings: list[Edge]
    endpoint_nodes: list[Node]


def _revision_conflict(message: str, **extra: Any) -> None:
    raise HTTPException(409, {"code": "REVISION_CONFLICT", "message": message, **extra})


def _safe_provenance(value: dict[str, Any]) -> dict[str, Any]:
    """Small explicit allowlist: history must never become a secret sink."""
    out: dict[str, Any] = {}
    for key in ("entry", "operation_index"):
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)) and len(str(item)) <= 128:
            out[key] = item
    return out


async def validate_create_edge(
    db: AsyncSession, data: CreateEdgeInput, *, allowed_relation_types: set[str]
) -> ValidatedCreateEdge:
    if data.relation_type not in allowed_relation_types:
        raise HTTPException(422, {"code": "UNSUPPORTED_RELATION", "message": "Unsupported relation type"})
    from_node = await db.get(Node, data.from_node_id)
    to_node = await db.get(Node, data.to_node_id)
    if not from_node or not to_node:
        raise HTTPException(422, {"code": "INVALID_REFERENCE", "message": "Edge endpoint does not exist"})
    if from_node.project_id != data.project_id or to_node.project_id != data.project_id:
        raise HTTPException(422, {"code": "INVALID_REFERENCE", "message": "Endpoints must exist in project"})
    if data.from_node_id == data.to_node_id:
        raise HTTPException(422, {"code": "SELF_RELATION", "message": "Cannot create a self-relation"})
    duplicate = await db.scalar(select(Edge.id).where(
        Edge.from_node_id == data.from_node_id,
        Edge.to_node_id == data.to_node_id,
        Edge.relation_type == data.relation_type,
    ))
    if duplicate:
        raise HTTPException(409, {"code": "DUPLICATE_RELATION", "message": "Duplicate relation"})
    if data.edge_id and await db.get(Edge, data.edge_id):
        raise HTTPException(409, {"code": "ID_CONFLICT", "message": "Entity id already exists"})
    if data.relation_type == "child_of" and (from_node.branch_id or None) != (to_node.branch_id or None):
        raise HTTPException(422, {"code": "BRANCH_MISMATCH", "message": "Containment endpoints must share branch"})
    return ValidatedCreateEdge(data, from_node, to_node)


async def apply_create_edge(
    db: AsyncSession,
    validated: ValidatedCreateEdge,
    *,
    touched: TouchedEntities,
    touch_endpoint_ids: set[str] | None = None,
) -> tuple[Edge, list[Edge]]:
    """Stage one edge and log; never commits or claims project CAS.

    ``touch_endpoint_ids`` identifies rows which predated an atomic batch.  GUI
    omits it (both endpoints necessarily pre-exist); Agent passes its snapshot so
    forward-created nodes remain revision 1.
    """
    d = validated.data
    siblings: list[Edge] = []
    if d.is_mainline and d.relation_type == "child_of":
        siblings = list((await db.execute(select(Edge).where(
            Edge.project_id == d.project_id,
            Edge.from_node_id == d.from_node_id,
            Edge.relation_type == "child_of",
            Edge.is_mainline == True,
        ))).scalars())
        for sibling in siblings:
            sibling.is_mainline = False
        touched.add(*siblings)

    edge = Edge(id=d.edge_id, project_id=d.project_id,
                from_node_id=d.from_node_id, to_node_id=d.to_node_id,
                relation_type=d.relation_type, weight=d.weight, note=d.note,
                is_mainline=bool(d.is_mainline and d.relation_type == "child_of"), revision=1)
    db.add(edge)
    await db.flush()
    eligible = touch_endpoint_ids
    if eligible is None or validated.from_node.id in eligible:
        touched.add(validated.from_node)
    if eligible is None or validated.to_node.id in eligible:
        touched.add(validated.to_node)
    payload: dict[str, Any] = {
        "edge_id": edge.id,
        "from_node_id": edge.from_node_id,
        "to_node_id": edge.to_node_id,
        "relation_type": edge.relation_type,
        "weight": edge.weight,
        "is_mainline": edge.is_mainline,
    }
    provenance = _safe_provenance(d.provenance)
    if provenance:
        payload["provenance"] = provenance
    db.add(ActionLog(project_id=d.project_id, node_id=edge.from_node_id,
                     actor_type=d.actor_type,
                     actor_id=d.actor_id if d.actor_id is not None else null(),
                     action_type="graph_relation_created", payload=payload))
    return edge, siblings


async def validate_update_edge(db: AsyncSession, data: UpdateEdgeInput) -> ValidatedUpdateEdge:
    edge = await db.get(Edge, data.edge_id)
    if not edge:
        raise HTTPException(404, "Edge not found")
    if edge.project_id != data.project_id:
        raise HTTPException(404, "Edge not found")
    if edge.relation_type == "child_of":
        raise HTTPException(400, "Tree parent relations cannot be edited as graph relations")
    changes = deepcopy(data.changes)
    if not changes:
        raise HTTPException(400, "No edge fields provided")
    unknown = sorted(set(changes) - {"weight", "note"})
    if unknown:
        raise HTTPException(422, {"code": "INVALID_EDGE_UPDATE", "message": "Only weight and note may be updated", "fields": unknown})
    return ValidatedUpdateEdge(data=data, edge=edge, changes=changes)


async def apply_update_edge(
    db: AsyncSession, validated: ValidatedUpdateEdge, *, touched: TouchedEntities
) -> Edge:
    d, edge = validated.data, validated.edge
    for key, value in validated.changes.items():
        setattr(edge, key, deepcopy(value))
    touched.add(edge)
    payload: dict[str, Any] = {
        "edge_id": edge.id,
        "from_node_id": edge.from_node_id,
        "to_node_id": edge.to_node_id,
        "changed_fields": sorted(validated.changes),
    }
    provenance = _safe_provenance(d.provenance)
    if provenance:
        payload["provenance"] = provenance
    db.add(ActionLog(project_id=d.project_id, node_id=edge.from_node_id,
                     actor_type=d.actor_type,
                     actor_id=d.actor_id if d.actor_id is not None else null(),
                     action_type="graph_relation_updated", payload=payload))
    await db.flush()
    return edge


async def validate_delete_edge(db: AsyncSession, data: DeleteEdgeInput) -> ValidatedDeleteEdge:
    edge = await db.get(Edge, data.edge_id)
    if not edge or edge.project_id != data.project_id:
        raise HTTPException(404, "Edge not found")
    if edge.relation_type == "child_of":
        raise HTTPException(400, "Tree parent relations must be changed through node move actions")
    return ValidatedDeleteEdge(data=data, edge=edge)


async def validate_promote_mainline(
    db: AsyncSession, data: PromoteMainlineInput
) -> ValidatedPromoteMainline:
    edge = await db.get(Edge, data.edge_id)
    if not edge or edge.project_id != data.project_id:
        raise HTTPException(404, "Edge not found")
    if edge.relation_type != "child_of":
        raise HTTPException(422, {"code": "INVALID_MAINLINE_TARGET", "message": "Only existing child_of edges can be promoted"})
    if data.expected_revision != (edge.revision or 1):
        _revision_conflict("Target edge revision is stale", entity_id=edge.id,
                           expected=data.expected_revision, current=edge.revision or 1)
    siblings = list((await db.execute(select(Edge).where(
        Edge.project_id == data.project_id,
        Edge.from_node_id == edge.from_node_id,
        Edge.relation_type == "child_of",
        Edge.is_mainline == True,
        Edge.id != edge.id,
    ).order_by(Edge.id))).scalars())
    authoritative = {str(s.id): s.revision or 1 for s in siblings}
    if data.expected_sibling_revisions != authoritative:
        _revision_conflict("Mainline sibling revision union is stale",
                           expected_sibling_revisions=data.expected_sibling_revisions,
                           current_sibling_revisions=authoritative)
    endpoint_ids = {edge.from_node_id, edge.to_node_id}
    for sibling in siblings:
        endpoint_ids.update((sibling.from_node_id, sibling.to_node_id))
    nodes = list((await db.execute(select(Node).where(
        Node.project_id == data.project_id, Node.id.in_(endpoint_ids)
    ))).scalars())
    if {n.id for n in nodes} != endpoint_ids:
        raise HTTPException(409, {"code": "INVALID_GRAPH_SCOPE", "message": "Containment endpoint is missing or cross-project"})
    return ValidatedPromoteMainline(data, edge, siblings, nodes)


async def apply_promote_mainline(
    db: AsyncSession, validated: ValidatedPromoteMainline, *, touched: TouchedEntities
) -> tuple[Edge, list[Edge]]:
    """Stage promotion, persisted endpoint touches and IDs-only history."""
    d, edge = validated.data, validated.edge
    for sibling in validated.mainline_siblings:
        sibling.is_mainline = False
    # SQLite's uniqueness trigger is row-ordered; persist demotions before the
    # target promotion while retaining one surrounding transaction.
    if validated.mainline_siblings:
        await db.flush(validated.mainline_siblings)
    edge.is_mainline = True
    touched.add(edge, *validated.mainline_siblings)
    payload: dict[str, Any] = {
        "edge_id": edge.id,
        "parent_node_id": edge.from_node_id,
        "child_node_id": edge.to_node_id,
        "demoted_edge_ids": [s.id for s in validated.mainline_siblings],
    }
    provenance = _safe_provenance(d.provenance)
    if provenance:
        payload["provenance"] = provenance
    db.add(ActionLog(project_id=d.project_id, node_id=edge.from_node_id,
                     actor_type=d.actor_type,
                     actor_id=d.actor_id if d.actor_id is not None else null(),
                     action_type="mainline_promoted", payload=payload))
    await db.flush()
    return edge, validated.mainline_siblings


async def apply_delete_edge(db: AsyncSession, validated: ValidatedDeleteEdge) -> None:
    """Stage a graph-relation delete and sanitized history; never commit or touch endpoints."""
    d, edge = validated.data, validated.edge
    payload: dict[str, Any] = {
        "edge_id": edge.id,
        "from_node_id": edge.from_node_id,
        "to_node_id": edge.to_node_id,
        "relation_type": edge.relation_type,
    }
    provenance = _safe_provenance(d.provenance)
    if provenance:
        payload["provenance"] = provenance
    db.add(ActionLog(project_id=d.project_id, node_id=edge.from_node_id,
                     actor_type=d.actor_type,
                     actor_id=d.actor_id if d.actor_id is not None else null(),
                     action_type="graph_relation_deleted", payload=payload))
    await db.delete(edge)
    await db.flush()
