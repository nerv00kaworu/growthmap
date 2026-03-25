"""Project & Node API routes"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.database import get_db
from models.models import Project, Node, Edge, ContentBlock, ActionLog
from models.schemas import (
    ProjectCreate, ProjectUpdate, ProjectOut,
    NodeCreate, NodeUpdate, NodeOut, NodeBrief,
    EdgeCreate, EdgeOut,
    ContentBlockCreate, ContentBlockUpdate, ContentBlockOut,
    NodeMoveRequest, AncestorNode, MainlinePathOut, BranchInfo,
)

router = APIRouter()


def touch_project(project: Project | None):
    if project:
        project.updated_at = datetime.now(timezone.utc)


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

        # Determine if child should be mainline (first child)
        result = await db.execute(
            select(func.count()).select_from(Edge).where(
                Edge.from_node_id == data.parent_id,
                Edge.relation_type == "child_of"
            )
        )
        existing_children = result.scalar() or 0
        edge = Edge(
            project_id=project_id,
            from_node_id=data.parent_id,
            to_node_id=node.id,
            relation_type="child_of",
            is_mainline=existing_children == 0,
        )
        db.add(edge)

    db.add(ActionLog(
        project_id=project_id,
        node_id=node.id,
        actor_type="human",
        action_type="create_node",
        payload={"title": node.title, "parent_id": str(data.parent_id) if data.parent_id else None},
    ))
    touch_project(project)
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
    project = await db.get(Project, node.project_id)
    touch_project(project)
    await db.commit()
    await db.refresh(node)
    return node


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(node_id: str, db: AsyncSession = Depends(get_db)):
    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    project = await db.get(Project, node.project_id)
    if project and project.root_node_id == node_id:
        raise HTTPException(400, "Cannot delete the project root node")
    # Delete edges referencing this node first
    from sqlalchemy import or_
    await db.execute(
        Edge.__table__.delete().where(
            or_(Edge.from_node_id == node_id, Edge.to_node_id == node_id)
        )
    )
    await db.delete(node)
    touch_project(project)
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
    """遞迴取得子樹（bulk-loaded to avoid per-node query fan-out）"""
    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")

    edge_rows = await db.execute(
        select(Edge.from_node_id, Edge.to_node_id, Edge.id, Edge.is_mainline).where(
            Edge.project_id == node.project_id,
            Edge.relation_type == "child_of"
        )
    )
    child_map: dict[str, list[str]] = {}
    edge_meta: dict[str, dict[str, str | bool]] = {}
    for from_node_id, to_node_id, edge_id, is_mainline in edge_rows.all():
        from_id = str(from_node_id)
        to_id = str(to_node_id)
        edge_meta[to_id] = {
            "edge_id": str(edge_id),
            "is_mainline": bool(is_mainline),
        }
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

    nodes_result = await db.execute(
        select(Node).where(Node.id.in_(subtree_ids))
    )
    nodes_by_id = {str(n.id): n for n in nodes_result.scalars().all()}

    blocks_result = await db.execute(
        select(ContentBlock).where(ContentBlock.node_id.in_(subtree_ids)).order_by(ContentBlock.node_id, ContentBlock.order_index)
    )
    blocks_by_node_id: dict[str, list[dict]] = {}
    for block in blocks_result.scalars().all():
        block_node_id = str(block.node_id)
        blocks_by_node_id.setdefault(block_node_id, []).append({
            "id": block.id,
            "block_type": block.block_type,
            "content": block.content,
            "order_index": block.order_index,
        })

    def build_tree(nid: str, current_depth: int = 0, ancestor_path: list[dict[str, str]] | None = None) -> dict:
        n = nodes_by_id[nid]
        current_ancestor_path = list(ancestor_path or [])
        children = []
        if current_depth < 10:
            next_ancestor_path = current_ancestor_path + [{"id": str(n.id), "title": n.title, "node_type": n.node_type}]
            for child_id in child_map.get(nid, []):
                if child_id in nodes_by_id:
                    children.append(build_tree(child_id, current_depth + 1, next_ancestor_path))

        return {
            "id": str(n.id),
            "title": n.title,
            "summary": n.summary,
            "node_type": n.node_type,
            "status": n.status,
            "maturity": n.maturity,
            "tags": n.tags or [],
            "meta": edge_meta.get(nid, {}),
            "content_blocks": blocks_by_node_id.get(nid, []),
            "ancestor_path": current_ancestor_path,
            "created_at": n.created_at.isoformat() if n.created_at else "",
            "updated_at": n.updated_at.isoformat() if n.updated_at else "",
            "children": children,
        }

    return build_tree(node_id)


# ─── Edges ───

@router.post("/edges", response_model=EdgeOut, status_code=201)
async def create_edge(data: EdgeCreate, db: AsyncSession = Depends(get_db)):
    from_node = await db.get(Node, data.from_node_id)
    to_node = await db.get(Node, data.to_node_id)
    if not from_node or not to_node:
        raise HTTPException(400, "Invalid node id")
    if from_node.project_id != to_node.project_id:
        raise HTTPException(400, "Nodes must be in same project")

    payload = data.model_dump()
    is_mainline = payload.pop("is_mainline", False)

    # If new edge is marked as mainline, demote siblings first
    if is_mainline and payload.get("relation_type", "child_of") == "child_of":
        await db.execute(
            update(Edge)
            .where(
                Edge.from_node_id == payload["from_node_id"],
                Edge.relation_type == "child_of"
            )
            .values(is_mainline=False)
        )

    edge = Edge(
        project_id=from_node.project_id,
        **payload,
        is_mainline=is_mainline,
    )
    db.add(edge)
    await db.commit()
    await db.refresh(edge)
    return edge


@router.post("/edges/{edge_id}/promote-mainline", response_model=EdgeOut)
async def promote_mainline(edge_id: str, db: AsyncSession = Depends(get_db)):
    edge = await db.get(Edge, edge_id)
    if not edge:
        raise HTTPException(404, "Edge not found")
    if edge.relation_type != "child_of":
        raise HTTPException(400, "Only child_of edges can be promoted")

    await db.execute(
        update(Edge)
        .where(
            Edge.from_node_id == edge.from_node_id,
            Edge.relation_type == "child_of"
        )
        .values(is_mainline=False)
    )

    edge.is_mainline = True
    await db.commit()
    await db.refresh(edge)
    return edge


@router.post("/nodes/{parent_id}/promote-child/{child_id}")
async def promote_child_mainline(parent_id: str, child_id: str, db: AsyncSession = Depends(get_db)):
    """Promote a child node to mainline by parent+child ids."""
    result = await db.execute(
        select(Edge).where(
            Edge.from_node_id == parent_id,
            Edge.to_node_id == child_id,
            Edge.relation_type == "child_of"
        )
    )
    edge = result.scalar_one_or_none()
    if not edge:
        raise HTTPException(404, "Edge not found")

    await db.execute(
        update(Edge)
        .where(Edge.from_node_id == parent_id, Edge.relation_type == "child_of")
        .values(is_mainline=False)
    )
    edge.is_mainline = True
    await db.commit()
    return {"ok": True}


@router.delete("/edges/{edge_id}", status_code=204)
async def delete_edge(edge_id: str, db: AsyncSession = Depends(get_db)):
    edge = await db.get(Edge, edge_id)
    if not edge:
        raise HTTPException(404, "Edge not found")
    await db.delete(edge)
    await db.commit()


# ─── Governance ───

@router.post("/nodes/{node_id}/move")
async def move_node(node_id: str, body: NodeMoveRequest, db: AsyncSession = Depends(get_db)):
    """Re-parent a node under a new parent, with cycle detection."""
    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")

    project = await db.get(Project, node.project_id)
    if project and project.root_node_id == node_id:
        raise HTTPException(400, "Cannot move root node")

    new_parent = await db.get(Node, body.new_parent_id)
    if not new_parent:
        raise HTTPException(404, "New parent not found")
    if new_parent.project_id != node.project_id:
        raise HTTPException(400, "Cannot move node to a different project")

    # Cycle detection: walk descendants of node_id
    descendants: set[str] = set()
    queue = [node_id]
    while queue:
        current = queue.pop()
        child_edges = (await db.execute(
            select(Edge).where(Edge.from_node_id == current, Edge.relation_type == "child_of")
        )).scalars().all()
        for e in child_edges:
            if e.to_node_id not in descendants:
                descendants.add(e.to_node_id)
                queue.append(e.to_node_id)

    if body.new_parent_id in descendants:
        raise HTTPException(400, "Cannot move node under its own descendant (would create cycle)")

    # Remove old incoming child_of edge
    old_edge_result = await db.execute(
        select(Edge).where(Edge.to_node_id == node_id, Edge.relation_type == "child_of")
    )
    old_edge = old_edge_result.scalar_one_or_none()
    if old_edge:
        await db.delete(old_edge)

    # First child becomes mainline
    existing_children = (await db.execute(
        select(func.count()).select_from(Edge).where(
            Edge.from_node_id == body.new_parent_id, Edge.relation_type == "child_of"
        )
    )).scalar() or 0
    is_mainline = existing_children == 0

    new_edge = Edge(
        project_id=node.project_id,
        from_node_id=body.new_parent_id,
        to_node_id=node_id,
        relation_type="child_of",
        is_mainline=is_mainline,
    )
    db.add(new_edge)

    db.add(ActionLog(
        project_id=node.project_id, node_id=node_id,
        action_type="move", actor_type="human",
        payload={"from_parent": old_edge.from_node_id if old_edge else None, "to_parent": body.new_parent_id},
    ))
    touch_project(project)
    await db.commit()
    return {"ok": True, "is_mainline": is_mainline}


@router.get("/nodes/{node_id}/ancestors", response_model=list[AncestorNode])
async def get_ancestors(node_id: str, db: AsyncSession = Depends(get_db)):
    """Walk up child_of edges from node to root, return root-first order."""
    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")

    ancestors: list[dict] = []
    current_id = node_id
    visited: set[str] = {current_id}

    while True:
        edge_result = await db.execute(
            select(Edge).where(Edge.to_node_id == current_id, Edge.relation_type == "child_of")
        )
        edge = edge_result.scalar_one_or_none()
        if not edge:
            break
        parent = await db.get(Node, edge.from_node_id)
        if not parent or parent.id in visited:
            break
        visited.add(parent.id)
        ancestors.append({
            "id": parent.id, "title": parent.title,
            "node_type": parent.node_type, "maturity": parent.maturity,
            "is_mainline": edge.is_mainline,
        })
        current_id = parent.id

    ancestors.reverse()
    return ancestors


@router.get("/projects/{project_id}/mainline-path", response_model=MainlinePathOut)
async def get_mainline_path(project_id: str, db: AsyncSession = Depends(get_db)):
    """Follow mainline edges from project root to deepest leaf."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.root_node_id:
        return {"path": []}

    path: list[dict] = []
    current_id = project.root_node_id

    while current_id:
        node = await db.get(Node, current_id)
        if not node:
            break

        is_mainline = True
        if path:
            edge_result = await db.execute(
                select(Edge).where(Edge.to_node_id == current_id, Edge.relation_type == "child_of")
            )
            edge = edge_result.scalar_one_or_none()
            is_mainline = edge.is_mainline if edge else False

        path.append({
            "id": node.id, "title": node.title,
            "node_type": node.node_type, "maturity": node.maturity,
            "is_mainline": is_mainline,
        })

        mainline_edge_result = await db.execute(
            select(Edge).where(
                Edge.from_node_id == current_id, Edge.relation_type == "child_of", Edge.is_mainline == True,
            )
        )
        mainline_edge = mainline_edge_result.scalar_one_or_none()
        current_id = mainline_edge.to_node_id if mainline_edge else None

    return {"path": path}


@router.get("/projects/{project_id}/branch-roots", response_model=list[BranchInfo])
async def get_branch_roots(project_id: str, db: AsyncSession = Depends(get_db)):
    """Find all nodes with more than one child (branch points)."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    branch_query = (
        select(Edge.from_node_id, func.count().label("cnt"))
        .where(Edge.project_id == project_id, Edge.relation_type == "child_of")
        .group_by(Edge.from_node_id)
        .having(func.count() > 1)
    )
    result = await db.execute(branch_query)
    branch_parents = result.all()

    branches: list[dict] = []
    for row in branch_parents:
        parent_id = row[0]
        parent_node = await db.get(Node, parent_id)
        if not parent_node:
            continue
        child_edges_result = await db.execute(
            select(Edge).where(Edge.from_node_id == parent_id, Edge.relation_type == "child_of")
        )
        child_edges = child_edges_result.scalars().all()
        mainline_child_id = None
        branch_child_ids: list[str] = []
        for e in child_edges:
            if e.is_mainline:
                mainline_child_id = e.to_node_id
            else:
                branch_child_ids.append(e.to_node_id)
        branches.append({
            "node_id": parent_id, "title": parent_node.title,
            "mainline_child_id": mainline_child_id,
            "branch_child_ids": branch_child_ids,
            "total_children": len(child_edges),
        })

    return branches


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

    counts = (
        await db.execute(
            select(
                select(func.count()).select_from(ContentBlock).where(ContentBlock.node_id == node_id).scalar_subquery(),
                select(func.count()).select_from(Edge).where(
                    Edge.from_node_id == node_id,
                    Edge.relation_type == "child_of"
                ).scalar_subquery(),
            )
        )
    ).one()
    block_count = counts[0] or 0
    child_count = counts[1] or 0

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
    """Export entire project tree as Markdown document (bulk-loaded)."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.root_node_id:
        raise HTTPException(404, "No root node")

    # Bulk load all nodes, edges, blocks for this project
    nodes_result = await db.execute(select(Node).where(Node.project_id == project_id))
    nodes_by_id = {str(n.id): n for n in nodes_result.scalars().all()}

    edges_result = await db.execute(
        select(Edge.from_node_id, Edge.to_node_id).where(
            Edge.project_id == project_id, Edge.relation_type == "child_of"
        )
    )
    child_map: dict[str, list[str]] = {}
    for from_id, to_id in edges_result.all():
        child_map.setdefault(str(from_id), []).append(str(to_id))

    all_node_ids = list(nodes_by_id.keys())
    blocks_by_node: dict[str, list] = {}
    if all_node_ids:
        blocks_result = await db.execute(
            select(ContentBlock).where(ContentBlock.node_id.in_(all_node_ids)).order_by(ContentBlock.node_id, ContentBlock.order_index)
        )
        for b in blocks_result.scalars().all():
            blocks_by_node.setdefault(str(b.node_id), []).append(b)

    lines = [f"# {project.name}\n"]
    if project.description:
        lines.append(f"_{project.description}_\n")
    if project.goal:
        lines.append(f"**目標**: {project.goal}\n")
    lines.append("---\n")

    visited: set[str] = set()

    def render_node(nid: str, depth: int = 0):
        if nid in visited or nid not in nodes_by_id:
            return
        visited.add(nid)
        n = nodes_by_id[nid]
        prefix = "#" * min(depth + 2, 6)
        maturity_badge = {"seed": "🌱", "rough": "🪨", "developing": "🔧", "stable": "✅", "finalized": "🏆"}.get(n.maturity, "")
        lines.append(f"{prefix} {maturity_badge} {n.title}\n")
        if n.summary:
            lines.append(f"{n.summary}\n")

        for b in blocks_by_node.get(nid, []):
            content = b.content or {}
            title = content.get("title", "")
            body = content.get("body", "")
            lines.append(f"**[{b.block_type}] {title}**\n")
            if body:
                lines.append(f"{body}\n")

        if n.maturity == "seed":
            lines.append("_⏳ 待展開_\n")

        for cid in child_map.get(nid, []):
            render_node(cid, depth + 1)

    render_node(str(project.root_node_id))
    return "\n".join(lines)
