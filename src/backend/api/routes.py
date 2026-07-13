"""Project & Node API routes"""
import uuid
import json
import shutil
import os
import re
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.database import get_db
from models.models import Project, Node, Edge, ContentBlock, ActionLog, Branch, ProviderConfig, AgentSession, AgentArtifact
from models.schemas import (
    ProjectCreate, ProjectUpdate, ProjectOut,
    NodeCreate, NodeUpdate, NodeOut, NodeBrief,
    EdgeCreate, EdgeUpdate, EdgeOut,
    ContentBlockCreate, ContentBlockUpdate, ContentBlockOut,
    NodeMoveRequest, AncestorNode, MainlinePathOut, BranchInfo,
    BranchCreate, BranchOut,
    ProviderConfigCreate, ProviderConfigUpdate, ProviderConfigOut,
    AgentSessionCreate, AgentSessionUpdate, AgentSessionOut,
    AgentArtifactCreate, AgentArtifactReview, AgentArtifactOut,
)

router = APIRouter()


def backup_db():
    """Backup growthmap.db before destructive operations."""
    try:
        if os.path.exists("growthmap.db"):
            shutil.copy2("growthmap.db", "growthmap.db.bak")
    except Exception:
        pass  # Don't fail operations due to backup issues


def touch_project(project: Project | None):
    if project:
        project.updated_at = datetime.now(timezone.utc)


# ─── Provider configurations ───

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = Path(os.getenv("GROWTHMAP_ENV_FILE", str(PROJECT_ROOT / ".env")))
SAFE_ENV_KEY = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")


class ProviderSecretWrite(BaseModel):
    api_key: str


def _write_env_value(env_key: str, secret: str) -> None:
    """Atomically update one local .env value while preserving other entries."""
    if not SAFE_ENV_KEY.fullmatch(env_key):
        raise HTTPException(400, "Invalid environment variable name")
    if not secret or "\x00" in secret:
        raise HTTPException(400, "API key is required")
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    assignment = f"{env_key}={json.dumps(secret)}"
    updated: list[str] = []
    found = False
    for line in lines:
        if re.match(rf"^\s*(?:export\s+)?{re.escape(env_key)}\s*=", line):
            updated.append(assignment)
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(assignment)
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=ENV_FILE.parent, delete=False) as handle:
        handle.write("\n".join(updated).rstrip() + "\n")
        temp_path = Path(handle.name)
    os.chmod(temp_path, 0o600)
    temp_path.replace(ENV_FILE)
    os.environ[env_key] = secret


@router.get("/providers", response_model=list[ProviderConfigOut])
async def list_providers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProviderConfig).order_by(ProviderConfig.created_at.desc()))
    return result.scalars().all()


@router.post("/providers", response_model=ProviderConfigOut, status_code=201)
async def create_provider(data: ProviderConfigCreate, db: AsyncSession = Depends(get_db)):
    provider = ProviderConfig(**data.model_dump(), auth_type="env")
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


@router.put("/providers/{provider_id}/secret", status_code=204)
async def write_provider_secret(provider_id: str, data: ProviderSecretWrite, request: Request, db: AsyncSession = Depends(get_db)):
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}: # testclient is FastAPI's in-process test transport
        raise HTTPException(403, "Provider secrets can only be configured from localhost")
    provider = await db.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    if provider.provider_type == "mock":
        raise HTTPException(400, "Mock provider does not use an API key")
    _write_env_value(provider.secret_env_key, data.api_key)


@router.patch("/providers/{provider_id}", response_model=ProviderConfigOut)
async def update_provider(provider_id: str, data: ProviderConfigUpdate, db: AsyncSession = Depends(get_db)):
    provider = await db.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(provider, key, value)
    provider.auth_type = "env"
    await db.commit()
    await db.refresh(provider)
    return provider


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: str, db: AsyncSession = Depends(get_db)):
    provider = await db.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    await db.delete(provider)
    await db.commit()


# ─── Agent sessions (manual workflow only; no external dispatch) ───

AGENT_SESSION_STATUSES = {"idle", "active", "waiting_review", "completed", "cancelled"}
AGENT_SESSION_TRANSITIONS = {
    "idle": {"active", "cancelled"},
    "active": {"waiting_review", "completed", "cancelled"},
    "waiting_review": {"active", "completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


@router.get("/agent-sessions", response_model=list[AgentSessionOut])
async def list_agent_sessions(project_id: str, status: str | None = None, db: AsyncSession = Depends(get_db)):
    query = select(AgentSession).where(AgentSession.project_id == project_id)
    if status:
        if status not in AGENT_SESSION_STATUSES:
            raise HTTPException(400, "Invalid agent session status")
        query = query.where(AgentSession.status == status)
    result = await db.execute(query.order_by(AgentSession.updated_at.desc()))
    return result.scalars().all()


@router.post("/agent-sessions", response_model=AgentSessionOut, status_code=201)
async def create_agent_session(data: AgentSessionCreate, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, data.project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not data.objective.strip():
        raise HTTPException(400, "Objective is required")
    if data.mode not in {"one_shot", "collab", "background"}:
        raise HTTPException(400, "Invalid agent session mode")
    if bool(data.assigned_node_id) == bool(data.assigned_branch_root_id):
        raise HTTPException(400, "Assign exactly one node or branch root")
    if data.assigned_node_id:
        node = await db.get(Node, data.assigned_node_id)
        if not node or node.project_id != project.id:
            raise HTTPException(400, "Assigned node must belong to the project")
    if data.assigned_branch_root_id:
        root = await db.get(Node, data.assigned_branch_root_id)
        branch = await db.get(Branch, root.branch_id) if root and root.branch_id else None
        if not root or root.project_id != project.id or not branch or branch.status != "active":
            raise HTTPException(400, "Assigned branch root must belong to an active branch")
    if data.provider_id:
        provider = await db.get(ProviderConfig, data.provider_id)
        if not provider or not provider.enabled:
            raise HTTPException(400, "Selected provider is unavailable")
    session = AgentSession(**data.model_dump(), status="idle")
    db.add(session)
    await db.flush()
    db.add(ActionLog(project_id=project.id, node_id=data.assigned_node_id or data.assigned_branch_root_id, actor_type="human", action_type="agent_session_created", payload={"session_id": session.id, "mode": session.mode, "provider_id": session.provider_id}))
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/agent-sessions/{session_id}/history")
async def get_agent_session_history(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await db.get(AgentSession, session_id)
    if not session:
        raise HTTPException(404, "Agent session not found")
    result = await db.execute(
        select(ActionLog)
        .where(ActionLog.project_id == session.project_id, ActionLog.payload["session_id"].as_string() == session_id)
        .order_by(ActionLog.created_at.desc())
    )
    return [{"id": log.id, "action_type": log.action_type, "actor_type": log.actor_type, "payload": log.payload, "created_at": log.created_at.isoformat() if log.created_at else ""} for log in result.scalars().all()]


@router.patch("/agent-sessions/{session_id}", response_model=AgentSessionOut)
async def update_agent_session(session_id: str, data: AgentSessionUpdate, db: AsyncSession = Depends(get_db)):
    session = await db.get(AgentSession, session_id)
    if not session:
        raise HTTPException(404, "Agent session not found")
    changes = data.model_dump(exclude_unset=True)
    new_status = changes.pop("status", None)
    if new_status:
        if new_status not in AGENT_SESSION_STATUSES:
            raise HTTPException(400, "Invalid agent session status")
        if new_status != session.status and new_status not in AGENT_SESSION_TRANSITIONS[session.status]:
            raise HTTPException(400, f"Cannot transition from {session.status} to {new_status}")
        session.status = new_status
        if new_status == "active":
            session.last_heartbeat_at = datetime.now(timezone.utc)
    if "result_summary" in changes and session.status not in {"waiting_review", "completed", "cancelled"}:
        raise HTTPException(400, "Result summary requires review or terminal status")
    for key, value in changes.items():
        setattr(session, key, value)
    db.add(ActionLog(project_id=session.project_id, node_id=session.assigned_node_id or session.assigned_branch_root_id, actor_type="human", action_type="agent_session_updated", payload={"session_id": session.id, "status": session.status, "has_result_summary": bool(session.result_summary)}))
    await db.commit()
    await db.refresh(session)
    return session


# ─── Agent artifacts (manual review/writeback; no automatic execution) ───

ARTIFACT_TYPES = {"create_child", "update_node", "create_block"}


def _valid_artifact_payload(artifact_type: str, payload: dict) -> bool:
    if artifact_type == "create_child":
        return isinstance(payload.get("title"), str) and bool(payload["title"].strip())
    if artifact_type == "update_node":
        return bool(set(payload).intersection({"title", "summary", "description", "maturity", "tags"}))
    if artifact_type == "create_block":
        return isinstance(payload.get("block_type"), str) and isinstance(payload.get("content"), dict)
    return False


@router.get("/agent-sessions/{session_id}/artifacts", response_model=list[AgentArtifactOut])
async def list_agent_artifacts(session_id: str, status: str | None = None, db: AsyncSession = Depends(get_db)):
    session = await db.get(AgentSession, session_id)
    if not session:
        raise HTTPException(404, "Agent session not found")
    query = select(AgentArtifact).where(AgentArtifact.session_id == session_id)
    if status:
        if status not in {"pending", "applied", "rejected"}:
            raise HTTPException(400, "Invalid artifact status")
        query = query.where(AgentArtifact.status == status)
    result = await db.execute(query.order_by(AgentArtifact.created_at.desc()))
    return result.scalars().all()


@router.post("/agent-sessions/{session_id}/artifacts", response_model=AgentArtifactOut, status_code=201)
async def create_agent_artifact(session_id: str, data: AgentArtifactCreate, db: AsyncSession = Depends(get_db)):
    session = await db.get(AgentSession, session_id)
    if not session:
        raise HTTPException(404, "Agent session not found")
    if session.status not in {"active", "waiting_review"}:
        raise HTTPException(400, "Artifacts require an active or review session")
    if data.artifact_type not in ARTIFACT_TYPES or not _valid_artifact_payload(data.artifact_type, data.payload):
        raise HTTPException(400, "Invalid artifact payload")
    target = await db.get(Node, data.target_node_id)
    if not target or target.project_id != session.project_id:
        raise HTTPException(400, "Target node must belong to the session project")
    if session.assigned_node_id and data.target_node_id != session.assigned_node_id:
        raise HTTPException(400, "Node-scoped session can only write back to its assigned node")
    if session.assigned_branch_root_id and target.branch_id != (await db.get(Node, session.assigned_branch_root_id)).branch_id:
        raise HTTPException(400, "Branch-scoped session target must belong to the assigned branch")
    artifact = AgentArtifact(session_id=session_id, project_id=session.project_id, target_node_id=data.target_node_id, artifact_type=data.artifact_type, payload=data.payload)
    db.add(artifact)
    await db.flush()
    db.add(ActionLog(project_id=session.project_id, node_id=data.target_node_id, actor_type="human", action_type="agent_artifact_created", payload={"session_id": session_id, "artifact_id": artifact.id, "artifact_type": artifact.artifact_type}))
    await db.commit()
    await db.refresh(artifact)
    return artifact


@router.post("/agent-artifacts/{artifact_id}/approve", response_model=AgentArtifactOut)
async def approve_agent_artifact(artifact_id: str, data: AgentArtifactReview, db: AsyncSession = Depends(get_db)):
    artifact = await db.get(AgentArtifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Agent artifact not found")
    if artifact.status != "pending":
        raise HTTPException(400, "Artifact has already been reviewed")
    session = await db.get(AgentSession, artifact.session_id)
    target = await db.get(Node, artifact.target_node_id)
    if not session or not target:
        raise HTTPException(400, "Artifact target is unavailable")
    if artifact.artifact_type == "create_child":
        child = Node(project_id=target.project_id, branch_id=target.branch_id, title=artifact.payload["title"].strip(), summary=artifact.payload.get("summary", ""), node_type=artifact.payload.get("node_type", "idea"), created_by="agent")
        db.add(child)
        await db.flush()
        count = (await db.execute(select(func.count()).select_from(Edge).where(Edge.from_node_id == target.id, Edge.relation_type == "child_of"))).scalar() or 0
        db.add(Edge(project_id=target.project_id, from_node_id=target.id, to_node_id=child.id, relation_type="child_of", is_mainline=count == 0))
    elif artifact.artifact_type == "update_node":
        for key in {"title", "summary", "description", "maturity", "tags"}.intersection(artifact.payload):
            setattr(target, key, artifact.payload[key])
        target.last_edited_by = "agent"
    else:
        block_count = (await db.execute(select(func.count()).select_from(ContentBlock).where(ContentBlock.node_id == target.id))).scalar() or 0
        db.add(ContentBlock(node_id=target.id, block_type=artifact.payload["block_type"], content=artifact.payload["content"], order_index=block_count, created_by="agent"))
    artifact.status = "applied"
    artifact.review_note = data.review_note
    artifact.reviewed_at = datetime.now(timezone.utc)
    project = await db.get(Project, artifact.project_id)
    touch_project(project)
    db.add(ActionLog(project_id=artifact.project_id, node_id=target.id, actor_type="human", action_type="agent_artifact_applied", payload={"session_id": session.id, "artifact_id": artifact.id, "artifact_type": artifact.artifact_type, "review_note": data.review_note}))
    await db.commit()
    await db.refresh(artifact)
    return artifact


@router.post("/agent-artifacts/{artifact_id}/reject", response_model=AgentArtifactOut)
async def reject_agent_artifact(artifact_id: str, data: AgentArtifactReview, db: AsyncSession = Depends(get_db)):
    artifact = await db.get(AgentArtifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Agent artifact not found")
    if artifact.status != "pending":
        raise HTTPException(400, "Artifact has already been reviewed")
    artifact.status = "rejected"
    artifact.review_note = data.review_note
    artifact.reviewed_at = datetime.now(timezone.utc)
    db.add(ActionLog(project_id=artifact.project_id, node_id=artifact.target_node_id, actor_type="human", action_type="agent_artifact_rejected", payload={"session_id": artifact.session_id, "artifact_id": artifact.id, "review_note": data.review_note}))
    await db.commit()
    await db.refresh(artifact)
    return artifact


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
    backup_db()
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

    branch = None
    if data.branch_id:
        branch = await db.get(Branch, data.branch_id)
        if not branch or branch.project_id != project_id or branch.status != "active":
            raise HTTPException(400, "Invalid active branch")

    node = Node(
        project_id=project_id,
        branch_id=data.branch_id,
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
        if (parent.branch_id or None) != (data.branch_id or None):
            raise HTTPException(400, "Parent and child must belong to the same branch")

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
    backup_db()
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
            "project_id": str(n.project_id),
            "branch_id": str(n.branch_id) if n.branch_id else None,
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

GRAPH_RELATION_TYPES = {"depends_on", "contradicts", "references", "supports", "blocks", "relates_to"}

@router.get("/projects/{project_id}/edges", response_model=list[EdgeOut])
async def list_project_edges(project_id: str, relation_type: str | None = None, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    query = select(Edge).where(Edge.project_id == project_id)
    if relation_type:
        query = query.where(Edge.relation_type == relation_type)
    result = await db.execute(query.order_by(Edge.created_at))
    return result.scalars().all()


@router.post("/edges", response_model=EdgeOut, status_code=201)
async def create_edge(data: EdgeCreate, db: AsyncSession = Depends(get_db)):
    from_node = await db.get(Node, data.from_node_id)
    to_node = await db.get(Node, data.to_node_id)
    if not from_node or not to_node:
        raise HTTPException(400, "Invalid node id")
    if from_node.project_id != to_node.project_id:
        raise HTTPException(400, "Nodes must be in same project")
    if data.from_node_id == data.to_node_id:
        raise HTTPException(400, "Cannot create a self-relation")
    if data.relation_type != "child_of" and data.relation_type not in GRAPH_RELATION_TYPES:
        raise HTTPException(400, "Unsupported graph relation type")
    duplicate = await db.execute(select(Edge).where(Edge.from_node_id == data.from_node_id, Edge.to_node_id == data.to_node_id, Edge.relation_type == data.relation_type))
    if duplicate.scalar_one_or_none():
        raise HTTPException(409, "Duplicate relation")

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


@router.patch("/edges/{edge_id}", response_model=EdgeOut)
async def update_edge(edge_id: str, data: EdgeUpdate, db: AsyncSession = Depends(get_db)):
    edge = await db.get(Edge, edge_id)
    if not edge:
        raise HTTPException(404, "Edge not found")
    if edge.relation_type == "child_of":
        raise HTTPException(400, "Tree parent relations cannot be edited as graph relations")
    values = data.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(400, "No edge fields provided")
    if "weight" in values and not 0 <= values["weight"] <= 1:
        raise HTTPException(400, "Weight must be between 0 and 1")
    if "note" in values and len(values["note"]) > 2000:
        raise HTTPException(400, "Note is too long")
    for key, value in values.items():
        setattr(edge, key, value)
    db.add(ActionLog(project_id=edge.project_id, node_id=edge.from_node_id, actor_type="human", action_type="graph_relation_updated", payload={"edge_id": edge.id, "changes": values}))
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
    if edge.relation_type == "child_of":
        raise HTTPException(400, "Tree parent relations must be changed through node move actions")
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

CONTENT_BLOCK_LABELS = {
    "note": "筆記",
    "spec": "規格",
    "decision": "決策",
    "todo": "待辦",
    "risk": "風險",
    "paragraph": "段落",
    "resource": "文件",
    "document": "文件",
    "file": "文件",
}
DOC_BLOCK_TYPES = {"resource", "document", "file"}


def _block_content(block):
    return block.content if isinstance(block.content, dict) else {}


def _render_content_blocks(blocks: list, heading_level: str = "###") -> list[str]:
    lines: list[str] = []
    content_blocks = [b for b in blocks if b.block_type not in DOC_BLOCK_TYPES]
    if not content_blocks:
        return lines
    lines.append(f"{heading_level} 內容區塊")
    for b in content_blocks:
        content = _block_content(b)
        label = CONTENT_BLOCK_LABELS.get(b.block_type, b.block_type)
        title = content.get("title") or label
        body = content.get("body") or content.get("summary") or ""
        lines.append(f"- **{label}｜{title}**")
        if body:
            for line in str(body).splitlines():
                lines.append(f"  {line}" if line else "")
    lines.append("")
    return lines


def _render_bound_docs(blocks: list, heading_level: str = "###") -> list[str]:
    lines: list[str] = []
    docs = [b for b in blocks if b.block_type in DOC_BLOCK_TYPES]
    if not docs:
        return lines
    lines.append(f"{heading_level} 綁定文件")
    for b in docs:
        content = _block_content(b)
        title = content.get("title") or content.get("name") or content.get("filename") or content.get("url") or content.get("path") or "未命名文件"
        href = content.get("url") or content.get("path") or ""
        summary = content.get("summary") or content.get("body") or ""
        if href:
            lines.append(f"- [{title}]({href})")
        else:
            lines.append(f"- {title}")
        if summary:
            lines.append(f"  - {summary}")
    lines.append("")
    return lines

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

        node_blocks = blocks_by_node.get(nid, [])
        lines.extend(_render_content_blocks(node_blocks, heading_level="#" * min(depth + 3, 6)))
        lines.extend(_render_bound_docs(node_blocks, heading_level="#" * min(depth + 3, 6)))

        if n.maturity == "seed":
            lines.append("_⏳ 待展開_\n")

        for cid in child_map.get(nid, []):
            render_node(cid, depth + 1)

    render_node(str(project.root_node_id))
    return "\n".join(lines)


@router.get("/projects/{project_id}/actions")
async def list_project_actions(project_id: str, limit: int = 5, db: AsyncSession = Depends(get_db)):
    """List recent actions for a project."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    result = await db.execute(
        select(ActionLog)
        .where(ActionLog.project_id == project_id)
        .order_by(ActionLog.created_at.desc())
        .limit(limit)
    )
    actions = result.scalars().all()
    return [
        {
            "id": str(a.id),
            "action_type": a.action_type,
            "actor_type": a.actor_type,
            "node_id": str(a.node_id) if a.node_id else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in actions
    ]


# ─── Reparent ───

@router.post("/nodes/{node_id}/reparent")
async def reparent_node(node_id: str, body: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """Reparent a node to a new parent via drag-and-drop."""
    new_parent_id = body.get("new_parent_id")
    if not new_parent_id:
        raise HTTPException(400, "new_parent_id required")

    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")

    project = await db.get(Project, node.project_id)
    if project and project.root_node_id == node_id:
        raise HTTPException(400, "Cannot reparent root node")

    new_parent = await db.get(Node, new_parent_id)
    if not new_parent or new_parent.project_id != node.project_id:
        raise HTTPException(400, "Invalid new parent")

    # Cycle detection
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

    if new_parent_id in descendants or new_parent_id == node_id:
        raise HTTPException(400, "Cannot reparent under descendant (cycle)")

    # Remove old child_of edge
    old_edge_result = await db.execute(
        select(Edge).where(Edge.to_node_id == node_id, Edge.relation_type == "child_of")
    )
    old_edge = old_edge_result.scalar_one_or_none()
    if old_edge:
        await db.delete(old_edge)

    # Determine mainline
    existing_children = (await db.execute(
        select(func.count()).select_from(Edge).where(
            Edge.from_node_id == new_parent_id, Edge.relation_type == "child_of"
        )
    )).scalar() or 0

    new_edge = Edge(
        project_id=node.project_id,
        from_node_id=new_parent_id,
        to_node_id=node_id,
        relation_type="child_of",
        is_mainline=existing_children == 0,
    )
    db.add(new_edge)
    touch_project(project)
    await db.commit()
    return {"ok": True}


# ─── Import / Export JSON ───

@router.get("/projects/{project_id}/export-json")
async def export_project_json(project_id: str, db: AsyncSession = Depends(get_db)):
    """Export entire project as JSON (all nodes, edges, content blocks, action logs)."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    nodes_result = await db.execute(select(Node).where(Node.project_id == project_id))
    nodes = nodes_result.scalars().all()

    edges_result = await db.execute(select(Edge).where(Edge.project_id == project_id))
    edges = edges_result.scalars().all()

    node_ids = [str(n.id) for n in nodes]
    blocks_result = await db.execute(
        select(ContentBlock).where(ContentBlock.node_id.in_(node_ids))
    ) if node_ids else None
    blocks = blocks_result.scalars().all() if blocks_result else []

    logs_result = await db.execute(
        select(ActionLog).where(ActionLog.project_id == project_id).order_by(ActionLog.created_at.desc()).limit(200)
    )
    logs = logs_result.scalars().all()

    return {
        "version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "project": {
            "id": str(project.id),
            "name": project.name,
            "description": project.description,
            "goal": project.goal,
            "root_node_id": str(project.root_node_id) if project.root_node_id else None,
            "status": project.status,
            "settings": project.settings,
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        },
        "nodes": [
            {
                "id": str(n.id),
                "title": n.title,
                "summary": n.summary,
                "node_type": n.node_type,
                "status": n.status,
                "maturity": n.maturity,
                "tags": n.tags,
                "description": n.description,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "updated_at": n.updated_at.isoformat() if n.updated_at else None,
            }
            for n in nodes
        ],
        "edges": [
            {
                "id": str(e.id),
                "from_node_id": str(e.from_node_id),
                "to_node_id": str(e.to_node_id),
                "relation_type": e.relation_type,
                "is_mainline": e.is_mainline,
            }
            for e in edges
        ],
        "content_blocks": [
            {
                "id": str(b.id),
                "node_id": str(b.node_id),
                "block_type": b.block_type,
                "content": b.content,
                "order_index": b.order_index,
            }
            for b in blocks
        ],
        "action_logs": [
            {
                "id": str(a.id),
                "node_id": str(a.node_id) if a.node_id else None,
                "actor_type": a.actor_type,
                "action_type": a.action_type,
                "payload": a.payload,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in logs
        ],
    }


@router.post("/projects/import-json", response_model=None, status_code=201)
async def import_project_json(data: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """Import a project from JSON export. Creates new project with new IDs."""
    proj_data = data.get("project", {})
    nodes_data = data.get("nodes", [])
    edges_data = data.get("edges", [])
    blocks_data = data.get("content_blocks", [])

    # Create new project
    new_project = Project(
        name=proj_data.get("name", "匯入的專案"),
        description=proj_data.get("description"),
        goal=proj_data.get("goal"),
        status=proj_data.get("status", "active"),
        settings=proj_data.get("settings", {}),
    )
    db.add(new_project)
    await db.flush()

    # Map old IDs to new IDs
    old_root_id = proj_data.get("root_node_id")
    id_map: dict[str, str] = {}

    for n in nodes_data:
        new_node = Node(
            project_id=new_project.id,
            title=n.get("title", ""),
            summary=n.get("summary"),
            node_type=n.get("node_type", "idea"),
            status=n.get("status", "active"),
            maturity=n.get("maturity", "seed"),
            tags=n.get("tags", []),
            description=n.get("description"),
            created_by="import",
        )
        db.add(new_node)
        await db.flush()
        id_map[n["id"]] = str(new_node.id)

    # Set root
    if old_root_id and old_root_id in id_map:
        new_project.root_node_id = id_map[old_root_id]

    for e in edges_data:
        from_id = id_map.get(e.get("from_node_id", ""))
        to_id = id_map.get(e.get("to_node_id", ""))
        if not from_id or not to_id:
            continue
        new_edge = Edge(
            project_id=new_project.id,
            from_node_id=from_id,
            to_node_id=to_id,
            relation_type=e.get("relation_type", "child_of"),
            is_mainline=e.get("is_mainline", False),
        )
        db.add(new_edge)

    for b in blocks_data:
        node_id_mapped = id_map.get(b.get("node_id", ""))
        if not node_id_mapped:
            continue
        new_block = ContentBlock(
            node_id=node_id_mapped,
            block_type=b.get("block_type", "note"),
            content=b.get("content", {}),
            order_index=b.get("order_index", 0),
        )
        db.add(new_block)

    db.add(ActionLog(
        project_id=new_project.id,
        actor_type="human",
        action_type="import_project",
        payload={"original_name": proj_data.get("name")},
    ))
    await db.commit()
    await db.refresh(new_project)
    return {"id": str(new_project.id), "name": new_project.name, "root_node_id": str(new_project.root_node_id) if new_project.root_node_id else None}


# ─── Spec Export ───

@router.get("/projects/{project_id}/export-spec", response_class=PlainTextResponse)
async def export_spec(project_id: str, db: AsyncSession = Depends(get_db)):
    """Export project as a structured spec Markdown document."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.root_node_id:
        raise HTTPException(404, "No root node")

    from datetime import date
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

    # Build TOC and content
    toc_lines: list[str] = []
    content_lines: list[str] = []
    visited: set[str] = set()

    def render_spec_node(nid: str, depth: int = 0):
        if nid in visited or nid not in nodes_by_id:
            return
        visited.add(nid)
        n = nodes_by_id[nid]
        prefix = "#" * min(depth + 2, 6)
        indent = "  " * depth
        anchor = n.title.lower().replace(" ", "-").replace("（", "").replace("）", "")
        toc_lines.append(f"{indent}- [{n.title}](#{anchor})")

        if n.maturity in ("stable", "finalized"):
            content_lines.append(f"{prefix} {n.title}")
            if n.summary:
                content_lines.append(f"\n{n.summary}\n")
            node_blocks = blocks_by_node.get(nid, [])
            content_lines.extend(_render_content_blocks(node_blocks, heading_level="###"))
            content_lines.extend(_render_bound_docs(node_blocks, heading_level="###"))
        else:
            content_lines.append(f"{prefix} {n.title} （🚧 開發中）")
            if n.summary:
                content_lines.append(f"\n{n.summary}\n")
            node_blocks = blocks_by_node.get(nid, [])
            content_lines.extend(_render_content_blocks(node_blocks, heading_level="###"))
            content_lines.extend(_render_bound_docs(node_blocks, heading_level="###"))

        for cid in child_map.get(nid, []):
            render_spec_node(cid, depth + 1)

    render_spec_node(str(project.root_node_id))

    header = [
        f"# {project.name} — 規格文件",
        "",
        f"**描述**：{project.description}" if project.description else "",
        f"**目標**：{project.goal}" if project.goal else "",
        f"**匯出日期**：{date.today().isoformat()}",
        "",
        "---",
        "",
        "## 目錄",
        "",
        *toc_lines,
        "",
        "---",
        "",
    ]
    lines = header + content_lines
    return "\n".join(l for l in lines if l is not None)


# ─── Git-like Branches ───

@router.post("/projects/{project_id}/branches", response_model=BranchOut, status_code=201)
async def create_branch(project_id: str, data: BranchCreate, db: AsyncSession = Depends(get_db)):
    """Create a branch by deep-copying source node and all its descendants."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    source_node = await db.get(Node, data.source_node_id)
    if not source_node or source_node.project_id != project_id:
        raise HTTPException(400, "Invalid source node")

    # Create branch record
    branch = Branch(
        project_id=project_id,
        name=data.name,
        description=data.description,
        source_node_id=data.source_node_id,
        status="active",
    )
    db.add(branch)
    await db.flush()

    # Load all edges for this project
    edges_result = await db.execute(
        select(Edge).where(Edge.project_id == project_id, Edge.relation_type == "child_of")
    )
    all_edges = edges_result.scalars().all()
    child_map_all: dict[str, list[str]] = {}
    for e in all_edges:
        child_map_all.setdefault(str(e.from_node_id), []).append(str(e.to_node_id))

    # Collect all nodes in subtree
    subtree_ids: list[str] = []
    frontier = [data.source_node_id]
    while frontier:
        nid = frontier.pop()
        subtree_ids.append(nid)
        for cid in child_map_all.get(nid, []):
            if cid not in subtree_ids:
                frontier.append(cid)

    # Load all subtree nodes
    nodes_result = await db.execute(select(Node).where(Node.id.in_(subtree_ids)))
    subtree_nodes = {str(n.id): n for n in nodes_result.scalars().all()}

    # Load blocks
    blocks_result = await db.execute(
        select(ContentBlock).where(ContentBlock.node_id.in_(subtree_ids))
    )
    blocks_by_node: dict[str, list] = {}
    for b in blocks_result.scalars().all():
        blocks_by_node.setdefault(str(b.node_id), []).append(b)

    # Deep copy: create id mapping
    id_map: dict[str, str] = {}
    for old_id in subtree_ids:
        new_node_id = str(uuid.uuid4())
        id_map[old_id] = new_node_id

    # Create new nodes
    for old_id, old_node in subtree_nodes.items():
        new_id = id_map[old_id]
        copied = Node(
            id=new_id,
            project_id=project_id,
            title=old_node.title,
            summary=old_node.summary,
            node_type=old_node.node_type,
            status=old_node.status,
            maturity=old_node.maturity,
            tags=old_node.tags or [],
            description=old_node.description,
            rules_text=old_node.rules_text,
            constraints_text=old_node.constraints_text,
            examples_text=old_node.examples_text,
            questions_text=old_node.questions_text,
            decision_notes=old_node.decision_notes,
            priority=old_node.priority,
            confidence=old_node.confidence,
            created_by="branch",
            branch_id=branch.id,
        )
        db.add(copied)
        # Copy blocks
        for b in blocks_by_node.get(old_id, []):
            db.add(ContentBlock(
                node_id=new_id,
                block_type=b.block_type,
                content=b.content,
                order_index=b.order_index,
                created_by="branch",
            ))

    await db.flush()

    # Create new edges mirroring original structure (child_of only within subtree)
    for old_from, old_tos in child_map_all.items():
        if old_from not in id_map:
            continue
        for old_to in old_tos:
            if old_to not in id_map:
                continue
            db.add(Edge(
                project_id=project_id,
                from_node_id=id_map[old_from],
                to_node_id=id_map[old_to],
                relation_type="child_of",
                is_mainline=True,
            ))

    db.add(ActionLog(
        project_id=project_id,
        actor_type="human",
        action_type="create_branch",
        payload={"branch_name": data.name, "source_node_id": data.source_node_id},
    ))
    await db.commit()
    await db.refresh(branch)
    return branch


@router.get("/projects/{project_id}/branches", response_model=list[BranchOut])
async def list_branches(project_id: str, include_inactive: bool = False, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    query = select(Branch).where(Branch.project_id == project_id)
    if not include_inactive:
        query = query.where(Branch.status == "active")
    result = await db.execute(query.order_by(Branch.created_at.desc()))
    return result.scalars().all()


@router.get("/branches/{branch_id}", response_model=BranchOut)
async def get_branch(branch_id: str, db: AsyncSession = Depends(get_db)):
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(404, "Branch not found")
    return branch


@router.get("/branches/{branch_id}/subtree")
async def get_branch_subtree(branch_id: str, db: AsyncSession = Depends(get_db)):
    """Get the full subtree of branch nodes."""
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(404, "Branch not found")

    # Find the root node of this branch (branch root = node with branch_id set and no parent within branch)
    branch_nodes_result = await db.execute(
        select(Node).where(Node.branch_id == branch_id, Node.project_id == branch.project_id)
    )
    branch_nodes = branch_nodes_result.scalars().all()
    if not branch_nodes:
        return {"id": branch_id, "name": branch.name, "nodes": []}

    branch_node_ids = {str(n.id) for n in branch_nodes}
    # Build child map for branch nodes
    edges_result = await db.execute(
        select(Edge).where(
            Edge.project_id == branch.project_id,
            Edge.from_node_id.in_(branch_node_ids),
            Edge.relation_type == "child_of"
        )
    )
    child_map: dict[str, list[str]] = {}
    child_ids: set[str] = set()
    for e in edges_result.scalars().all():
        child_map.setdefault(str(e.from_node_id), []).append(str(e.to_node_id))
        child_ids.add(str(e.to_node_id))

    # Find root: branch node with no parent within branch
    root_id = None
    for n in branch_nodes:
        if str(n.id) not in child_ids:
            root_id = str(n.id)
            break

    nodes_by_id = {str(n.id): n for n in branch_nodes}

    def build_tree(nid: str) -> dict:
        n = nodes_by_id.get(nid)
        if not n:
            return {}
        return {
            "id": str(n.id),
            "project_id": str(n.project_id),
            "title": n.title,
            "summary": n.summary,
            "node_type": n.node_type,
            "status": n.status,
            "maturity": n.maturity,
            "tags": n.tags or [],
            "meta": {},
            "content_blocks": [],
            "branch_id": n.branch_id,
            "created_at": n.created_at.isoformat() if n.created_at else "",
            "updated_at": n.updated_at.isoformat() if n.updated_at else "",
            "children": [build_tree(cid) for cid in child_map.get(nid, []) if cid in nodes_by_id],
        }

    return {"branch": {"id": branch.id, "name": branch.name, "status": branch.status}, "tree": build_tree(root_id) if root_id else None}


@router.get("/branches/{branch_id}/history")
async def get_branch_history(branch_id: str, limit: int = 20, db: AsyncSession = Depends(get_db)):
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(404, "Branch not found")

    result = await db.execute(
        select(ActionLog)
        .where(
            ActionLog.project_id == branch.project_id,
            or_(
                ActionLog.payload["branch_id"].as_string() == branch_id,
                ActionLog.payload["branch_name"].as_string() == branch.name,
            )
        )
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


@router.get("/branches/{branch_id}/compare")
async def compare_branch(branch_id: str, db: AsyncSession = Depends(get_db)):
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(404, "Branch not found")

    source_node = await db.get(Node, branch.source_node_id)
    if not source_node:
        raise HTTPException(404, "Branch source node not found")

    branch_nodes_result = await db.execute(
        select(Node).where(Node.branch_id == branch_id, Node.project_id == branch.project_id)
    )
    branch_nodes = branch_nodes_result.scalars().all()
    branch_node_ids = {str(n.id) for n in branch_nodes}

    edges_result = await db.execute(
        select(Edge).where(
            Edge.project_id == branch.project_id,
            Edge.from_node_id.in_(branch_node_ids),
            Edge.relation_type == "child_of"
        )
    )
    child_ids: set[str] = {str(e.to_node_id) for e in edges_result.scalars().all()}
    branch_root = next((n for n in branch_nodes if str(n.id) not in child_ids), None)

    def summarize(node: Node | None):
        if not node:
            return None
        return {
            "id": str(node.id),
            "title": node.title,
            "summary": node.summary,
            "node_type": node.node_type,
            "maturity": node.maturity,
            "updated_at": node.updated_at.isoformat() if node.updated_at else None,
        }

    source_blocks = (await db.execute(
        select(func.count()).select_from(ContentBlock).where(ContentBlock.node_id == source_node.id)
    )).scalar() or 0
    branch_blocks = 0
    if branch_root:
        branch_blocks = (await db.execute(
            select(func.count()).select_from(ContentBlock).where(ContentBlock.node_id == branch_root.id)
        )).scalar() or 0

    return {
        "branch": {"id": branch.id, "name": branch.name, "status": branch.status},
        "source": summarize(source_node),
        "branch_root": summarize(branch_root),
        "diff": {
            "title_changed": bool(branch_root and branch_root.title != source_node.title),
            "summary_changed": bool(branch_root and (branch_root.summary or "") != (source_node.summary or "")),
            "maturity_changed": bool(branch_root and branch_root.maturity != source_node.maturity),
            "source_block_count": source_blocks,
            "branch_block_count": branch_blocks,
            "branch_node_count": len(branch_nodes),
        },
    }


@router.get("/projects/{project_id}/branches/ranking")
async def rank_branches(project_id: str, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    result = await db.execute(
        select(Branch).where(Branch.project_id == project_id, Branch.status == "active").order_by(Branch.created_at.desc())
    )
    branches = result.scalars().all()

    ranked = []
    for branch in branches:
        nodes_result = await db.execute(select(Node).where(Node.branch_id == branch.id))
        nodes = nodes_result.scalars().all()
        node_ids = [str(n.id) for n in nodes]
        block_count = 0
        if node_ids:
            block_count = (await db.execute(
                select(func.count()).select_from(ContentBlock).where(ContentBlock.node_id.in_(node_ids))
            )).scalar() or 0
        ranked.append({
            "branch_id": str(branch.id),
            "name": branch.name,
            "status": branch.status,
            "node_count": len(nodes),
            "block_count": block_count,
            "score": len(nodes) * 10 + block_count,
            "created_at": branch.created_at.isoformat() if branch.created_at else None,
        })

    ranked.sort(key=lambda x: (-x["score"], x["created_at"] or ""))
    return ranked


@router.post("/branches/{branch_id}/merge")
async def merge_branch(branch_id: str, body: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """Merge branch by re-parenting branch root under target node."""
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(404, "Branch not found")
    if branch.status != "active":
        raise HTTPException(400, "Only active branches can be merged")
    target_node_id = body.get("target_node_id")
    if not target_node_id:
        raise HTTPException(400, "target_node_id required")
    target_node = await db.get(Node, target_node_id)
    if not target_node or target_node.project_id != branch.project_id or target_node.branch_id:
        raise HTTPException(400, "Target node must be on this project mainline")

    # Find branch nodes
    branch_nodes_result = await db.execute(
        select(Node).where(Node.branch_id == branch_id)
    )
    branch_nodes = branch_nodes_result.scalars().all()
    branch_node_ids = {str(n.id) for n in branch_nodes}

    # Find branch root (no incoming child_of edge from another branch node)
    child_ids: set[str] = set()
    edges_result = await db.execute(
        select(Edge).where(Edge.from_node_id.in_(branch_node_ids), Edge.relation_type == "child_of")
    )
    for e in edges_result.scalars().all():
        child_ids.add(str(e.to_node_id))

    root_node_id = None
    for n in branch_nodes:
        if str(n.id) not in child_ids:
            root_node_id = str(n.id)
            break

    if not root_node_id:
        raise HTTPException(400, "Cannot find branch root")
    if target_node_id in branch_node_ids:
        raise HTTPException(400, "Cannot merge a branch into itself")

    # Clear branch_id from all nodes
    for n in branch_nodes:
        n.branch_id = None

    # Re-parent branch root under target
    root_node = await db.get(Node, root_node_id)
    if root_node:
        # Remove existing edge if any
        old_edge_result = await db.execute(
            select(Edge).where(Edge.to_node_id == root_node_id, Edge.relation_type == "child_of")
        )
        old_edge = old_edge_result.scalar_one_or_none()
        if old_edge:
            await db.delete(old_edge)

        existing_children = (await db.execute(
            select(func.count()).select_from(Edge).where(
                Edge.from_node_id == target_node_id, Edge.relation_type == "child_of"
            )
        )).scalar() or 0

        db.add(Edge(
            project_id=branch.project_id,
            from_node_id=target_node_id,
            to_node_id=root_node_id,
            relation_type="child_of",
            is_mainline=existing_children == 0,
        ))

    branch.status = "merged"
    project = await db.get(Project, branch.project_id)
    touch_project(project)
    db.add(ActionLog(
        project_id=branch.project_id,
        actor_type="human",
        action_type="merge_branch",
        payload={"branch_id": branch_id, "target_node_id": target_node_id},
    ))
    await db.commit()
    return {"ok": True}


@router.delete("/branches/{branch_id}", status_code=204)
async def archive_branch(branch_id: str, db: AsyncSession = Depends(get_db)):
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(404, "Branch not found")
    if branch.status != "active":
        raise HTTPException(400, "Only active branches can be archived")
    branch.status = "archived"
    project = await db.get(Project, branch.project_id)
    touch_project(project)
    db.add(ActionLog(
        project_id=branch.project_id,
        actor_type="human",
        action_type="archive_branch",
        payload={"branch_id": branch_id},
    ))
    await db.commit()

