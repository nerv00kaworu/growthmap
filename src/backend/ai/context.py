"""Context builder — assembles minimal local context for LLM operations"""
from sqlalchemy import select, literal, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from models.models import Node, Edge, Project, ContentBlock, ActionLog


async def _load_ancestor_path(node_id: str, db: AsyncSession) -> tuple[list[dict], str | None]:
    """Load ancestor nodes in one recursive query and return the direct parent id."""
    base = (
        select(
            Edge.from_node_id.label("ancestor_id"),
            literal(1).label("depth"),
        )
        .where(Edge.to_node_id == node_id, Edge.relation_type == "child_of")
        .cte(name="ancestor_chain", recursive=True)
    )

    parent_edge = Edge.__table__.alias("parent_edge")
    ancestor_chain = base.union_all(
        select(
            parent_edge.c.from_node_id.label("ancestor_id"),
            (base.c.depth + 1).label("depth"),
        ).where(
            parent_edge.c.to_node_id == base.c.ancestor_id,
            parent_edge.c.relation_type == "child_of",
            base.c.depth < 5,
        )
    )

    result = await db.execute(
        select(ancestor_chain.c.ancestor_id, ancestor_chain.c.depth, Node.title, Node.node_type)
        .join(Node, Node.id == ancestor_chain.c.ancestor_id)
        .order_by(ancestor_chain.c.depth.desc())
    )

    rows = result.all()
    ancestors = [
        {"id": row.ancestor_id, "title": row.title, "type": row.node_type}
        for row in rows
    ]
    direct_parent_id = rows[-1].ancestor_id if rows else None
    return ancestors, direct_parent_id


async def build_node_context(node_id: str, db: AsyncSession) -> dict:
    """Build a compact context packet for a single node.
    
    Includes: project info, ancestor path, current node, siblings, children summaries.
    This is the "just enough" context for LLM to operate on one node.
    """
    node = await db.get(Node, node_id)
    if not node:
        raise ValueError(f"Node {node_id} not found")

    project = await db.get(Project, node.project_id)

    ancestors, parent_id = await _load_ancestor_path(node_id, db)

    # Get siblings + children with one edge read and one node read
    siblings = []
    children = []

    relationship_source_ids = {node_id}
    if parent_id:
        relationship_source_ids.add(parent_id)

    edge_result = await db.execute(
        select(Edge.from_node_id, Edge.to_node_id).where(
            Edge.relation_type == "child_of",
            Edge.from_node_id.in_(relationship_source_ids),
        )
    )
    edge_rows = edge_result.all()

    related_node_ids = {str(row.to_node_id) for row in edge_rows}
    related_nodes_by_id: dict[str, Node] = {}
    if related_node_ids:
        related_nodes = await db.execute(select(Node).where(Node.id.in_(related_node_ids)))
        related_nodes_by_id = {str(related.id): related for related in related_nodes.scalars().all()}

    for row in edge_rows:
        source_id = str(row.from_node_id)
        related_node = related_nodes_by_id.get(str(row.to_node_id))
        if not related_node:
            continue

        item = {
            "id": related_node.id,
            "title": related_node.title,
            "type": related_node.node_type,
            "maturity": related_node.maturity,
        }

        if source_id == node_id:
            children.append(item)
        elif parent_id and source_id == str(parent_id) and str(related_node.id) != node_id:
            siblings.append(item)

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
            "name": project.name if project else "",
            "description": project.description if project else "",
            "goal": project.goal if project else "",
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
