"""Edge service-layer business logic."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Edge, Node
from models.schemas import EdgeCreate
from services.exceptions import NotFoundError, ValidationError


async def create_edge(db: AsyncSession, data: EdgeCreate) -> Edge:
    from_node = await db.get(Node, data.from_node_id)
    to_node = await db.get(Node, data.to_node_id)
    if not from_node or not to_node:
        raise ValidationError("Invalid node id")
    if from_node.project_id != to_node.project_id:
        raise ValidationError("Nodes must be in same project")

    payload = data.model_dump()
    is_mainline = payload.pop("is_mainline", False)

    if is_mainline and payload.get("relation_type", "child_of") == "child_of":
        await db.execute(
            update(Edge)
            .where(
                Edge.from_node_id == payload["from_node_id"],
                Edge.relation_type == "child_of",
            )
            .values(is_mainline=False)
        )

    edge = Edge(project_id=from_node.project_id, **payload, is_mainline=is_mainline)
    db.add(edge)
    await db.commit()
    await db.refresh(edge)
    return edge


async def delete_edge(db: AsyncSession, edge_id: str) -> None:
    edge = await db.get(Edge, edge_id)
    if not edge:
        raise NotFoundError("Edge not found")
    await db.delete(edge)
    await db.commit()


async def promote_mainline(db: AsyncSession, edge_id: str) -> Edge:
    edge = await db.get(Edge, edge_id)
    if not edge:
        raise NotFoundError("Edge not found")
    if edge.relation_type != "child_of":
        raise ValidationError("Only child_of edges can be promoted")

    await db.execute(
        update(Edge)
        .where(
            Edge.from_node_id == edge.from_node_id,
            Edge.relation_type == "child_of",
        )
        .values(is_mainline=False)
    )
    edge.is_mainline = True
    await db.commit()
    await db.refresh(edge)
    return edge


async def promote_child_mainline(db: AsyncSession, parent_id: str, child_id: str) -> dict[str, bool]:
    result = await db.execute(
        select(Edge).where(
            Edge.from_node_id == parent_id,
            Edge.to_node_id == child_id,
            Edge.relation_type == "child_of",
        )
    )
    edge = result.scalar_one_or_none()
    if not edge:
        raise NotFoundError("Edge not found")

    await db.execute(
        update(Edge)
        .where(Edge.from_node_id == parent_id, Edge.relation_type == "child_of")
        .values(is_mainline=False)
    )
    edge.is_mainline = True
    await db.commit()
    return {"ok": True}
