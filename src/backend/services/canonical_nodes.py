"""Entry-point-neutral canonical node creation.

Authorization, HTTP/wire contracts, project CAS, idempotency and commit ownership
remain adapter responsibilities.
"""
from dataclasses import dataclass, field
from typing import Any
from fastapi import HTTPException
from sqlalchemy import func, null, select
from sqlalchemy.ext.asyncio import AsyncSession
from models.models import ActionLog, Branch, Edge, Node, Project
from services.maturity import auto_advance_maturity
from services.revisions import TouchedEntities

@dataclass(frozen=True)
class CreateNodeInput:
    project_id: str
    node_id: str | None
    parent_id: str | None
    branch_id: str | None
    title: str
    summary: str = ""
    node_type: str = "idea"
    description: str = ""
    tags: list[str] = field(default_factory=list)
    actor_type: str = "human"
    actor_id: str | None = None
    created_by: str = "human"
    provenance: dict[str, Any] = field(default_factory=dict)

@dataclass
class ValidatedCreateNode:
    data: CreateNodeInput
    project: Project
    parent: Node | None
    branch: Branch | None
    branch_id: str | None

async def validate_create_node(db: AsyncSession, data: CreateNodeInput) -> ValidatedCreateNode:
    project = await db.get(Project, data.project_id)
    if not project: raise HTTPException(404, "Project not found")
    if not data.title.strip():
        raise HTTPException(422, {"code":"INVALID_TITLE", "message":"Node title cannot be blank"})
    if data.node_id and await db.get(Node, data.node_id):
        raise HTTPException(409, {"code":"ID_CONFLICT", "message":"Entity id already exists"})
    if data.node_id and data.parent_id == data.node_id:
        raise HTTPException(422, {"code":"INVALID_REFERENCE", "message":"Node cannot contain itself"})
    parent = await db.get(Node, data.parent_id) if data.parent_id else None
    if data.parent_id and (not parent or parent.project_id != data.project_id):
        raise HTTPException(422, {"code":"INVALID_REFERENCE", "message":"Parent must exist in project"})
    branch_id = data.branch_id
    if parent:
        inherited = parent.branch_id or None
        if branch_id is None: branch_id = inherited
        elif branch_id != inherited:
            raise HTTPException(422, {"code":"BRANCH_MISMATCH", "message":"Parent and child must belong to the same branch"})
    branch = await db.get(Branch, branch_id) if branch_id else None
    if branch_id and (not branch or branch.project_id != data.project_id):
        raise HTTPException(422, {"code":"INVALID_BRANCH", "message":"Branch must exist in project"})
    if branch and branch.status != "active":
        raise HTTPException(422, {"code":"INACTIVE_BRANCH", "message":"Branch is not active"})
    return ValidatedCreateNode(data, project, parent, branch, branch_id)

async def apply_create_node(db: AsyncSession, validated: ValidatedCreateNode, *, touched: TouchedEntities | None = None) -> Node:
    d = validated.data
    touched = touched or TouchedEntities()
    node = Node(id=d.node_id, project_id=d.project_id, branch_id=validated.branch_id,
                title=d.title.strip(), summary=d.summary, node_type=d.node_type,
                description=d.description, tags=d.tags, created_by=d.created_by,
                last_edited_by=d.created_by, revision=1)
    db.add(node); await db.flush()
    if validated.parent:
        count = await db.scalar(select(func.count()).select_from(Edge).where(
            Edge.from_node_id == validated.parent.id, Edge.relation_type == "child_of")) or 0
        db.add(Edge(project_id=d.project_id, from_node_id=validated.parent.id,
                    to_node_id=node.id, relation_type="child_of", is_mainline=count == 0, revision=1))
        await db.flush()
        # Creation itself leaves revision 1; only becoming a parent in this
        # transaction marks a newly-created node as touched.
        touched.add(validated.parent)
        await auto_advance_maturity(validated.parent.id, db, touched=touched)
    payload={"title":node.title,"parent_id":validated.parent.id if validated.parent else None}
    if d.provenance: payload["provenance"] = d.provenance
    db.add(ActionLog(project_id=d.project_id,node_id=node.id,actor_type=d.actor_type,
                     actor_id=d.actor_id if d.actor_id is not None else null(),
                     action_type="create_node",payload=payload))
    return node
