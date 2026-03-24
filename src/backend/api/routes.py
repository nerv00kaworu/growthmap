"""Project & Node API routes"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.database import get_db
from models.models import Project, Node, Edge, ContentBlock, ActionLog
from models.schemas import (
    ProjectCreate, ProjectUpdate, ProjectOut,
    NodeCreate, NodeUpdate, NodeOut, NodeBrief,
    EdgeCreate, EdgeOut,
    ContentBlockCreate, ContentBlockUpdate, ContentBlockOut,
)

router = APIRouter()


# ─── Projects ───

@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).order_by(Project.updated_at.desc()))
    return result.scalars().all()


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    project = Project(**data.model_dump())
    db.add(project)
    await db.flush()

    # 自動建 root node
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

    # log
    db.add(ActionLog(
        project_id=project.id,
        actor_type="human",
        action_type="create_project",
        payload={"name": project.name},
    ))
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(project_id: str, data: ProjectUpdate, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(project, k, v)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    await db.delete(project)
    await db.commit()


# ─── Nodes ───

@router.get("/projects/{project_id}/nodes", response_model=list[NodeBrief])
async def list_nodes(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Node).where(Node.project_id == project_id).order_by(Node.created_at)
    )
    return result.scalars().all()


@router.post("/projects/{project_id}/nodes", response_model=NodeOut, status_code=201)
async def create_node(project_id: str, data: NodeCreate, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

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

    # 如果指定 parent，自動建 child_of edge
    if data.parent_id:
        parent = await db.get(Node, data.parent_id)
        if not parent or parent.project_id != project_id:
            raise HTTPException(400, "Invalid parent node")
        edge = Edge(
            project_id=project_id,
            from_node_id=data.parent_id,
            to_node_id=node.id,
            relation_type="child_of",
        )
        db.add(edge)

    db.add(ActionLog(
        project_id=project_id,
        node_id=node.id,
        actor_type="human",
        action_type="create_node",
        payload={"title": node.title, "parent_id": str(data.parent_id) if data.parent_id else None},
    ))
    # Auto-advance parent maturity
    if data.parent_id:
        await auto_advance_maturity(data.parent_id, db)
    await db.commit()
    await db.refresh(node)
    return node


@router.get("/nodes/{node_id}", response_model=NodeOut)
async def get_node(node_id: str, db: AsyncSession = Depends(get_db)):
    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    return node


@router.patch("/nodes/{node_id}", response_model=NodeOut)
async def update_node(node_id: str, data: NodeUpdate, db: AsyncSession = Depends(get_db)):
    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(node, k, v)
    node.last_edited_by = "human"
    # Auto-advance maturity based on content richness
    await auto_advance_maturity(node_id, db)

    db.add(ActionLog(
        project_id=node.project_id,
        node_id=node.id,
        actor_type="human",
        action_type="update_node",
        payload=data.model_dump(exclude_unset=True),
    ))
    await db.commit()
    await db.refresh(node)
    return node


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(node_id: str, db: AsyncSession = Depends(get_db)):
    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    # Delete edges referencing this node first
    from sqlalchemy import or_
    await db.execute(
        Edge.__table__.delete().where(
            or_(Edge.from_node_id == node_id, Edge.to_node_id == node_id)
        )
    )
    await db.delete(node)
    await db.commit()


@router.get("/nodes/{node_id}/children", response_model=list[NodeBrief])
async def get_children(node_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Node).join(Edge, Edge.to_node_id == Node.id).where(
            Edge.from_node_id == node_id,
            Edge.relation_type == "child_of"
        )
    )
    return result.scalars().all()


@router.get("/nodes/{node_id}/subtree")
async def get_subtree(node_id: str, db: AsyncSession = Depends(get_db)):
    """遞迴取得子樹（BFS）"""
    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")

    async def build_tree(nid: str, depth: int = 0) -> dict:
        n = await db.get(Node, nid)
        result = await db.execute(
            select(Edge.to_node_id).where(
                Edge.from_node_id == nid,
                Edge.relation_type == "child_of"
            )
        )
        child_ids = result.scalars().all()
        children = []
        if depth < 10:  # 防無限遞迴
            for cid in child_ids:
                children.append(await build_tree(cid, depth + 1))

        # Get content blocks
        blocks_result = await db.execute(
            select(ContentBlock).where(ContentBlock.node_id == nid).order_by(ContentBlock.order_index)
        )
        blocks = [
            {"id": b.id, "block_type": b.block_type, "content": b.content, "order_index": b.order_index}
            for b in blocks_result.scalars().all()
        ]

        return {
            "id": str(n.id),
            "title": n.title,
            "summary": n.summary,
            "node_type": n.node_type,
            "status": n.status,
            "maturity": n.maturity,
            "tags": n.tags or [],
            "meta": {},
            "content_blocks": blocks,
            "created_at": n.created_at.isoformat() if n.created_at else "",
            "updated_at": n.updated_at.isoformat() if n.updated_at else "",
            "children": children,
        }

    return await build_tree(node_id)


# ─── Edges ───

@router.post("/edges", response_model=EdgeOut, status_code=201)
async def create_edge(data: EdgeCreate, db: AsyncSession = Depends(get_db)):
    from_node = await db.get(Node, data.from_node_id)
    to_node = await db.get(Node, data.to_node_id)
    if not from_node or not to_node:
        raise HTTPException(400, "Invalid node id")
    if from_node.project_id != to_node.project_id:
        raise HTTPException(400, "Nodes must be in same project")

    edge = Edge(
        project_id=from_node.project_id,
        **data.model_dump(),
    )
    db.add(edge)
    await db.commit()
    await db.refresh(edge)
    return edge


@router.delete("/edges/{edge_id}", status_code=204)
async def delete_edge(edge_id: str, db: AsyncSession = Depends(get_db)):
    edge = await db.get(Edge, edge_id)
    if not edge:
        raise HTTPException(404, "Edge not found")
    await db.delete(edge)
    await db.commit()


# ─── Content Blocks ───

@router.get("/nodes/{node_id}/blocks", response_model=list[ContentBlockOut])
async def list_blocks(node_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ContentBlock).where(ContentBlock.node_id == node_id).order_by(ContentBlock.order_index)
    )
    return result.scalars().all()


@router.post("/nodes/{node_id}/blocks", response_model=ContentBlockOut, status_code=201)
async def create_block(node_id: str, data: ContentBlockCreate, db: AsyncSession = Depends(get_db)):
    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    block = ContentBlock(node_id=node_id, **data.model_dump())
    db.add(block)
    await auto_advance_maturity(node_id, db)
    await db.commit()
    await db.refresh(block)
    return block


@router.patch("/blocks/{block_id}", response_model=ContentBlockOut)
async def update_block(block_id: str, data: ContentBlockUpdate, db: AsyncSession = Depends(get_db)):
    block = await db.get(ContentBlock, block_id)
    if not block:
        raise HTTPException(404, "Block not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(block, k, v)
    await db.commit()
    await db.refresh(block)
    return block


@router.delete("/blocks/{block_id}", status_code=204)
async def delete_block(block_id: str, db: AsyncSession = Depends(get_db)):
    block = await db.get(ContentBlock, block_id)
    if not block:
        raise HTTPException(404, "Block not found")
    await db.delete(block)
    await db.commit()


# ─── Maturity Auto-Advance ───

MATURITY_ORDER = ["seed", "rough", "developing", "stable", "finalized"]

async def auto_advance_maturity(node_id: str, db: AsyncSession):
    """Auto-advance node maturity based on content richness.
    
    Rules:
    - seed → rough: has summary OR at least 1 child
    - rough → developing: has ≥1 content block AND ≥1 child  
    - developing → stable: has ≥3 content blocks AND summary AND ≥2 children
    - stable → finalized: only manual (human decision)
    """
    node = await db.get(Node, node_id)
    if not node or node.maturity == "finalized":
        return

    # Count content blocks
    result = await db.execute(
        select(func.count()).select_from(ContentBlock).where(ContentBlock.node_id == node_id)
    )
    block_count = result.scalar() or 0

    # Count children
    result = await db.execute(
        select(func.count()).select_from(Edge).where(
            Edge.from_node_id == node_id,
            Edge.relation_type == "child_of"
        )
    )
    child_count = result.scalar() or 0

    has_summary = bool(node.summary and len(node.summary.strip()) > 10)
    current = node.maturity
    new_maturity = current

    if current == "seed":
        if has_summary or child_count >= 1:
            new_maturity = "rough"
    if current in ("seed", "rough"):
        if block_count >= 1 and child_count >= 1:
            new_maturity = "developing"
    if current in ("seed", "rough", "developing"):
        if block_count >= 3 and has_summary and child_count >= 2:
            new_maturity = "stable"

    if new_maturity != current:
        node.maturity = new_maturity
        db.add(ActionLog(
            project_id=node.project_id,
            node_id=node.id,
            actor_type="system",
            action_type="maturity_advance",
            payload={"from": current, "to": new_maturity},
        ))


# ─── Node History ───

@router.get("/nodes/{node_id}/history")
async def get_node_history(node_id: str, limit: int = 20, db: AsyncSession = Depends(get_db)):
    """Get action history for a node — what happened to it and when."""
    result = await db.execute(
        select(ActionLog).where(ActionLog.node_id == node_id)
        .order_by(ActionLog.created_at.desc())
        .limit(limit)
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


# ─── Export ───

from fastapi.responses import PlainTextResponse

@router.get("/projects/{project_id}/export", response_class=PlainTextResponse)
async def export_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Export entire project tree as Markdown document."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.root_node_id:
        raise HTTPException(404, "No root node")

    lines = [f"# {project.name}\n"]
    if project.description:
        lines.append(f"_{project.description}_\n")
    if project.goal:
        lines.append(f"**目標**: {project.goal}\n")
    lines.append("---\n")

    async def export_node(nid: str, depth: int = 0):
        n = await db.get(Node, nid)
        if not n:
            return
        prefix = "#" * min(depth + 2, 6)
        maturity_badge = {"seed": "🌱", "rough": "🪨", "developing": "🔧", "stable": "✅", "finalized": "🏆"}.get(n.maturity, "")
        lines.append(f"{prefix} {maturity_badge} {n.title}\n")
        if n.summary:
            lines.append(f"{n.summary}\n")

        # Content blocks
        result = await db.execute(
            select(ContentBlock).where(ContentBlock.node_id == nid).order_by(ContentBlock.order_index)
        )
        for b in result.scalars().all():
            content = b.content or {}
            title = content.get("title", "")
            body = content.get("body", "")
            lines.append(f"**[{b.block_type}] {title}**\n")
            if body:
                lines.append(f"{body}\n")

        if n.maturity == "seed":
            lines.append("_⏳ 待展開_\n")

        # Recurse children
        result = await db.execute(
            select(Edge.to_node_id).where(
                Edge.from_node_id == nid, Edge.relation_type == "child_of"
            )
        )
        for cid in result.scalars().all():
            await export_node(cid, depth + 1)

    await export_node(project.root_node_id)
    return "\n".join(lines)
