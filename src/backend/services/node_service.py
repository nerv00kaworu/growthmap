"""Node service-layer business logic."""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import ActionLog, ContentBlock, Edge, Node, Project
from models.schemas import ContentBlockCreate, NodeCreate, NodeUpdate
from services.exceptions import NotFoundError, ValidationError
from services.project_service import touch_project

MATURITY_ORDER = ["seed", "rough", "developing", "stable", "finalized"]


async def create_node(db: AsyncSession, project_id: str, data: NodeCreate) -> Node:
    project = await db.get(Project, project_id)
    if not project:
        raise NotFoundError("Project not found")

    node = Node(
        project_id=project_id,
        title=data.title,
        summary=data.summary,
        node_type=data.node_type,
        description=data.description,
        tags=data.tags,
        created_by="human",
    )
    db.add(node)
    await db.flush()

    if data.parent_id:
        parent = await db.get(Node, data.parent_id)
        if not parent or parent.project_id != project_id:
            raise ValidationError("Invalid parent node")

        result = await db.execute(
            select(func.count()).select_from(Edge).where(
                Edge.from_node_id == data.parent_id,
                Edge.relation_type == "child_of",
            )
        )
        existing_children = result.scalar() or 0
        db.add(
            Edge(
                project_id=project_id,
                from_node_id=data.parent_id,
                to_node_id=node.id,
                relation_type="child_of",
                is_mainline=existing_children == 0,
            )
        )

    db.add(
        ActionLog(
            project_id=project_id,
            node_id=node.id,
            actor_type="human",
            action_type="create_node",
            payload={"title": node.title, "parent_id": str(data.parent_id) if data.parent_id else None},
        )
    )
    touch_project(project)
    if data.parent_id:
        await auto_advance_maturity(db, data.parent_id)
    await db.commit()
    await db.refresh(node)
    return node


async def get_node(db: AsyncSession, node_id: str) -> Node:
    node = await db.get(Node, node_id)
    if not node:
        raise NotFoundError("Node not found")
    return node


async def update_node(db: AsyncSession, node_id: str, data: NodeUpdate) -> Node:
    node = await get_node(db, node_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(node, key, value)
    node.last_edited_by = "human"
    await auto_advance_maturity(db, node_id)

    db.add(
        ActionLog(
            project_id=node.project_id,
            node_id=node.id,
            actor_type="human",
            action_type="update_node",
            payload=data.model_dump(exclude_unset=True),
        )
    )
    project = await db.get(Project, node.project_id)
    touch_project(project)
    await db.commit()
    await db.refresh(node)
    return node


async def delete_node(db: AsyncSession, node_id: str) -> None:
    node = await get_node(db, node_id)
    project = await db.get(Project, node.project_id)
    if project and project.root_node_id == node_id:
        raise ValidationError("Cannot delete the project root node")

    async with db.begin_nested():
        edge_result = await db.execute(
            select(Edge).where(or_(Edge.from_node_id == node_id, Edge.to_node_id == node_id))
        )
        for edge in edge_result.scalars().all():
            await db.delete(edge)
        await db.delete(node)
        touch_project(project)
    await db.commit()


async def get_children(db: AsyncSession, node_id: str) -> list[Node]:
    result = await db.execute(
        select(Node).join(Edge, Edge.to_node_id == Node.id).where(
            Edge.from_node_id == node_id,
            Edge.relation_type == "child_of",
        )
    )
    return list(result.scalars().all())


async def get_subtree(db: AsyncSession, node_id: str) -> dict:
    node = await get_node(db, node_id)

    edge_rows = await db.execute(
        select(Edge.from_node_id, Edge.to_node_id, Edge.id, Edge.is_mainline).where(
            Edge.project_id == node.project_id,
            Edge.relation_type == "child_of",
        )
    )
    child_map: dict[str, list[str]] = {}
    edge_meta: dict[str, dict[str, str | bool]] = {}
    for from_node_id, to_node_id, edge_id, is_mainline in edge_rows.all():
        from_id = str(from_node_id)
        to_id = str(to_node_id)
        edge_meta[to_id] = {"edge_id": str(edge_id), "is_mainline": bool(is_mainline)}
        child_map.setdefault(from_id, []).append(to_id)

    subtree_ids = {node_id}
    frontier = [node_id]
    depth = 0
    while frontier and depth < 10:
        next_frontier: list[str] = []
        for current_id in frontier:
            for child_id in child_map.get(current_id, []):
                if child_id not in subtree_ids:
                    subtree_ids.add(child_id)
                    next_frontier.append(child_id)
        frontier = next_frontier
        depth += 1

    nodes_result = await db.execute(select(Node).where(Node.id.in_(subtree_ids)))
    nodes_by_id = {str(item.id): item for item in nodes_result.scalars().all()}

    blocks_result = await db.execute(
        select(ContentBlock)
        .where(ContentBlock.node_id.in_(subtree_ids))
        .order_by(ContentBlock.node_id, ContentBlock.order_index)
    )
    blocks_by_node_id: dict[str, list[dict]] = {}
    for block in blocks_result.scalars().all():
        block_node_id = str(block.node_id)
        blocks_by_node_id.setdefault(block_node_id, []).append(
            {
                "id": block.id,
                "block_type": block.block_type,
                "content": block.content,
                "order_index": block.order_index,
            }
        )

    def build_tree(
        current_node_id: str,
        current_depth: int = 0,
        ancestor_path: list[dict[str, str]] | None = None,
    ) -> dict:
        current_node = nodes_by_id[current_node_id]
        current_ancestor_path = list(ancestor_path or [])
        children = []
        if current_depth < 10:
            next_ancestor_path = current_ancestor_path + [
                {
                    "id": str(current_node.id),
                    "title": current_node.title,
                    "node_type": current_node.node_type,
                }
            ]
            for child_id in child_map.get(current_node_id, []):
                if child_id in nodes_by_id:
                    children.append(build_tree(child_id, current_depth + 1, next_ancestor_path))

        return {
            "id": str(current_node.id),
            "title": current_node.title,
            "summary": current_node.summary,
            "node_type": current_node.node_type,
            "status": current_node.status,
            "maturity": current_node.maturity,
            "tags": current_node.tags or [],
            "meta": edge_meta.get(current_node_id, {}),
            "content_blocks": blocks_by_node_id.get(current_node_id, []),
            "ancestor_path": current_ancestor_path,
            "created_at": current_node.created_at.isoformat() if current_node.created_at else "",
            "updated_at": current_node.updated_at.isoformat() if current_node.updated_at else "",
            "children": children,
        }

    return build_tree(node_id)


async def create_block(db: AsyncSession, node_id: str, data: ContentBlockCreate) -> ContentBlock:
    await get_node(db, node_id)
    block = ContentBlock(node_id=node_id, **data.model_dump())
    db.add(block)
    await auto_advance_maturity(db, node_id)
    await db.commit()
    await db.refresh(block)
    return block


async def get_node_history(db: AsyncSession, node_id: str, limit: int = 20) -> list[dict]:
    result = await db.execute(
        select(ActionLog).where(ActionLog.node_id == node_id).order_by(ActionLog.created_at.desc()).limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "action_type": log.action_type,
            "actor_type": log.actor_type,
            "payload": log.payload,
            "created_at": log.created_at.isoformat() if log.created_at else "",
        }
        for log in logs
    ]


async def auto_advance_maturity(db: AsyncSession, node_id: str) -> None:
    node = await db.get(Node, node_id)
    if not node or node.maturity == "finalized":
        return

    result = await db.execute(
        select(func.count()).select_from(ContentBlock).where(ContentBlock.node_id == node_id)
    )
    block_count = result.scalar() or 0

    result = await db.execute(
        select(func.count()).select_from(Edge).where(
            Edge.from_node_id == node_id,
            Edge.relation_type == "child_of",
        )
    )
    child_count = result.scalar() or 0

    has_summary = bool(node.summary and len(node.summary.strip()) > 10)
    current = node.maturity
    new_maturity = current

    if current == "seed" and (has_summary or child_count >= 1):
        new_maturity = "rough"
    if current in ("seed", "rough") and block_count >= 1 and child_count >= 1:
        new_maturity = "developing"
    if current in ("seed", "rough", "developing") and block_count >= 3 and has_summary and child_count >= 2:
        new_maturity = "stable"

    if new_maturity != current:
        await db.refresh(node)
        current = node.maturity
        if current == "finalized" or new_maturity == current:
            return

        node.maturity = new_maturity
        db.add(
            ActionLog(
                project_id=node.project_id,
                node_id=node.id,
                actor_type="system",
                action_type="maturity_advance",
                payload={"from": current, "to": new_maturity},
            )
        )
