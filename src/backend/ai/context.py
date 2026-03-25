"""Context builder — assembles minimal local context for LLM operations"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models.models import Node, Edge, Project, ContentBlock, ActionLog


async def build_node_context(node_id: str, db: AsyncSession) -> dict:
    """Build a compact context packet for a single node.
    
    Includes: project info, ancestor path, current node, siblings, children summaries.
    This is the "just enough" context for LLM to operate on one node.
    """
    node = await db.get(Node, node_id)
    if not node:
        raise ValueError(f"Node {node_id} not found")

    project = await db.get(Project, node.project_id)
    if not project:
        raise ValueError(f"Project {node.project_id} not found")

    # Get ancestors (walk up parent edges, max 5 levels)
    ancestors = []
    current_id = node_id
    for _ in range(5):
        result = await db.execute(
            select(Edge.from_node_id).where(
                Edge.to_node_id == current_id,
                Edge.relation_type == "child_of"
            )
        )
        parent_id = result.scalar_one_or_none()
        if not parent_id:
            break
        parent = await db.get(Node, parent_id)
        if parent:
            ancestors.insert(0, {"id": parent.id, "title": parent.title, "type": parent.node_type})
        current_id = parent_id

    # Get siblings (other children of same parent)
    siblings = []
    result = await db.execute(
        select(Edge.from_node_id).where(
            Edge.to_node_id == node_id,
            Edge.relation_type == "child_of"
        )
    )
    parent_id = result.scalar_one_or_none()
    if parent_id:
        result = await db.execute(
            select(Node).join(Edge, Edge.to_node_id == Node.id).where(
                Edge.from_node_id == parent_id,
                Edge.relation_type == "child_of",
                Node.id != node_id
            )
        )
        for sib in result.scalars().all():
            siblings.append({"id": sib.id, "title": sib.title, "type": sib.node_type, "maturity": sib.maturity})

    # Get children
    children = []
    result = await db.execute(
        select(Node).join(Edge, Edge.to_node_id == Node.id).where(
            Edge.from_node_id == node_id,
            Edge.relation_type == "child_of"
        )
    )
    for child in result.scalars().all():
        children.append({"id": child.id, "title": child.title, "type": child.node_type, "maturity": child.maturity})

    # Get content blocks (so LLM knows what's already been deepened)
    result = await db.execute(
        select(ContentBlock).where(ContentBlock.node_id == node_id).order_by(ContentBlock.order_index)
    )
    blocks = []
    for b in result.scalars().all():
        blocks.append({"block_type": b.block_type, "content": b.content})

    # Get recent action history (so LLM knows what happened before)
    result = await db.execute(
        select(ActionLog).where(ActionLog.node_id == node_id)
        .order_by(ActionLog.created_at.desc()).limit(10)
    )
    history = []
    for log in result.scalars().all():
        history.append({
            "action": log.action_type,
            "actor": log.actor_type,
            "payload": log.payload,
            "at": log.created_at.isoformat() if log.created_at else "",
        })

    return {
        "project": {
            "name": project.name,
            "description": project.description,
            "goal": project.goal,
        },
        "ancestor_path": ancestors,
        "current_node": {
            "id": node.id,
            "title": node.title,
            "summary": node.summary or "",
            "node_type": node.node_type,
            "maturity": node.maturity,
            "tags": node.tags or [],
            "description": node.description or "",
        },
        "siblings": siblings,
        "children": children,
        "content_blocks": blocks,
        "recent_history": history,
    }
