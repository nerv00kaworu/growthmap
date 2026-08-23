"""Project & Node API routes"""
import uuid
import json
import shutil
import os
import re
import tempfile
import asyncio
from types import SimpleNamespace
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, update, exists
from sqlalchemy.exc import StatementError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.database import get_db
from models.models import Project, Node, Edge, ContentBlock, ActionLog, Branch, ProviderConfig, ProviderSelection, AgentSession, AgentArtifact
from models.content_blocks import CONTENT_BLOCK_TYPES
from desktop.entitlements import peek_current_entitlement
from desktop.secrets import desktop_mode, has as has_memory_secret, put as put_memory_secret, delete as delete_memory_secret
from api.revisions import claim_project_revision, check_entity_revision, bump_existing, TouchedEntities
from api.branching import deep_copy_branch
from api.provider_authority import guarded_provider_update, change_external_secret, recover_external_secret
from models.schemas import (
    ProjectCreate, ProjectUpdate, ProjectOut,
    NodeCreate, NodeUpdate, NodeOut, NodeBrief,
    EdgeCreate, EdgeUpdate, EdgeOut,
    ContentBlockCreate, ContentBlockUpdate, ContentBlockOut,
    NodeMoveRequest, AncestorNode, MainlinePathOut, BranchInfo,
    BranchCreate, BranchOut, ProjectRevisionRequest, EntityRevisionRequest,
    NodeEntityRevisionRequest, BranchMergeRequest,
    ProviderConfigCreate, ProviderConfigUpdate, ProviderModelUpdate, ProviderConfigOut, ProviderSecretRecovery,
    AgentSessionCreate, AgentSessionUpdate, AgentSessionOut,
    AgentArtifactCreate, AgentArtifactReview, AgentArtifactOut,
    validate_app_secret_env_key,
)

router = APIRouter()
# One desktop sidecar process serializes count+commit seat mutations. Reads,
# exports and archive operations do not acquire this lock.
_project_seat_lock = asyncio.Lock()

async def _require_active_project_seat(db: AsyncSession, *, conflict_status: int=402) -> None:
    entitlement=peek_current_entitlement()
    if desktop_mode() and entitlement.max_active_projects is not None:
        active=await db.scalar(select(func.count(Project.id)).where(Project.status == "active"))
        if active >= entitlement.max_active_projects:
            raise HTTPException(conflict_status, f"Active project limit reached ({active}/{entitlement.max_active_projects}); archive a project or import a matching-major license")


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
        project.revision = (project.revision or 1) + 1


def ordinary_main_nodes(project_id: str):
    """Canonical ordinary-project projection; branch views are explicit."""
    return select(Node).where(Node.project_id == project_id, Node.branch_id.is_(None))


# ─── Provider configurations ───

PROJECT_ROOT = Path(__file__).resolve().parents[3]
def _env_file() -> Path:
    return Path(os.getenv("GROWTHMAP_ENV_FILE", str(PROJECT_ROOT / ".env")))
SAFE_ENV_KEY = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")


class ProviderSecretWrite(BaseModel):
    api_key: str


def _write_env_value(env_key: str, secret: str) -> None:
    """Atomically update one local .env value while preserving other entries."""
    if desktop_mode():
        raise HTTPException(403, "Desktop mode forbids env-file secret writes; use secure desktop storage")
    try:
        validate_app_secret_env_key(env_key)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not secret or "\x00" in secret:
        raise HTTPException(400, "API key is required")
    env_file = _env_file()
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
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
    env_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=env_file.parent, delete=False) as handle:
        handle.write("\n".join(updated).rstrip() + "\n")
        temp_path = Path(handle.name)
    os.chmod(temp_path, 0o600)
    temp_path.replace(env_file)
    os.environ[env_key] = secret


def _delete_env_value(env_key: str) -> None:
    validate_app_secret_env_key(env_key)
    env_file = _env_file()
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    kept = [line for line in lines if not re.match(rf"^\s*(?:export\s+)?{re.escape(env_key)}\s*=", line)]
    env_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=env_file.parent, delete=False) as handle:
        handle.write("\n".join(kept).rstrip() + ("\n" if kept else ""))
        temp_path = Path(handle.name)
    os.chmod(temp_path, 0o600)
    temp_path.replace(env_file)
    os.environ.pop(env_key, None)


class ProviderSelectionWrite(BaseModel):
    expected_selection_revision: int = Field(ge=1, le=9007199254740991)
    provider_id: str | None

def _is_sqlite_busy(exc: OperationalError) -> bool:
    orig=getattr(exc,"orig",exc)
    code=getattr(orig,"sqlite_errorcode",None)
    # Extended result codes retain the primary code in the low byte.
    if isinstance(code,int) and (code & 0xFF) in {5,6}: return True
    message=str(orig).lower()
    return message in {"database is locked","database table is locked","database schema is locked","database is busy"} or "sqlite_busy" in message or "sqlite_locked" in message

async def _selection_busy(db: AsyncSession, exc: OperationalError):
    await db.rollback()
    if not _is_sqlite_busy(exc): raise exc
    raise HTTPException(503,detail={"code":"LLM_SELECTION_BUSY","message":"Selection is busy; retry shortly."},headers={"Retry-After":"1"}) from exc

async def _selection(db: AsyncSession) -> ProviderSelection:
    row=(await db.execute(select(ProviderSelection).where(ProviderSelection.singleton_id==1))).scalar_one_or_none()
    if not row: raise HTTPException(503,detail={"code":"LLM_SELECTION_UNAVAILABLE","message":"Selection authority is unavailable."})
    return row

async def _project_provider(db: AsyncSession, row: ProviderConfig) -> dict:
    return _provider_out(row, await _selection(db))

def _credential_status(row: ProviderConfig) -> str:
    if row.secret_change_pending: return "recovery_required"
    if row.provider_type == "mock": return "ready"
    if desktop_mode(): return "ready" if has_memory_secret(row.id) else "unavailable"
    key=row.secret_env_key
    return "ready" if isinstance(key,str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}",key) and bool(os.getenv(key)) else "unavailable"

def _provider_out(row: ProviderConfig, selection: ProviderSelection) -> dict:
    credential_status=_credential_status(row)
    return {name:getattr(row,name) for name in ProviderConfigOut.model_fields if name not in {"credential_status","is_default","selection_revision"}} | {"credential_status":credential_status,"is_default":row.id==selection.provider_id,"selection_revision":selection.selection_revision}

async def _clear_selection_for_provider(db: AsyncSession, provider_id: str) -> None:
    selection=await _selection(db)
    if selection.provider_id != provider_id: return
    if selection.selection_revision >= 9007199254740991:
        raise HTTPException(409,detail={"code":"LLM_SELECTION_REVISION_EXHAUSTED","message":"Selection revision exhausted."})
    result=await db.execute(update(ProviderSelection).where(ProviderSelection.singleton_id==1,ProviderSelection.provider_id==provider_id,ProviderSelection.selection_revision==selection.selection_revision,ProviderSelection.selection_revision<9007199254740991).values(provider_id=None,selection_revision=ProviderSelection.selection_revision+1,updated_at=datetime.now(timezone.utc)))
    if result.rowcount != 1: raise HTTPException(409,detail={"code":"LLM_SELECTION_STALE","message":"Selection changed; reload and retry."})

@router.get("/providers", response_model=list[ProviderConfigOut])
async def list_providers(db: AsyncSession = Depends(get_db)):
    selection=await _selection(db)
    rows=(await db.execute(select(ProviderConfig).order_by(ProviderConfig.created_at.desc()))).scalars().all()
    return [_provider_out(row,selection) for row in rows]

@router.put("/providers/selection")
async def set_provider_selection(data: ProviderSelectionWrite, db: AsyncSession = Depends(get_db)):
    try:
        if data.provider_id is not None:
            candidate=await db.get(ProviderConfig,data.provider_id)
            if candidate is None or not candidate.enabled or _credential_status(candidate)!="ready":
                raise HTTPException(409,detail={"code":"PROVIDER_UNAVAILABLE","message":"Only an enabled ready provider can be selected."})
        eligible=exists(select(ProviderConfig.id).where(ProviderConfig.id==data.provider_id,ProviderConfig.enabled.is_(True),ProviderConfig.secret_change_pending.is_(False)))
        result=await db.execute(update(ProviderSelection).where(ProviderSelection.singleton_id==1,ProviderSelection.selection_revision==data.expected_selection_revision,ProviderSelection.selection_revision<9007199254740991,True if data.provider_id is None else eligible).values(provider_id=data.provider_id,selection_revision=ProviderSelection.selection_revision+1,updated_at=datetime.now(timezone.utc)))
        if result.rowcount!=1:
            await db.rollback(); current=await _selection(db)
            if current.selection_revision != data.expected_selection_revision or current.selection_revision >= 9007199254740991:
                raise HTTPException(409,detail={"code":"LLM_SELECTION_STALE","message":"Selection changed or revision exhausted; reload and retry."})
            raise HTTPException(409,detail={"code":"PROVIDER_UNAVAILABLE","message":"Only an enabled ready provider can be selected."})
        await db.commit(); row=await _selection(db)
        return {"provider_id":row.provider_id,"selection_revision":row.selection_revision,"updated_at":row.updated_at}
    except OperationalError as exc:
        await _selection_busy(db,exc)


@router.get("/providers/{provider_id}", response_model=ProviderConfigOut)
async def get_provider_config(provider_id: str, db: AsyncSession = Depends(get_db)):
    provider=await db.get(ProviderConfig,provider_id)
    if not provider: raise HTTPException(404,"Provider not found")
    return await _project_provider(db,provider)


@router.post("/providers", response_model=ProviderConfigOut, status_code=201)
async def create_provider(data: ProviderConfigCreate, db: AsyncSession = Depends(get_db)):
    provider = ProviderConfig(**data.model_dump(), auth_type="env")
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return await _project_provider(db,provider)


def _is_local_client(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "testclient"}


@router.put("/providers/{provider_id}/secret", status_code=204)
async def write_provider_secret(provider_id: str, data: ProviderSecretWrite, request: Request, db: AsyncSession = Depends(get_db)):
    client_host = request.client.host if request.client else ""
    if not _is_local_client(client_host):  # testclient is FastAPI's in-process test transport
        raise HTTPException(403, "Provider secrets can only be configured from localhost")
    provider = await db.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    try:
        validate_app_secret_env_key(provider.secret_env_key)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if provider.provider_type == "mock":
        raise HTTPException(400, "Mock provider does not use an API key")
    # Commit a durable dispatch fence before touching the external store. If the
    # store or final DB publish fails, resolution remains closed on the latch.
    mutate = (lambda: put_memory_secret(provider.id, data.api_key)) if desktop_mode() else (lambda: _write_env_value(provider.secret_env_key, data.api_key))
    await change_external_secret(db, provider, mutate)


@router.post("/providers/{provider_id}/secret/recover", status_code=204)
async def recover_provider_secret(provider_id: str, data: ProviderSecretRecovery, request: Request, db: AsyncSession = Depends(get_db)):
    if not _is_local_client(request.client.host if request.client else ""):
        raise HTTPException(403, "Provider secrets can only be configured from localhost")
    provider = await db.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    try:
        validate_app_secret_env_key(provider.secret_env_key)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if data.operation == "set":
        mutate = (lambda: put_memory_secret(provider.id, data.api_key)) if desktop_mode() else (lambda: _write_env_value(provider.secret_env_key, data.api_key))
    else:
        mutate = (lambda: delete_memory_secret(provider.id)) if desktop_mode() else (lambda: _delete_env_value(provider.secret_env_key))
    await recover_external_secret(db, provider, data.revision, mutate)


@router.patch("/providers/{provider_id}/model", response_model=ProviderConfigOut)
async def update_provider_model(provider_id: str, data: ProviderModelUpdate, db: AsyncSession = Depends(get_db)):
    provider = await db.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    await guarded_provider_update(db, provider, model_name=data.model_name, auth_type="env")
    await db.commit()
    await db.refresh(provider)
    return await _project_provider(db,provider)


@router.patch("/providers/{provider_id}", response_model=ProviderConfigOut)
async def update_provider(provider_id: str, data: ProviderConfigUpdate, db: AsyncSession = Depends(get_db)):
    try:
        provider = await db.get(ProviderConfig, provider_id)
        if not provider: raise HTTPException(404, "Provider not found")
        changes = data.model_dump(exclude_unset=True); changes["auth_type"] = "env"
        if changes.get("enabled") is False: await _clear_selection_for_provider(db,provider_id)
        await guarded_provider_update(db, provider, **changes); await db.commit(); await db.refresh(provider)
        return await _project_provider(db,provider)
    except OperationalError as exc:
        await db.rollback()
        if data.enabled is False and _is_sqlite_busy(exc): await _selection_busy(db,exc)
        raise
    except BaseException:
        await db.rollback()
        raise


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: str, db: AsyncSession = Depends(get_db)):
    try:
        provider = await db.get(ProviderConfig, provider_id)
        if not provider: raise HTTPException(404, "Provider not found")
        await _clear_selection_for_provider(db,provider_id); await db.delete(provider); await db.commit()
    except OperationalError as exc:
        await db.rollback()
        if _is_sqlite_busy(exc): await _selection_busy(db,exc)
        raise
    except BaseException:
        await db.rollback()
        raise


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
        return payload.get("block_type") in CONTENT_BLOCK_TYPES and isinstance(payload.get("content"), dict)
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
    if data.expected_project_revision is None or data.expected_node_revision is None:
        raise HTTPException(422, "Artifact approval requires expected project and node revisions")
    await claim_project_revision(db, artifact.project_id, data.expected_project_revision)
    check_entity_revision(target, data.expected_node_revision, kind="node")
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
    bump_existing(target)
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
    if os.getenv("GROWTHMAP_DB_QUERY_ONLY") == "1":
        rows=(await db.execute(__import__("sqlalchemy").text("SELECT id,name,description,goal,root_node_id,status,settings,created_at,updated_at FROM projects ORDER BY updated_at DESC"))).mappings().all()
        return [{**dict(row),"settings":json.loads(row["settings"]) if isinstance(row["settings"],str) else (row["settings"] or {}),"revision":1} for row in rows]
    result = await db.execute(select(Project).order_by(Project.updated_at.desc()))
    return result.scalars().all()


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    async with _project_seat_lock:
        await _require_active_project_seat(db)
        return await _create_project_committed(data, db)


async def _create_project_committed(data: ProjectCreate, db: AsyncSession):
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
    await claim_project_revision(db, project_id, data.expected_project_revision)
    changes = data.model_dump(exclude_unset=True, exclude={"expected_project_revision"})
    if changes.get("status") == "active" and project.status != "active":
        async with _project_seat_lock:
            await _require_active_project_seat(db, conflict_status=409)
            for k, v in changes.items(): setattr(project, k, v)
            await db.commit()
            await db.refresh(project)
            return project
    for k, v in changes.items(): setattr(project, k, v)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, data: ProjectRevisionRequest, db: AsyncSession = Depends(get_db)):
    backup_db()
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    await claim_project_revision(db, project_id, data.expected_project_revision)
    project = await db.get(Project, project_id)
    await db.delete(project)
    await db.commit()


# ─── Nodes ───

@router.get("/projects/{project_id}/nodes", response_model=list[NodeBrief])
async def list_nodes(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        ordinary_main_nodes(project_id).order_by(Node.created_at)
    )
    return result.scalars().all()


@router.post("/projects/{project_id}/nodes", response_model=NodeOut, status_code=201)
async def create_node(project_id: str, data: NodeCreate, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Load and validate every existing entity CAS before the project claim or any
    # canonical write. A child relationship touches its parent even if maturity
    # happens not to advance.
    parent = None
    if data.parent_id:
        parent = await db.get(Node, data.parent_id)
        if not parent or parent.project_id != project_id:
            raise HTTPException(400, "Invalid parent node")
        check_entity_revision(parent, data.expected_parent_revision, kind="node")
        if (parent.branch_id or None) != (data.branch_id or None):
            raise HTTPException(400, "Parent and child must belong to the same branch")

    await claim_project_revision(db, project_id, data.expected_project_revision)
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
        payload={"title": node.title, "parent_id": str(data.parent_id) if data.parent_id else None, "branch_id": str(node.branch_id) if node.branch_id else None},
    ))
    # Auto-advance parent maturity and bump the touched existing parent exactly
    # once for the relationship plus any maturity transition.
    touched = TouchedEntities()
    if parent:
        touched.add(parent)
        await auto_advance_maturity(parent.id, db, touched=touched)
    touched.apply()
    await db.commit()
    await db.refresh(node)
    # Response carries all authoritative CAS values needed by a serialized GUI
    # workflow; these are response-only Pydantic fields, never canonical columns.
    node.authoritative_project_revision = data.expected_project_revision + 1
    node.authoritative_parent_id = parent.id if parent else None
    node.authoritative_parent_revision = parent.revision if parent else None
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
    await claim_project_revision(db, node.project_id, data.expected_project_revision)
    check_entity_revision(node, data.expected_revision, kind="node")
    changes = data.model_dump(exclude_unset=True, exclude={"expected_project_revision", "expected_revision"})
    for k, v in changes.items():
        setattr(node, k, v)
    node.last_edited_by = "human"
    bump_existing(node)
    # Auto-advance maturity based on content richness
    await auto_advance_maturity(node_id, db)

    db.add(ActionLog(
        project_id=node.project_id,
        node_id=node.id,
        actor_type="human",
        action_type="update_node",
        payload=changes,
    ))
    await db.commit()
    await db.refresh(node)
    return node


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(node_id: str, data: EntityRevisionRequest, db: AsyncSession = Depends(get_db)):
    backup_db()
    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    project = await db.get(Project, node.project_id)
    if project and project.root_node_id == node_id:
        raise HTTPException(409, "Cannot delete the project root node")
    check_entity_revision(node, data.expected_revision, kind="node")

    async def validate_closure():
        subtree_ids={str(node.id)};frontier={str(node.id)};incoming=set();edge_ids=set();parents={}
        def chunks(values,size=500):
            values=list(values)
            for offset in range(0,len(values),size):yield values[offset:offset+size]
        async def nodes_by_ids(values):
            rows=[]
            for part in chunks(values):rows.extend((await db.execute(select(Node).where(Node.id.in_(part)))).scalars().all())
            return rows
        async def edges_touching(values,relation_type=None):
            rows={}
            # Separate endpoint queries keep each statement at <=501 total binds
            # (500 IDs plus the optional relation type), below the conservative
            # SQLite 900-variable budget.
            for part in chunks(values):
                for endpoint in (Edge.from_node_id,Edge.to_node_id):
                    predicates=[endpoint.in_(part)]
                    if relation_type is not None:predicates.append(Edge.relation_type==relation_type)
                    for edge in (await db.execute(select(Edge).where(*predicates))).scalars().all():rows[str(edge.id)]=edge
            return list(rows.values())
        root_ids={str(value) for value in (await db.execute(
            select(Project.root_node_id).where(Project.root_node_id.is_not(None))
        )).scalars().all()}
        branch_id=str(node.branch_id) if node.branch_id is not None else None
        if branch_id is not None:
            branch=await db.get(Branch,branch_id)
            if not branch or str(branch.project_id)!=str(node.project_id):
                raise HTTPException(409,"Branch ownership is invalid")
            if branch.status not in {"active","merged","archived"}:
                raise HTTPException(409,"Branch status is invalid")
            # Constant-bind authority proof. UNION (not UNION ALL) makes the
            # recursive reachability walk cycle-safe. In-degree validity alone is
            # insufficient: a rooted component plus a disconnected cycle must fail.
            authority=(await db.execute(__import__("sqlalchemy").text("""
                WITH RECURSIVE
                ownership AS (
                  SELECT n.id AS target_id, COUNT(e.id) AS inbound_count,
                         SUM(CASE WHEN e.id IS NOT NULL AND e.project_id=:project_id
                                   AND s.id IS NOT NULL AND s.project_id=:project_id
                                   AND s.branch_id=:branch_id THEN 1 ELSE 0 END) AS valid_count
                  FROM nodes n
                  LEFT JOIN edges e ON e.to_node_id=n.id AND e.relation_type='child_of'
                  LEFT JOIN nodes s ON s.id=e.from_node_id
                  WHERE n.project_id=:project_id AND n.branch_id=:branch_id
                  GROUP BY n.id
                ),
                roots AS (SELECT target_id FROM ownership WHERE inbound_count=0),
                reachable(id) AS (
                  SELECT target_id FROM roots
                  UNION
                  SELECT t.id FROM reachable r
                  JOIN edges e ON e.from_node_id=r.id AND e.relation_type='child_of'
                  JOIN nodes s ON s.id=e.from_node_id
                  JOIN nodes t ON t.id=e.to_node_id
                  WHERE e.project_id=:project_id
                    AND s.project_id=:project_id AND s.branch_id=:branch_id
                    AND t.project_id=:project_id AND t.branch_id=:branch_id
                )
                SELECT (SELECT COUNT(*) FROM ownership) AS branch_nodes,
                       (SELECT COUNT(*) FROM roots) AS roots,
                       (SELECT COUNT(*) FROM ownership
                          WHERE inbound_count>1 OR inbound_count<>valid_count) AS malformed,
                       (SELECT MAX(target_id) FROM roots) AS root_id,
                       (SELECT COUNT(*) FROM reachable) AS reachable
            """),{"project_id":str(node.project_id),"branch_id":branch_id})).mappings().one()
            if (int(authority["branch_nodes"] or 0)==0 or int(authority["roots"] or 0)!=1
                    or int(authority["malformed"] or 0)!=0
                    or int(authority["reachable"] or 0)!=int(authority["branch_nodes"] or 0)):
                raise HTTPException(409,"Branch root authority is malformed")
            # Branch rows are durable lifecycle/history authorities. Archive is a
            # soft lifecycle transition, not permission to destroy its tree; merged
            # branches canonically have no branch-bound root at all.
            if str(node.id)==str(authority["root_id"]):
                raise HTTPException(409,"Cannot delete a branch root")
        while frontier:
            sources=await nodes_by_ids(frontier)
            if len(sources)!=len(frontier) or any(
                str(source.project_id)!=str(node.project_id)
                or (str(source.branch_id) if source.branch_id is not None else None)!=branch_id
                for source in sources
            ):raise HTTPException(409,"Subtree containment boundary is invalid")
            edges=[]
            for part in chunks(frontier):edges.extend((await db.execute(select(Edge).where(
                Edge.relation_type=="child_of",Edge.from_node_id.in_(part)
            ))).scalars().all())
            target_ids={str(edge.to_node_id) for edge in edges}
            targets={str(target.id):target for target in await nodes_by_ids(target_ids)} if target_ids else {}
            for edge in edges:
                target_id=str(edge.to_node_id);target=targets.get(target_id)
                if (str(edge.id) in edge_ids or target_id in incoming or target_id in subtree_ids
                        or not target or str(edge.project_id)!=str(node.project_id)
                        or str(target.project_id)!=str(node.project_id)
                        or (str(target.branch_id) if target.branch_id is not None else None)!=branch_id
                        or target_id in root_ids):
                    raise HTTPException(409,"Subtree containment crosses a boundary or is not a tree")
                edge_ids.add(str(edge.id));incoming.add(target_id);parents[target_id]=str(edge.from_node_id)
            frontier=target_ids;subtree_ids.update(frontier)

        inbound=[]
        for part in chunks(subtree_ids):inbound.extend((await db.execute(select(Edge).where(
            Edge.relation_type=="child_of",Edge.to_node_id.in_(part)
        ))).scalars().all())
        source_ids={str(edge.from_node_id) for edge in inbound}
        sources={str(source.id):source for source in await nodes_by_ids(source_ids)} if source_ids else {}
        by_target={}
        for edge in inbound:
            source=sources.get(str(edge.from_node_id));target_id=str(edge.to_node_id)
            if (str(edge.project_id)!=str(node.project_id) or not source
                    or str(source.project_id)!=str(node.project_id)
                    or (str(source.branch_id) if source.branch_id is not None else None)!=branch_id):
                raise HTTPException(409,"Subtree incoming ownership boundary is invalid")
            by_target.setdefault(target_id,[]).append(edge)
        for target_id in subtree_ids:
            edges=by_target.get(target_id,[])
            if target_id==str(node.id):
                if len(edges)>1:raise HTTPException(409,"Subtree root has invalid ownership")
            elif len(edges)!=1 or str(edges[0].from_node_id)!=parents.get(target_id):
                raise HTTPException(409,"Subtree descendant has invalid ownership")

        # Validate every relation incident to the closure. Cross-branch
        # non-containment relations are canonical, but every endpoint and edge
        # must still belong to the claimed project.
        incident=await edges_touching(subtree_ids)
        endpoint_ids={str(value) for edge in incident for value in (edge.from_node_id,edge.to_node_id)}
        endpoints={str(item.id):item for item in await nodes_by_ids(endpoint_ids)} if endpoint_ids else {}
        incident_ids=set()
        for edge in incident:
            source=endpoints.get(str(edge.from_node_id));target=endpoints.get(str(edge.to_node_id))
            if (str(edge.id) in incident_ids or not source or not target
                    or str(edge.project_id)!=str(node.project_id)
                    or str(source.project_id)!=str(node.project_id)
                    or str(target.project_id)!=str(node.project_id)):
                raise HTTPException(409,"Subtree incident edge ownership is invalid")
            if edge.relation_type=="child_of" and source.branch_id!=target.branch_id:
                raise HTTPException(409,"Subtree containment branch is invalid")
            incident_ids.add(str(edge.id))
        logs=[]
        for part in chunks(subtree_ids):logs.extend((await db.execute(select(ActionLog).where(
            ActionLog.node_id.in_(part)
        ))).scalars().all())
        log_ids=set()
        for log in logs:
            if str(log.project_id)!=str(node.project_id) or str(log.id) in log_ids:
                raise HTTPException(409,"Subtree action log ownership is invalid")
            log_ids.add(str(log.id))
        return subtree_ids,incident_ids,log_ids

    # Validate before and after the project CAS writer boundary.
    subtree_ids,incident_ids,log_ids=await validate_closure()
    await claim_project_revision(db,node.project_id,data.expected_project_revision)
    subtree_ids,incident_ids,log_ids=await validate_closure()
    def chunks(values,size=500):
        values=list(values)
        for offset in range(0,len(values),size):yield values[offset:offset+size]
    for part in chunks(incident_ids):await db.execute(Edge.__table__.delete().where(Edge.id.in_(part)))
    for part in chunks(log_ids):await db.execute(ActionLog.__table__.delete().where(ActionLog.id.in_(part)))
    for part in chunks(subtree_ids):await db.execute(Node.__table__.delete().where(Node.id.in_(part)))
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
    if os.getenv("GROWTHMAP_DB_QUERY_ONLY") == "1":
        text=__import__("sqlalchemy").text
        node_rows=(await db.execute(text("SELECT id,project_id,branch_id,title,summary,node_type,status,maturity,priority,confidence,description,rules_text,constraints_text,examples_text,questions_text,decision_notes,tags,created_by,last_edited_by,position_x,position_y,workflow_status,file_paths,created_at,updated_at FROM nodes WHERE project_id=(SELECT project_id FROM nodes WHERE id=:node_id)"),{"node_id":node_id})).mappings().all()
        nodes={str(row["id"]):dict(row) for row in node_rows}
        if node_id not in nodes: raise HTTPException(404,"Node not found")
        edge_rows=(await db.execute(text("SELECT id,from_node_id,to_node_id,is_mainline FROM edges WHERE project_id=:project_id AND relation_type='child_of' ORDER BY created_at,id"),{"project_id":nodes[node_id]["project_id"]})).mappings().all()
        child_map:dict[str,list[str]]={};edge_meta={}
        for row in edge_rows:
            child_map.setdefault(str(row["from_node_id"]),[]).append(str(row["to_node_id"]));edge_meta[str(row["to_node_id"])]={"edge_id":str(row["id"]),"edge_revision":1,"is_mainline":bool(row["is_mainline"])}
        block_rows=(await db.execute(text("SELECT id,node_id,block_type,content,order_index FROM content_blocks WHERE node_id IN (SELECT id FROM nodes WHERE project_id=:project_id) ORDER BY node_id,order_index"),{"project_id":nodes[node_id]["project_id"]})).mappings().all()
        blocks={}
        for row in block_rows:
            item=dict(row);item["content"]=json.loads(item["content"]) if isinstance(item["content"],str) else (item["content"] or {});item["revision"]=1;blocks.setdefault(str(row["node_id"]),[]).append(item)
        def tree(nid:str,depth:int=0,ancestors:list|None=None):
            row=nodes[nid];ancestor_path=list(ancestors or []);children=[]
            if depth<10:
                next_path=ancestor_path+[{"id":nid,"title":row["title"],"node_type":row["node_type"]}]
                children=[tree(child,depth+1,next_path) for child in child_map.get(nid,[]) if child in nodes]
            def value(name,default=""):
                return row[name] if row[name] is not None else default
            def sequence(name):
                raw=row[name];return json.loads(raw) if isinstance(raw,str) else (raw or [])
            return {"id":nid,"project_id":str(row["project_id"]),"branch_id":str(row["branch_id"]) if row["branch_id"] else None,"title":row["title"],"summary":value("summary"),"node_type":row["node_type"],"status":row["status"],"maturity":row["maturity"],"priority":value("priority",0),"confidence":value("confidence",0.5),"description":value("description"),"rules_text":value("rules_text"),"constraints_text":value("constraints_text"),"examples_text":value("examples_text"),"questions_text":value("questions_text"),"decision_notes":value("decision_notes"),"workflow_status":value("workflow_status","draft"),"tags":sequence("tags"),"file_paths":sequence("file_paths"),"created_by":value("created_by"),"last_edited_by":value("last_edited_by"),"position_x":value("position_x",0),"position_y":value("position_y",0),"meta":edge_meta.get(nid,{}),"content_blocks":blocks.get(nid,[]),"ancestor_path":ancestor_path,"created_at":str(value("created_at")),"updated_at":str(value("updated_at")),"revision":1,"children":children}
        return tree(node_id)
    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")

    edge_rows = await db.execute(
        select(Edge.from_node_id, Edge.to_node_id, Edge.id, Edge.is_mainline, Edge.revision).where(
            Edge.project_id == node.project_id,
            Edge.relation_type == "child_of"
        )
    )
    child_map: dict[str, list[str]] = {}
    edge_meta: dict[str, dict[str, str | bool | int]] = {}
    for from_node_id, to_node_id, edge_id, is_mainline, edge_revision in edge_rows.all():
        from_id = str(from_node_id)
        to_id = str(to_node_id)
        edge_meta[to_id] = {
            "edge_id": str(edge_id),
            "edge_revision": edge_revision or 1,
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
            "node_id": block.node_id,
            "block_type": block.block_type,
            "content": block.content,
            "order_index": block.order_index,
            "revision": block.revision or 1,
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
            "priority": n.priority if n.priority is not None else 0,
            "confidence": n.confidence if n.confidence is not None else 0.5,
            "description": n.description or "",
            "rules_text": n.rules_text or "",
            "constraints_text": n.constraints_text or "",
            "examples_text": n.examples_text or "",
            "questions_text": n.questions_text or "",
            "decision_notes": n.decision_notes or "",
            "workflow_status": n.workflow_status or "draft",
            "tags": n.tags or [],
            "file_paths": n.file_paths or [],
            "created_by": n.created_by or "",
            "last_edited_by": n.last_edited_by or "",
            "position_x": n.position_x if n.position_x is not None else 0,
            "position_y": n.position_y if n.position_y is not None else 0,
            "meta": edge_meta.get(nid, {}),
            "content_blocks": blocks_by_node_id.get(nid, []),
            "ancestor_path": current_ancestor_path,
            "created_at": n.created_at.isoformat() if n.created_at else "",
            "updated_at": n.updated_at.isoformat() if n.updated_at else "",
            "revision": n.revision or 1,
            "children": children,
        }

    return build_tree(node_id)


# ─── Edges ───

GRAPH_RELATION_TYPES = {
    "depends_on", "contradicts", "references", "supports", "blocks", "relates_to",
    "decomposes", "interfaces_with", "supersedes", "validates",
}


async def demote_mainline_siblings(db: AsyncSession, parent_id: str, *, except_edge_id: str | None = None):
    """Demote and revision-bump every pre-existing mainline sibling."""
    query = select(Edge).where(
        Edge.from_node_id == parent_id,
        Edge.relation_type == "child_of",
        Edge.is_mainline == True,
    )
    if except_edge_id:
        query = query.where(Edge.id != except_edge_id)
    siblings = (await db.execute(query)).scalars().all()
    for sibling in siblings:
        sibling.is_mainline = False
    bump_existing(*siblings)
    await db.flush()

@router.get("/projects/{project_id}/edges", response_model=list[EdgeOut])
async def list_project_edges(project_id: str, relation_type: str | None = None, db: AsyncSession = Depends(get_db)):
    if os.getenv("GROWTHMAP_DB_QUERY_ONLY") == "1":
        query="SELECT id,project_id,from_node_id,to_node_id,relation_type,weight,note,is_mainline,created_at FROM edges WHERE project_id=:project_id";params={"project_id":project_id}
        if relation_type: query+=" AND relation_type=:relation_type";params["relation_type"]=relation_type
        query+=" ORDER BY created_at";rows=(await db.execute(__import__("sqlalchemy").text(query),params)).mappings().all();return [{**dict(row),"revision":1} for row in rows]
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

    await claim_project_revision(db, from_node.project_id, data.expected_project_revision)
    payload = data.model_dump(exclude={"expected_project_revision"})
    is_mainline = payload.pop("is_mainline", False)

    # If new edge is marked as mainline, demote siblings first
    if is_mainline and payload.get("relation_type", "child_of") == "child_of":
        await demote_mainline_siblings(db, payload["from_node_id"])

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
    await claim_project_revision(db, edge.project_id, data.expected_project_revision)
    check_entity_revision(edge, data.expected_revision, kind="edge")
    values = data.model_dump(exclude_unset=True, exclude={"expected_project_revision", "expected_revision"})
    if not values:
        raise HTTPException(400, "No edge fields provided")
    if "weight" in values and not 0 <= values["weight"] <= 1:
        raise HTTPException(400, "Weight must be between 0 and 1")
    if "note" in values and len(values["note"]) > 2000:
        raise HTTPException(400, "Note is too long")
    for key, value in values.items():
        setattr(edge, key, value)
    bump_existing(edge)
    db.add(ActionLog(project_id=edge.project_id, node_id=edge.from_node_id, actor_type="human", action_type="graph_relation_updated", payload={"edge_id": edge.id, "changes": values}))
    await db.commit()
    await db.refresh(edge)
    return edge


@router.post("/edges/{edge_id}/promote-mainline", response_model=EdgeOut)
async def promote_mainline(edge_id: str, data: EntityRevisionRequest, db: AsyncSession = Depends(get_db)):
    edge = await db.get(Edge, edge_id)
    if not edge:
        raise HTTPException(404, "Edge not found")
    if edge.relation_type != "child_of":
        raise HTTPException(400, "Only child_of edges can be promoted")
    await claim_project_revision(db, edge.project_id, data.expected_project_revision)
    check_entity_revision(edge, data.expected_revision, kind="edge")

    await demote_mainline_siblings(db, edge.from_node_id, except_edge_id=edge.id)
    edge.is_mainline = True
    bump_existing(edge)
    await db.commit()
    await db.refresh(edge)
    return edge


@router.post("/nodes/{parent_id}/promote-child/{child_id}")
async def promote_child_mainline(parent_id: str, child_id: str, data: EntityRevisionRequest, db: AsyncSession = Depends(get_db)):
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
    await claim_project_revision(db, edge.project_id, data.expected_project_revision)
    check_entity_revision(edge, data.expected_revision, kind="edge")

    await demote_mainline_siblings(db, parent_id, except_edge_id=edge.id)
    edge.is_mainline = True
    bump_existing(edge)
    await db.commit()
    return {"ok": True}


@router.delete("/edges/{edge_id}", status_code=204)
async def delete_edge(edge_id: str, data: EntityRevisionRequest, db: AsyncSession = Depends(get_db)):
    edge = await db.get(Edge, edge_id)
    if not edge:
        raise HTTPException(404, "Edge not found")
    if edge.relation_type == "child_of":
        raise HTTPException(400, "Tree parent relations must be changed through node move actions")
    await claim_project_revision(db, edge.project_id, data.expected_project_revision)
    check_entity_revision(edge, data.expected_revision, kind="edge")
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
    old_edge = (await db.execute(select(Edge).where(
        Edge.to_node_id == node_id, Edge.relation_type == "child_of"
    ))).scalar_one_or_none()
    old_parent = await db.get(Node, old_edge.from_node_id) if old_edge else None
    check_entity_revision(node, body.expected_revision, kind="node")
    check_entity_revision(new_parent, body.expected_new_parent_revision, kind="node")
    if old_parent:
        if body.expected_old_parent_revision is None:
            raise HTTPException(422, "expected_old_parent_revision is required")
        check_entity_revision(old_parent, body.expected_old_parent_revision, kind="node")
    await claim_project_revision(db, node.project_id, body.expected_project_revision)

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
    touched = TouchedEntities()
    touched.add(node, old_parent, new_parent)
    touched.apply()
    await db.commit()
    return {"ok": True, "is_mainline": is_mainline, "project_revision": body.expected_project_revision + 1,
            "node_revision": node.revision, "old_parent_revision": old_parent.revision if old_parent else None,
            "new_parent_revision": new_parent.revision}


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
            ).order_by(Edge.created_at, Edge.id).limit(1)
        )
        # 歷史資料若曾留下多條主線，先採最早一條穩定降級，避免整個 API 500。
        mainline_edge = mainline_edge_result.scalars().first()
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
    if os.getenv("GROWTHMAP_DB_QUERY_ONLY") == "1":
        rows=(await db.execute(__import__("sqlalchemy").text("SELECT id,node_id,block_type,content,order_index,created_by,created_at,updated_at FROM content_blocks WHERE node_id=:node_id ORDER BY order_index"),{"node_id":node_id})).mappings().all();return [{**dict(row),"content":json.loads(row["content"]) if isinstance(row["content"],str) else (row["content"] or {}),"revision":1} for row in rows]
    result = await db.execute(
        select(ContentBlock).where(ContentBlock.node_id == node_id).order_by(ContentBlock.order_index)
    )
    return result.scalars().all()


@router.post("/nodes/{node_id}/blocks", response_model=ContentBlockOut, status_code=201)
async def create_block(node_id: str, data: ContentBlockCreate, db: AsyncSession = Depends(get_db)):
    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    await claim_project_revision(db, node.project_id, data.expected_project_revision)
    check_entity_revision(node, data.expected_node_revision, kind="node")
    block = ContentBlock(node_id=node_id, **data.model_dump(exclude={"expected_project_revision", "expected_node_revision"}))
    db.add(block)
    bump_existing(node)
    await auto_advance_maturity(node_id, db)
    await db.commit()
    await db.refresh(block)
    return block


@router.patch("/blocks/{block_id}", response_model=ContentBlockOut)
async def update_block(block_id: str, data: ContentBlockUpdate, db: AsyncSession = Depends(get_db)):
    block = await db.get(ContentBlock, block_id)
    if not block:
        raise HTTPException(404, "Block not found")
    node = await db.get(Node, block.node_id)
    if not node: raise HTTPException(404, "Node not found")
    await claim_project_revision(db, node.project_id, data.expected_project_revision)
    check_entity_revision(block, data.expected_revision, kind="block")
    check_entity_revision(node, data.expected_node_revision, kind="node")
    for k, v in data.model_dump(exclude_unset=True, exclude={"expected_project_revision", "expected_node_revision", "expected_revision"}).items():
        setattr(block, k, v)
    bump_existing(block, node)
    await db.commit()
    await db.refresh(block)
    return block


@router.delete("/blocks/{block_id}", status_code=204)
async def delete_block(block_id: str, data: NodeEntityRevisionRequest, db: AsyncSession = Depends(get_db)):
    block = await db.get(ContentBlock, block_id)
    if not block:
        raise HTTPException(404, "Block not found")
    node = await db.get(Node, block.node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    await claim_project_revision(db, node.project_id, data.expected_project_revision)
    check_entity_revision(block, data.expected_revision, kind="block")
    check_entity_revision(node, data.expected_node_revision, kind="node")
    bump_existing(node)
    await db.delete(block)
    await db.commit()


# ─── Maturity Auto-Advance ───

MATURITY_ORDER = ["seed", "rough", "developing", "stable", "finalized"]

async def auto_advance_maturity(node_id: str, db: AsyncSession, *, touched: TouchedEntities | None = None):
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
        if touched is not None:
            touched.add(node)
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

EXPORT_LABELS = {
    "en": {"blocks":"Content blocks","docs":"Attached documents","untitled":"Untitled document","spec":"Specification","description":"Description","goal":"Goal","date":"Export date","toc":"Table of contents","developing":"Developing"},
    "zh-CN": {"blocks":"内容区块","docs":"绑定文件","untitled":"未命名文件","spec":"规格文档","description":"描述","goal":"目标","date":"导出日期","toc":"目录","developing":"开发中"},
    "zh-TW": {"blocks":"內容區塊","docs":"綁定文件","untitled":"未命名文件","spec":"規格文件","description":"描述","goal":"目標","date":"匯出日期","toc":"目錄","developing":"開發中"},
}
CONTENT_BLOCK_LABELS = {
 "en":{"note":"Note","spec":"Specification","decision":"Decision","todo":"To do","risk":"Risk","paragraph":"Paragraph","resource":"Document","document":"Document","file":"Document"},
 "zh-CN":{"note":"笔记","spec":"规格","decision":"决策","todo":"待办","risk":"风险","paragraph":"段落","resource":"文件","document":"文件","file":"文件"},
 "zh-TW":{"note":"筆記","spec":"規格","decision":"決策","todo":"待辦","risk":"風險","paragraph":"段落","resource":"文件","document":"文件","file":"文件"},
}
DOC_BLOCK_TYPES = {"resource", "document", "file"}

def _block_content(block): return block.content if isinstance(block.content, dict) else {}
def _render_content_blocks(blocks:list,heading_level:str="###",locale:str="en")->list[str]:
 lines=[]; content_blocks=[b for b in blocks if b.block_type not in DOC_BLOCK_TYPES]
 if not content_blocks:return lines
 labels=EXPORT_LABELS[locale];types=CONTENT_BLOCK_LABELS[locale];lines.append(f"{heading_level} {labels['blocks']}")
 for b in content_blocks:
  content=_block_content(b);label=types.get(b.block_type,b.block_type);title=content.get("title") or label;body=content.get("body") or content.get("summary") or "";lines.append(f"- **{label}｜{title}**")
  if body:
   for line in str(body).splitlines():lines.append(f"  {line}" if line else "")
 lines.append("");return lines

def _render_bound_docs(blocks:list,heading_level:str="###",locale:str="en")->list[str]:
 lines=[];docs=[b for b in blocks if b.block_type in DOC_BLOCK_TYPES]
 if not docs:return lines
 labels=EXPORT_LABELS[locale];lines.append(f"{heading_level} {labels['docs']}")
 for b in docs:
  content=_block_content(b);title=content.get("title") or content.get("name") or content.get("filename") or content.get("url") or content.get("path") or labels["untitled"];href=content.get("url") or content.get("path") or "";summary=content.get("summary") or content.get("body") or "";lines.append(f"- [{title}]({href})" if href else f"- {title}")
  if summary:lines.append(f"  - {summary}")
 lines.append("");return lines

class ExportContentCompatibilityError(ValueError):
    """Stored content cannot be represented by the Markdown exporter."""


def _decode_export_content(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ExportContentCompatibilityError("invalid stored JSON") from error
    if not isinstance(value, dict):
        raise ExportContentCompatibilityError("stored content must be a JSON object")
    return value


async def _query_only_export_rows(db: AsyncSession, project_id: str):
    """Narrow seam for query-only export reads; intentionally performs no writes."""
    text = __import__("sqlalchemy").text
    project_row = (await db.execute(text("SELECT id,name,description,goal,root_node_id FROM projects WHERE id=:project_id"), {"project_id": project_id})).mappings().first()
    node_rows = (await db.execute(text("SELECT id,title,summary,maturity FROM nodes WHERE project_id=:project_id AND branch_id IS NULL"), {"project_id": project_id})).mappings().all()
    edge_rows = (await db.execute(text("SELECT e.from_node_id,e.to_node_id FROM edges e JOIN nodes f ON f.id=e.from_node_id JOIN nodes t ON t.id=e.to_node_id WHERE e.project_id=:project_id AND e.relation_type='child_of' AND f.project_id=:project_id AND t.project_id=:project_id AND f.branch_id IS NULL AND t.branch_id IS NULL"), {"project_id": project_id})).all()
    block_rows = (await db.execute(text("SELECT id,node_id,block_type,content,order_index FROM content_blocks WHERE node_id IN (SELECT id FROM nodes WHERE project_id=:project_id AND branch_id IS NULL) ORDER BY node_id,order_index"), {"project_id": project_id})).mappings().all()
    return project_row, node_rows, edge_rows, block_rows


def _is_json_deserialization_error(error: Exception) -> bool:
    if isinstance(error,json.JSONDecodeError):return True
    return isinstance(error,StatementError) and isinstance(error.orig,json.JSONDecodeError)


@router.get("/projects/{project_id}/export", response_class=PlainTextResponse)
async def export_project(project_id: str, locale: str = "zh-TW", db: AsyncSession = Depends(get_db)):
    """Export entire project tree as Markdown document (bulk-loaded)."""
    if os.getenv("GROWTHMAP_DB_QUERY_ONLY") == "1":
        project_row, node_rows, edge_rows, block_rows = await _query_only_export_rows(db, project_id)
        if not project_row: raise HTTPException(404,"Project not found")
        project=SimpleNamespace(**project_row)
        nodes_by_id={str(row["id"]):SimpleNamespace(**row) for row in node_rows}
        blocks_by_node:dict[str,list]={}
        for row in block_rows:
            item=dict(row)
            try: item["content"]=_decode_export_content(item["content"])
            except (ExportContentCompatibilityError, json.JSONDecodeError) as error:
                raise HTTPException(409,"Project data is not compatible with Markdown export") from error
            blocks_by_node.setdefault(str(item["node_id"]),[]).append(SimpleNamespace(**item))
    else:
        project = await db.get(Project, project_id)
        if not project: raise HTTPException(404, "Project not found")
        nodes_result = await db.execute(ordinary_main_nodes(project_id))
        nodes_by_id = {str(n.id): n for n in nodes_result.scalars().all()}
        all_node_ids = list(nodes_by_id.keys())
        edge_rows = (await db.execute(select(Edge.from_node_id, Edge.to_node_id).where(
            Edge.project_id == project_id, Edge.relation_type == "child_of",
            Edge.from_node_id.in_(all_node_ids), Edge.to_node_id.in_(all_node_ids)
        ))).all() if all_node_ids else []
        blocks_by_node: dict[str, list] = {}
        if all_node_ids:
            try:
                blocks_result = await db.execute(select(ContentBlock).where(ContentBlock.node_id.in_(all_node_ids)).order_by(ContentBlock.node_id, ContentBlock.order_index))
                for b in blocks_result.scalars().all(): blocks_by_node.setdefault(str(b.node_id), []).append(b)
            except (json.JSONDecodeError,StatementError) as error:
                if not _is_json_deserialization_error(error):raise
                raise HTTPException(409,"Project data is not compatible with Markdown export") from error
    if not project.root_node_id:
        raise HTTPException(404, "No root node")
    child_map: dict[str, list[str]] = {}
    for from_id, to_id in edge_rows: child_map.setdefault(str(from_id), []).append(str(to_id))

    language = locale if locale in EXPORT_LABELS else "zh-TW"
    labels = {**EXPORT_LABELS[language], "pending": {"en":"Pending expansion", "zh-CN":"待展开", "zh-TW":"待展開"}[language]}
    lines = [f"# {project.name}\n"]
    if project.description:
        lines.append(f"_{project.description}_\n")
    if project.goal:
        lines.append(f"**{labels['goal']}**: {project.goal}\n")
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
        lines.extend(_render_content_blocks(node_blocks, heading_level="#" * min(depth + 3, 6), locale=language))
        lines.extend(_render_bound_docs(node_blocks, heading_level="#" * min(depth + 3, 6), locale=language))

        if n.maturity == "seed":
            lines.append(f"_⏳ {labels['pending']}_\n")

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
async def reparent_node(node_id: str, body: NodeMoveRequest, db: AsyncSession = Depends(get_db)):
    """Reparent a node to a new parent via drag-and-drop."""
    new_parent_id = body.new_parent_id

    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")

    project = await db.get(Project, node.project_id)
    if project and project.root_node_id == node_id:
        raise HTTPException(400, "Cannot reparent root node")

    new_parent = await db.get(Node, new_parent_id)
    if not new_parent or new_parent.project_id != node.project_id:
        raise HTTPException(400, "Invalid new parent")
    old_edge = (await db.execute(select(Edge).where(
        Edge.to_node_id == node_id, Edge.relation_type == "child_of"
    ))).scalar_one_or_none()
    old_parent = await db.get(Node, old_edge.from_node_id) if old_edge else None
    check_entity_revision(node, body.expected_revision, kind="node")
    check_entity_revision(new_parent, body.expected_new_parent_revision, kind="node")
    if old_parent:
        if body.expected_old_parent_revision is None:
            raise HTTPException(422, "expected_old_parent_revision is required")
        check_entity_revision(old_parent, body.expected_old_parent_revision, kind="node")
    await claim_project_revision(db, node.project_id, body.expected_project_revision)

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
    touched = TouchedEntities()
    touched.add(node, old_parent, new_parent)
    touched.apply()
    await db.commit()
    return {"ok": True, "project_revision": body.expected_project_revision + 1,
            "node_revision": node.revision, "old_parent_revision": old_parent.revision if old_parent else None,
            "new_parent_revision": new_parent.revision}


# ─── Import / Export JSON ───

@router.get("/projects/{project_id}/export-json")
async def export_project_json(project_id: str, db: AsyncSession = Depends(get_db)):
    """Export entire project as JSON (all nodes, edges, content blocks, action logs)."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    nodes_result = await db.execute(ordinary_main_nodes(project_id))
    nodes = nodes_result.scalars().all()

    node_ids = [str(n.id) for n in nodes]
    edges_result = await db.execute(select(Edge).where(
        Edge.project_id == project_id, Edge.from_node_id.in_(node_ids), Edge.to_node_id.in_(node_ids)
    )) if node_ids else None
    edges = edges_result.scalars().all() if edges_result else []
    blocks_result = await db.execute(
        select(ContentBlock).where(ContentBlock.node_id.in_(node_ids))
    ) if node_ids else None
    blocks = blocks_result.scalars().all() if blocks_result else []

    logs_result = await db.execute(
        select(ActionLog).where(
            ActionLog.project_id == project_id, ActionLog.node_id.in_(node_ids)
        ).order_by(ActionLog.created_at.desc()).limit(200)
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
                "priority": n.priority,
                "confidence": n.confidence,
                "tags": n.tags or [],
                "description": n.description or "",
                "rules_text": n.rules_text or "",
                "constraints_text": n.constraints_text or "",
                "examples_text": n.examples_text or "",
                "questions_text": n.questions_text or "",
                "decision_notes": n.decision_notes or "",
                "workflow_status": n.workflow_status or "draft",
                "file_paths": n.file_paths or [],
                "created_by": n.created_by or "human",
                "last_edited_by": n.last_edited_by or "human",
                "position_x": n.position_x if n.position_x is not None else 0,
                "position_y": n.position_y if n.position_y is not None else 0,
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
                "weight": 1.0 if e.weight is None else e.weight,
                "note": "" if e.note is None else e.note,
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
    """Import atomically with the same active-seat allocator as create/restore."""
    status=data.get("project",{}).get("status","active")
    if status != "active": return await _import_project_json_committed(data,db)
    async with _project_seat_lock:
        await _require_active_project_seat(db)
        return await _import_project_json_committed(data,db)

async def _import_project_json_committed(data: dict, db: AsyncSession):
    proj_data = data.get("project", {})
    nodes_data = data.get("nodes", [])
    edges_data = data.get("edges", [])
    blocks_data = data.get("content_blocks", [])

    # Create new project
    new_project = Project(
        name=proj_data.get("name", "Imported project"),
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
            priority=n.get("priority", 0),
            confidence=n.get("confidence", 0.5),
            tags=n.get("tags") or [],
            description=n.get("description") or "",
            rules_text=n.get("rules_text") or "",
            constraints_text=n.get("constraints_text") or "",
            examples_text=n.get("examples_text") or "",
            questions_text=n.get("questions_text") or "",
            decision_notes=n.get("decision_notes") or "",
            workflow_status=n.get("workflow_status") or "draft",
            file_paths=n.get("file_paths") or [],
            created_by=n.get("created_by") or "import",
            last_edited_by=n.get("last_edited_by") or "import",
            position_x=n.get("position_x") if n.get("position_x") is not None else 0,
            position_y=n.get("position_y") if n.get("position_y") is not None else 0,
        )
        db.add(new_node)
        await db.flush()
        id_map[n["id"]] = str(new_node.id)

    # Set root
    if old_root_id and old_root_id in id_map:
        new_project.root_node_id = id_map[old_root_id]

    # 匯入時每個父節點只接受第一條宣告主線；重複旗標安全降級為非主線。
    imported_mainline_parents: set[str] = set()
    for e in edges_data:
        from_id = id_map.get(e.get("from_node_id", ""))
        to_id = id_map.get(e.get("to_node_id", ""))
        if not from_id or not to_id:
            continue
        relation_type = e.get("relation_type", "child_of")
        is_mainline = bool(e.get("is_mainline", False)) and relation_type == "child_of"
        if is_mainline and from_id in imported_mainline_parents:
            is_mainline = False
        elif is_mainline:
            imported_mainline_parents.add(from_id)
        new_edge = Edge(
            project_id=new_project.id,
            from_node_id=from_id,
            to_node_id=to_id,
            relation_type=relation_type,
            weight=1.0 if e.get("weight") is None else e.get("weight"),
            note="" if e.get("note") is None else e.get("note"),
            is_mainline=is_mainline,
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
async def export_spec(project_id: str, locale: str = "zh-TW", db: AsyncSession = Depends(get_db)):
    """Export project as a structured spec Markdown document."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.root_node_id:
        raise HTTPException(404, "No root node")

    from datetime import date
    nodes_result = await db.execute(ordinary_main_nodes(project_id))
    nodes_by_id = {str(n.id): n for n in nodes_result.scalars().all()}

    main_ids = list(nodes_by_id.keys())
    edges_result = await db.execute(
        select(Edge.from_node_id, Edge.to_node_id).where(
            Edge.project_id == project_id, Edge.relation_type == "child_of",
            Edge.from_node_id.in_(main_ids), Edge.to_node_id.in_(main_ids)
        )
    ) if main_ids else None
    child_map: dict[str, list[str]] = {}
    for from_id, to_id in (edges_result.all() if edges_result else []):
        child_map.setdefault(str(from_id), []).append(str(to_id))

    all_node_ids = list(nodes_by_id.keys())
    blocks_by_node: dict[str, list] = {}
    if all_node_ids:
        blocks_result = await db.execute(
            select(ContentBlock).where(ContentBlock.node_id.in_(all_node_ids)).order_by(ContentBlock.node_id, ContentBlock.order_index)
        )
        for b in blocks_result.scalars().all():
            blocks_by_node.setdefault(str(b.node_id), []).append(b)

    language = locale if locale in EXPORT_LABELS else "zh-TW"
    labels = EXPORT_LABELS[language]

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
            content_lines.extend(_render_content_blocks(node_blocks, heading_level="###", locale=language))
            content_lines.extend(_render_bound_docs(node_blocks, heading_level="###", locale=language))
        else:
            content_lines.append(f"{prefix} {n.title} (🚧 {labels['developing']})")
            if n.summary:
                content_lines.append(f"\n{n.summary}\n")
            node_blocks = blocks_by_node.get(nid, [])
            content_lines.extend(_render_content_blocks(node_blocks, heading_level="###", locale=language))
            content_lines.extend(_render_bound_docs(node_blocks, heading_level="###", locale=language))

        for cid in child_map.get(nid, []):
            render_spec_node(cid, depth + 1)

    render_spec_node(str(project.root_node_id))

    header = [
        f"# {project.name} — {labels['spec']}",
        "",
        f"**{labels['description']}**: {project.description}" if project.description else "",
        f"**{labels['goal']}**: {project.goal}" if project.goal else "",
        f"**{labels['date']}**: {date.today().isoformat()}",
        "",
        "---",
        "",
        f"## {labels['toc']}",
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
    """Create a branch through the canonical transaction-local deep-copy primitive."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    source_node = await db.get(Node, data.source_node_id)
    if not source_node or source_node.project_id != project_id:
        raise HTTPException(400, "Invalid source node")

    await claim_project_revision(db, project_id, data.expected_project_revision)
    branch = await deep_copy_branch(
        db, project_id=project_id, source_node_id=data.source_node_id,
        name=data.name, description=data.description, actor="branch",
    )
    db.add(ActionLog(
        project_id=project_id, actor_type="human", action_type="create_branch",
        payload={"branch_name": data.name, "source_node_id": data.source_node_id},
    ))
    await db.commit()
    await db.refresh(branch)
    return branch


@router.get("/projects/{project_id}/branches", response_model=list[BranchOut])
async def list_branches(project_id: str, include_inactive: bool = False, db: AsyncSession = Depends(get_db)):
    if os.getenv("GROWTHMAP_DB_QUERY_ONLY") == "1":
        query="SELECT id,project_id,name,description,source_node_id,status,created_at FROM branches WHERE project_id=:project_id";params={"project_id":project_id}
        if not include_inactive: query+=" AND status='active'"
        query+=" ORDER BY created_at DESC";rows=(await db.execute(__import__("sqlalchemy").text(query),params)).mappings().all();return [{**dict(row),"revision":1} for row in rows]
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
            "priority": n.priority if n.priority is not None else 0,
            "confidence": n.confidence if n.confidence is not None else 0.5,
            "description": n.description or "",
            "rules_text": n.rules_text or "",
            "constraints_text": n.constraints_text or "",
            "examples_text": n.examples_text or "",
            "questions_text": n.questions_text or "",
            "decision_notes": n.decision_notes or "",
            "workflow_status": n.workflow_status or "draft",
            "tags": n.tags or [],
            "file_paths": n.file_paths or [],
            "created_by": n.created_by or "",
            "last_edited_by": n.last_edited_by or "",
            "position_x": n.position_x if n.position_x is not None else 0,
            "position_y": n.position_y if n.position_y is not None else 0,
            "meta": {},
            "content_blocks": [],
            "branch_id": n.branch_id,
            "created_at": n.created_at.isoformat() if n.created_at else "",
            "updated_at": n.updated_at.isoformat() if n.updated_at else "",
            "revision": n.revision or 1,
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
async def merge_branch(branch_id: str, body: BranchMergeRequest, db: AsyncSession = Depends(get_db)):
    """Merge branch by re-parenting branch root under target node."""
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(404, "Branch not found")
    if branch.status != "active":
        raise HTTPException(400, "Only active branches can be merged")
    target_node_id = body.target_node_id
    await claim_project_revision(db, branch.project_id, body.expected_project_revision)
    check_entity_revision(branch, body.expected_revision, kind="branch")
    target_node = await db.get(Node, target_node_id)
    if not target_node or target_node.project_id != branch.project_id or target_node.branch_id:
        raise HTTPException(400, "Target node must be on this project mainline")
    check_entity_revision(target_node, body.expected_target_revision, kind="node")

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
    # The target gains the canonical child relationship; branch nodes are
    # canonically reassigned to mainline. Deduplication prevents a double bump.
    bump_existing(branch, target_node, *branch_nodes)
    db.add(ActionLog(
        project_id=branch.project_id,
        actor_type="human",
        action_type="merge_branch",
        payload={"branch_id": branch_id, "target_node_id": target_node_id},
    ))
    await db.commit()
    return {"ok": True}


@router.delete("/branches/{branch_id}", status_code=204)
async def archive_branch(branch_id: str, data: EntityRevisionRequest, db: AsyncSession = Depends(get_db)):
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(404, "Branch not found")
    if branch.status != "active":
        raise HTTPException(400, "Only active branches can be archived")
    await claim_project_revision(db, branch.project_id, data.expected_project_revision)
    check_entity_revision(branch, data.expected_revision, kind="branch")
    branch.status = "archived"
    bump_existing(branch)
    db.add(ActionLog(
        project_id=branch.project_id,
        actor_type="human",
        action_type="archive_branch",
        payload={"branch_id": branch_id},
    ))
    await db.commit()

