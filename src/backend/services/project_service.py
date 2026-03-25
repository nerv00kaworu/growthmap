"""Project service-layer business logic."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import ActionLog, ContentBlock, Edge, Node, Project
from models.schemas import ProjectCreate, ProjectUpdate
from services.exceptions import NotFoundError


def touch_project(project: Project | None) -> None:
    if project:
        project.updated_at = datetime.now(timezone.utc)


async def list_projects(db: AsyncSession) -> list[Project]:
    result = await db.execute(select(Project).order_by(Project.updated_at.desc()))
    return list(result.scalars().all())


async def create_project(db: AsyncSession, data: ProjectCreate) -> Project:
    project = Project(**data.model_dump())
    db.add(project)
    await db.flush()

    root = Node(
        project_id=project.id,
        title=project.name,
        summary=project.description,
        node_type="concept",
        created_by="human",
    )
    db.add(root)
    await db.flush()
    project.root_node_id = root.id

    db.add(
        ActionLog(
            project_id=project.id,
            actor_type="human",
            action_type="create_project",
            payload={"name": project.name},
        )
    )
    await db.commit()
    await db.refresh(project)
    return project


async def get_project(db: AsyncSession, project_id: str) -> Project:
    project = await db.get(Project, project_id)
    if not project:
        raise NotFoundError("Project not found")
    return project


async def update_project(db: AsyncSession, project_id: str, data: ProjectUpdate) -> Project:
    project = await get_project(db, project_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    await db.commit()
    await db.refresh(project)
    return project


async def delete_project(db: AsyncSession, project_id: str) -> None:
    project = await get_project(db, project_id)
    await db.delete(project)
    await db.commit()


async def export_project_markdown(db: AsyncSession, project_id: str) -> str:
    project = await get_project(db, project_id)
    if not project.root_node_id:
        raise NotFoundError("No root node")

    nodes_result = await db.execute(select(Node).where(Node.project_id == project_id))
    nodes_by_id = {str(node.id): node for node in nodes_result.scalars().all()}

    edges_result = await db.execute(
        select(Edge.from_node_id, Edge.to_node_id).where(
            Edge.project_id == project_id,
            Edge.relation_type == "child_of",
        )
    )
    child_map: dict[str, list[str]] = {}
    for from_id, to_id in edges_result.all():
        child_map.setdefault(str(from_id), []).append(str(to_id))

    all_node_ids = list(nodes_by_id.keys())
    blocks_by_node: dict[str, list[ContentBlock]] = {}
    if all_node_ids:
        blocks_result = await db.execute(
            select(ContentBlock)
            .where(ContentBlock.node_id.in_(all_node_ids))
            .order_by(ContentBlock.node_id, ContentBlock.order_index)
        )
        for block in blocks_result.scalars().all():
            blocks_by_node.setdefault(str(block.node_id), []).append(block)

    lines = [f"# {project.name}\n"]
    if project.description:
        lines.append(f"_{project.description}_\n")
    if project.goal:
        lines.append(f"**目標**: {project.goal}\n")
    lines.append("---\n")

    visited: set[str] = set()

    def render_node(node_id: str, depth: int = 0) -> None:
        if node_id in visited or node_id not in nodes_by_id:
            return

        visited.add(node_id)
        node = nodes_by_id[node_id]
        prefix = "#" * min(depth + 2, 6)
        maturity_badge = {
            "seed": "🌱",
            "rough": "🪨",
            "developing": "🔧",
            "stable": "✅",
            "finalized": "🏆",
        }.get(node.maturity, "")
        lines.append(f"{prefix} {maturity_badge} {node.title}\n")
        if node.summary:
            lines.append(f"{node.summary}\n")

        for block in blocks_by_node.get(node_id, []):
            content = block.content or {}
            title = content.get("title", "")
            body = content.get("body", "")
            lines.append(f"**[{block.block_type}] {title}**\n")
            if body:
                lines.append(f"{body}\n")

        if node.maturity == "seed":
            lines.append("_⏳ 待展開_\n")

        for child_id in child_map.get(node_id, []):
            render_node(child_id, depth + 1)

    render_node(str(project.root_node_id))
    return "\n".join(lines)
