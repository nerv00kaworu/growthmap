"""Canonical branch creation shared by the human API and Agent Port.

The caller owns validation, the Project revision CAS, audit/receipt rows and the
transaction boundary.  This module never commits and never mutates the source
subtree.
"""
from copy import deepcopy
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Branch, ContentBlock, Edge, Node


async def deep_copy_branch(
    db: AsyncSession,
    *,
    project_id: str,
    source_node_id: str,
    name: str,
    description: str = "",
    branch_id: str | None = None,
    actor: str = "branch",
) -> Branch:
    """Stage one revision-1 Branch and a deep copy of its containment subtree.

    No Project/source revision is claimed here and no flush/commit is performed;
    all staged objects therefore remain part of the caller's atomic transaction.
    """
    source = await db.get(Node, source_node_id)
    if not source or source.project_id != project_id:
        raise HTTPException(422, {"code": "INVALID_SOURCE", "message": "Branch source must exist in project"})

    branch = Branch(
        id=branch_id or str(uuid.uuid4()), project_id=project_id,
        name=name, description=description, source_node_id=source_node_id,
        status="active", revision=1,
    )
    db.add(branch)

    edges = (await db.execute(select(Edge).where(
        Edge.project_id == project_id, Edge.relation_type == "child_of"
    ))).scalars().all()
    children: dict[str, list[str]] = {}
    for edge in edges:
        children.setdefault(str(edge.from_node_id), []).append(str(edge.to_node_id))

    subtree: list[str] = []
    seen: set[str] = set()
    stack = [source_node_id]
    while stack:
        old_id = stack.pop()
        if old_id in seen:
            continue
        seen.add(old_id)
        subtree.append(old_id)
        stack.extend(reversed(children.get(old_id, ())))

    nodes = {str(n.id): n for n in (await db.execute(
        select(Node).where(Node.project_id == project_id, Node.id.in_(subtree))
    )).scalars().all()}
    if len(nodes) != len(subtree):
        raise HTTPException(422, {"code": "INVALID_SUBTREE", "message": "Branch source subtree is inconsistent"})

    blocks_by_node: dict[str, list[ContentBlock]] = {}
    blocks = (await db.execute(select(ContentBlock).where(
        ContentBlock.node_id.in_(subtree)
    ).order_by(ContentBlock.node_id, ContentBlock.order_index, ContentBlock.id))).scalars().all()
    for block in blocks:
        blocks_by_node.setdefault(str(block.node_id), []).append(block)

    id_map = {old_id: str(uuid.uuid4()) for old_id in subtree}
    for old_id in subtree:
        old = nodes[old_id]
        db.add(Node(
            id=id_map[old_id], project_id=project_id, title=old.title,
            summary=old.summary, node_type=old.node_type, status=old.status,
            maturity=old.maturity, priority=old.priority, confidence=old.confidence,
            description=old.description, rules_text=old.rules_text,
            constraints_text=old.constraints_text, examples_text=old.examples_text,
            questions_text=old.questions_text, decision_notes=old.decision_notes,
            tags=deepcopy(old.tags or []), workflow_status=old.workflow_status,
            file_paths=deepcopy(old.file_paths or []), branch_id=branch.id,
            created_by=actor, last_edited_by=old.last_edited_by or actor,
            position_x=old.position_x, position_y=old.position_y, revision=1,
        ))
        for old_block in blocks_by_node.get(old_id, ()):
            db.add(ContentBlock(
                id=str(uuid.uuid4()), node_id=id_map[old_id],
                block_type=old_block.block_type, content=deepcopy(old_block.content),
                order_index=old_block.order_index, created_by=actor, revision=1,
            ))

    # Materialize Branch/nodes/blocks before edge FKs. This remains inside the
    # caller's transaction (flush is not commit).
    await db.flush()

    for edge in edges:
        old_from, old_to = str(edge.from_node_id), str(edge.to_node_id)
        if old_from in id_map and old_to in id_map:
            db.add(Edge(
                id=str(uuid.uuid4()), project_id=project_id,
                from_node_id=id_map[old_from], to_node_id=id_map[old_to],
                relation_type="child_of", weight=edge.weight, note=edge.note,
                is_mainline=bool(edge.is_mainline), revision=1,
            ))
    return branch
