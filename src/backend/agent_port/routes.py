import hashlib, hmac, json, os, secrets, time, uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from models.models import Project,Node,Edge,ContentBlock,Branch,ActionLog,AgentGrant,AgentProposal,AgentEvent,AgentReadback
from agent_port.service import apply_batch,allowed_nodes,canonical,digest,idempotency_lock,validate_scope,validate_operations
from agent_port.schemas import Batch,ProposalIn,EventIn,ReadbackIn,ReviewIn

router=APIRouter(); _hits=defaultdict(deque)
PERMISSIONS={"read":0,"propose":1,"write":2}
MODES={"read_only":"read","review_first":"propose","direct_collaboration":"write"}
_workspace_grant_race_hook=None  # tests may install an awaitable barrier

async def human_control(request:Request,authorization:str|None=Header(None)):
    # Separate human capability. Desktop uses its per-launch token; authoring mode
    # must explicitly provision a local session token or the plane fails closed.
    token=os.getenv("GROWTHMAP_SESSION_TOKEN") or os.getenv("GROWTHMAP_HUMAN_CONTROL_TOKEN")
    if not token: raise HTTPException(403,{"code":"HUMAN_CONTROL_DISABLED","message":"Human control session is not initialized"})
    if not authorization or not hmac.compare_digest(authorization,f"Bearer {token}"): raise HTTPException(401,{"code":"HUMAN_AUTH_REQUIRED","message":"Human session capability required"})
    origin=request.headers.get("origin")
    if origin and origin.rstrip("/") not in {"http://127.0.0.1:3000","http://localhost:3000",str(request.base_url).rstrip("/")}: raise HTTPException(403,{"code":"ORIGIN_DENIED","message":"Untrusted browser origin"})
    request.state.human_identity="desktop-human" if os.getenv("GROWTHMAP_DESKTOP_MODE")=="1" else "local-human-session"

human_router=APIRouter(dependencies=[Depends(human_control)])

def now(): return datetime.now(timezone.utc)
def iso(value): return value.isoformat() if value else None
def uuid_value(value,name="id"):
    try: return str(uuid.UUID(value))
    except Exception: raise HTTPException(422,f"Invalid {name}")
def grant_mode(g): return g.mode or {"read":"read_only","propose":"review_first","write":"direct_collaboration"}.get(g.permission,"read_only")
def public_grant(g): return {"id":g.id,"token_prefix":g.token_prefix,"project_id":g.project_id,"workspace_scope":getattr(g,"workspace_scope","legacy_project"),"mode":grant_mode(g),"permission":g.permission,"node_scope_id":g.node_scope_id,"branch_root_id":g.branch_root_id,"label":g.label,"agent_identity":g.agent_identity,"status":g.status,"expires_at":None if g.persistent else iso(g.expires_at),"persistent":g.persistent,"revoked_at":iso(g.revoked_at),"last_used_at":iso(g.last_used_at),"created_at":iso(g.created_at)}
def public_readback(x,grant=None): return {"id":x.id,"target_node_id":x.target_node_id,**({"source":grant.label,"agent":grant.agent_identity} if grant else {}),"summary":x.summary,"commit_refs":x.commit_refs,"files":x.files,"tests":x.tests,"decisions":x.decisions,"risks":x.risks,"todos":x.todos,"evidence":x.evidence,"created_at":iso(x.created_at)}
def hash_secret(secret,salt): return hashlib.scrypt(secret.encode(),salt=bytes.fromhex(salt),n=2**14,r=8,p=1,dklen=32).hex()
def active_grant(grant):
    if not grant or grant.status!="active" or grant.revoked_at:return False
    if grant.persistent:return True
    expires=grant.expires_at
    if expires is None:return False
    if expires.tzinfo is None:expires=expires.replace(tzinfo=timezone.utc)
    return expires>now()

class Strict(BaseModel): model_config=ConfigDict(extra="forbid")
class GrantCreate(Strict):
    id:str|None=None
    project_id:str|None=None; permission:Literal["read","propose","write"]|None=None
    mode:Literal["read_only","direct_collaboration","review_first"]|None=None
    workspace_scope:Literal["workspace","legacy_project"]|None=None
    node_scope_id:str|None=None; branch_root_id:str|None=None
    expires_at:datetime|None; persistent:bool=False; label:str=Field(min_length=1,max_length=120); agent_identity:str=Field(min_length=1,max_length=120)
    @model_validator(mode="after")
    def scope(self):
        # Omitted scope with a project is the v1 compatibility shape. Fresh R18
        # desktop enable sends workspace explicitly and never binds UI selection.
        if self.workspace_scope is None:self.workspace_scope="legacy_project" if self.project_id else "workspace"
        if self.workspace_scope=="workspace":
            if self.project_id or self.node_scope_id or self.branch_root_id: raise ValueError("Workspace grants cannot carry project or node scope")
            if not self.mode:self.mode="direct_collaboration"
            mapped=MODES[self.mode]
            if self.permission and self.permission!=mapped: raise ValueError("Mode and permission conflict")
            self.permission=mapped
        elif not self.project_id or not self.permission: raise ValueError("Legacy project grant requires project and permission")
        if self.node_scope_id and self.branch_root_id: raise ValueError("Choose node or branch scope, not both")
        if self.persistent:
            if self.expires_at is not None: raise ValueError("Persistent grants must not have an expiry")
        elif self.expires_at is None or self.expires_at <= now()+timedelta(minutes=1) or self.expires_at > now()+timedelta(days=90): raise ValueError("Expiry must be finite, 1 minute to 90 days")
        return self

async def local_limit(request:Request):
    host=request.client.host if request.client else ""
    if host not in {"127.0.0.1","::1","localhost","testclient"}: raise HTTPException(403,{"code":"LOCALHOST_ONLY","message":"Agent Port is localhost-only"})
    if request.url.query and "token" in request.query_params: raise HTTPException(400,{"code":"TOKEN_QUERY_FORBIDDEN","message":"Bearer token cannot use query string"})
    length=int(request.headers.get("content-length","0") or 0)
    if length>1_048_576: raise HTTPException(413,"Agent Port request exceeds 1 MiB")

async def auth(request:Request,authorization:str|None=Header(None),db:AsyncSession=Depends(get_db)):
    await local_limit(request)
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,{"code":"AUTH_REQUIRED","message":"Bearer token required"})
    raw=authorization[7:]
    try: version,prefix,secret=raw.split(".",2)
    except ValueError: raise HTTPException(401,{"code":"INVALID_TOKEN","message":"Invalid token"})
    if version!="gm1" or len(prefix)!=12 or len(secret)<32: raise HTTPException(401,{"code":"INVALID_TOKEN","message":"Invalid token"})
    grant=(await db.execute(select(AgentGrant).where(AgentGrant.token_prefix==prefix))).scalar_one_or_none()
    dummy_salt="00"*16; supplied=hash_secret(secret,grant.token_salt if grant else dummy_salt); expected=grant.token_hash if grant else "00"*32
    if not hmac.compare_digest(supplied,expected): raise HTTPException(401,{"code":"INVALID_TOKEN","message":"Invalid token"})
    if not active_grant(grant): raise HTTPException(401,{"code":"GRANT_INACTIVE","message":"Grant is revoked or expired"})
    instant=time.monotonic()
    if len(_hits)>10000:
        for gid in list(_hits)[:1000]:
            if not _hits[gid] or _hits[gid][-1]<instant-60:_hits.pop(gid,None)
    bucket=_hits[grant.id]
    while bucket and bucket[0]<instant-60: bucket.popleft()
    if len(bucket)>=120: raise HTTPException(429,{"code":"RATE_LIMITED","message":"120 requests/minute limit"})
    bucket.append(instant);grant.last_used_at=now();await db.commit();await db.refresh(grant);return grant

def require(grant,permission):
    if PERMISSIONS[grant.permission]<PERMISSIONS[permission]: raise HTTPException(403,{"code":"PERMISSION_DENIED","message":f"{permission} permission required"})
def require_mode(grant,*modes):
    mode=grant_mode(grant)
    if mode not in modes: raise HTTPException(403,{"code":"MODE_DENIED","message":f"Operation is unavailable in {mode} mode"})
async def project_grant(db,grant,project_id):
    from types import SimpleNamespace
    if getattr(grant,"workspace_scope","legacy_project")=="workspace":
        if not project_id: raise HTTPException(422,{"code":"PROJECT_ID_REQUIRED","message":"Workspace access requires explicit project_id"})
        pid=uuid_value(project_id,"project_id")
    else:
        pid=grant.project_id
        if project_id and uuid_value(project_id,"project_id")!=pid: raise HTTPException(403,{"code":"PROJECT_MISMATCH","message":"Project is outside grant scope"})
    if not await db.get(Project,pid): raise HTTPException(404,"Project not found")
    values={name:getattr(grant,name,None) for name in ("id","permission","mode","workspace_scope","node_scope_id","branch_root_id","label","agent_identity")}
    return SimpleNamespace(**values,project_id=pid)

@router.get("/capabilities",dependencies=[Depends(local_limit)])
async def capabilities(): return {"instance_nonce":os.getenv("GROWTHMAP_AGENT_INSTANCE_NONCE",""),"product_major":int(os.getenv("GROWTHMAP_PRODUCT_MAJOR","0")),"protocol":"growthmap-agent-port","version":"1.0","auth":"bearer","provider_neutral":True,"limits":{"request_bytes":1048576,"operations_per_batch":50,"requests_per_minute":120},"permissions":["read","propose","write"],"operations":["create_node","update_node","create_edge","create_content_block","create_branch"],"endpoints":["project","graph","context","proposals","batch","events","readbacks"]}

@router.get("/projects")
async def projects_read(grant=Depends(auth),db:AsyncSession=Depends(get_db)):
    rows=(await db.execute(select(Project).order_by(Project.updated_at.desc()).limit(100))).scalars().all()
    if getattr(grant,"workspace_scope","legacy_project")!="workspace": rows=[p for p in rows if p.id==grant.project_id]
    return [{"id":p.id,"name":p.name,"status":p.status,"revision":p.revision,"updated_at":iso(p.updated_at)} for p in rows]

@router.get("/project")
async def project_read(project_id:str|None=None,grant=Depends(auth),db:AsyncSession=Depends(get_db)):
    scoped=await project_grant(db,grant,project_id);p=await db.get(Project,scoped.project_id); return {"id":p.id,"name":p.name,"description":p.description,"goal":p.goal,"status":p.status,"root_node_id":p.root_node_id,"revision":p.revision,"updated_at":iso(p.updated_at)}

async def graph_data(db,grant):
    ids=await allowed_nodes(db,grant); nodes=(await db.execute(select(Node).where(Node.id.in_(ids),Node.project_id==grant.project_id).order_by(Node.created_at))).scalars().all(); edges=(await db.execute(select(Edge).where(Edge.project_id==grant.project_id,Edge.from_node_id.in_(ids),Edge.to_node_id.in_(ids)))).scalars().all(); blocks=(await db.execute(select(ContentBlock).where(ContentBlock.node_id.in_(ids)))).scalars().all()
    return {"project_id":grant.project_id,"nodes":[{"id":n.id,"title":n.title,"summary":n.summary,"node_type":n.node_type,"status":n.status,"maturity":n.maturity,"description":n.description,"constraints_text":n.constraints_text,"decision_notes":n.decision_notes,"tags":n.tags or [],"branch_id":n.branch_id,"revision":n.revision,"updated_at":iso(n.updated_at)} for n in nodes],"edges":[{"id":e.id,"from_node_id":e.from_node_id,"to_node_id":e.to_node_id,"relation_type":e.relation_type,"note":e.note,"revision":e.revision} for e in edges],"content_blocks":[{"id":b.id,"node_id":b.node_id,"block_type":b.block_type,"content":b.content,"order_index":b.order_index,"revision":b.revision} for b in blocks]}
@router.get("/graph")
async def graph_read(project_id:str|None=None,grant=Depends(auth),db:AsyncSession=Depends(get_db)): return await graph_data(db,await project_grant(db,grant,project_id))

@router.get("/context/{target_id}")
async def context(target_id:str,objective:str="",project_id:str|None=None,grant=Depends(auth),db:AsyncSession=Depends(get_db)):
    grant=await project_grant(db,grant,project_id);target_id=uuid_value(target_id); await validate_scope(db,grant,[target_id]); target=await db.get(Node,target_id)
    if not target or target.project_id!=grant.project_id: raise HTTPException(404,"Node not found")
    graph=await graph_data(db,grant); by={n["id"]:n for n in graph["nodes"]}; parents={e["to_node_id"]:e["from_node_id"] for e in graph["edges"] if e["relation_type"]=="child_of"}; ancestors=[];cur=target_id
    while cur in parents and parents[cur] in by: cur=parents[cur];ancestors.append(by[cur])
    children=[by[e["to_node_id"]] for e in graph["edges"] if e["from_node_id"]==target_id and e["to_node_id"] in by][:500]
    relevant=[n for n in graph["nodes"] if n["id"]!=target_id and (n["node_type"] in {"decision","risk"} or n["constraints_text"] or n["decision_notes"])][:200]
    p=await db.get(Project,grant.project_id)
    # Digest exactly the complete canonical packet consumed by the agent. No
    # volatile timestamps or transport fields are excluded implicitly.
    packet={"objective":objective[:2000],"project":{"id":p.id,"name":p.name,"description":p.description,
            "goal":p.goal,"status":p.status,"revision":p.revision},"target_revision":target.revision,
            "target":by[target_id],"ancestors":ancestors,"children":children,"relevant":relevant,
            "relations":graph["edges"][:2000]}
    return {**packet,"snapshot_digest":digest(packet)}

async def store_once(db,grant,key,payload,kind,create):
    import asyncio
    from models.models import AgentReceipt
    # Snapshot primitives before expire/commit/rollback; ORM instances are
    # expired by those lifecycle operations and attribute access may otherwise
    # attempt async IO outside SQLAlchemy's greenlet context.
    grant_id, project_id = grant.id, grant.project_id
    req=digest(payload); lock=idempotency_lock(grant_id,key)
    await asyncio.to_thread(lock.acquire)
    try:
        # Query the winner's durable receipt using only snapshotted primitives.
        prior=(await db.execute(select(AgentReceipt).where(AgentReceipt.grant_id==grant_id,AgentReceipt.idempotency_key==key))).scalar_one_or_none()
        if prior:
            if not hmac.compare_digest(prior.request_digest,req): raise HTTPException(409,{"code":"IDEMPOTENCY_MISMATCH","message":"Key payload mismatch"})
            return prior.response
        response=await create()
        db.add(AgentReceipt(grant_id=grant_id,project_id=project_id,idempotency_key=key,request_digest=req,action_type=kind,status="recorded",response=response))
        await db.commit()
        return response
    finally:
        lock.release()

@router.post("/proposals",status_code=201)
async def propose(data:ProposalIn,grant=Depends(auth),db:AsyncSession=Depends(get_db)):
    require_mode(grant,"review_first","direct_collaboration");require(grant,"propose");grant=await project_grant(db,grant,data.project_id);payload=data.model_dump(mode="json"); await validate_scope(db,grant,[data.target_node_id] if data.target_node_id else []); await validate_operations(db,grant,data.operations)
    async def create():
        p=await db.get(Project,grant.project_id)
        if data.expected_project_revision!=p.revision: raise HTTPException(409,{"code":"REVISION_CONFLICT","message":"Project revision is stale","current":p.revision})
        proposal=AgentProposal(grant_id=grant.id,project_id=grant.project_id,target_node_id=data.target_node_id,title=data.title,rationale=data.rationale,operations=data.model_dump(mode="json")["operations"],expected_project_revision=data.expected_project_revision);db.add(proposal);await db.flush();return {"proposal_id":proposal.id,"status":"pending","project_revision":p.revision,"canonical_changed":False}
    return await store_once(db,grant,data.idempotency_key,payload,"proposal",create)

@router.post("/batch")
async def batch(data:Batch,grant=Depends(auth),db:AsyncSession=Depends(get_db)): require_mode(grant,"direct_collaboration");require(grant,"write");grant=await project_grant(db,grant,data.project_id);return await apply_batch(db,grant,data.model_dump())

@router.post("/events",status_code=201)
async def event(data:EventIn,grant=Depends(auth),db:AsyncSession=Depends(get_db)):
    require_mode(grant,"review_first","direct_collaboration");require(grant,"propose");grant=await project_grant(db,grant,data.project_id);await validate_scope(db,grant,[data.target_node_id] if data.target_node_id else []);payload=data.model_dump(mode="json")
    async def create():
        row=AgentEvent(grant_id=grant.id,project_id=grant.project_id,target_node_id=data.target_node_id,event_type=data.event_type,message=data.message,payload=data.payload);db.add(row);await db.flush();return {"event_id":row.id,"status":"recorded"}
    return await store_once(db,grant,data.idempotency_key,payload,"event",create)
@router.post("/readbacks",status_code=201)
async def readback(data:ReadbackIn,grant=Depends(auth),db:AsyncSession=Depends(get_db)):
    require_mode(grant,"review_first","direct_collaboration");require(grant,"propose");grant=await project_grant(db,grant,data.project_id);await validate_scope(db,grant,[data.target_node_id] if data.target_node_id else []);payload=data.model_dump(mode="json")
    if len(canonical(payload))>262144: raise HTTPException(413,"Readback exceeds 256 KiB")
    async def create():
        vals=data.model_dump(exclude={"idempotency_key","project_id"});row=AgentReadback(grant_id=grant.id,project_id=grant.project_id,**vals);db.add(row);await db.flush();db.add(ActionLog(project_id=grant.project_id,node_id=data.target_node_id,actor_type="agent",actor_id=grant.agent_identity,action_type="agent_readback",payload={"readback_id":row.id,"summary":data.summary[:500]}));return {"readback_id":row.id,"status":"recorded"}
    return await store_once(db,grant,data.idempotency_key,payload,"readback",create)

@human_router.post("/agent-port/grants",status_code=201)
async def create_grant(data:GrantCreate,db:AsyncSession=Depends(get_db)):
    p=None
    if data.project_id:
        p=await db.get(Project,uuid_value(data.project_id,"project_id"))
        if not p: raise HTTPException(404,"Project not found")
    for value,name in ((data.node_scope_id,"node_scope_id"),(data.branch_root_id,"branch_root_id")):
        if value:
            n=await db.get(Node,uuid_value(value,name));
            if not p or not n or n.project_id!=p.id: raise HTTPException(422,"Scope must belong to project")
    prefix=None
    for _ in range(8):
        candidate=secrets.token_hex(6)
        if not (await db.execute(select(AgentGrant.id).where(AgentGrant.token_prefix==candidate))).scalar_one_or_none(): prefix=candidate;break
    if not prefix: raise HTTPException(503,"Unable to allocate token prefix")
    secret=secrets.token_urlsafe(32);salt=secrets.token_hex(16);raw=f"gm1.{prefix}.{secret}"
    grant_id=uuid_value(data.id,"id") if data.id else str(uuid.uuid4())
    if await db.get(AgentGrant,grant_id): raise HTTPException(409,{"code":"ID_CONFLICT","message":"Grant ID already exists"})
    if data.workspace_scope=="workspace":
        # Singleton authority is deliberately lifecycle-based, not auth-time
        # expiry-based: an expired finite row remains the workspace master until
        # it is explicitly revoked. This exactly matches the partial index below.
        active=(await db.execute(select(AgentGrant.id).where(AgentGrant.workspace_scope=="workspace",AgentGrant.status=="active",AgentGrant.revoked_at.is_(None)))).scalar_one_or_none()
        if active: raise HTTPException(409,{"code":"WORKSPACE_GRANT_ACTIVE","message":"An active workspace grant already exists"})
        if _workspace_grant_race_hook is not None: await _workspace_grant_race_hook()
    g=AgentGrant(id=grant_id,token_prefix=prefix,token_salt=salt,token_hash=hash_secret(secret,salt),project_id=p.id if p else None,permission=data.permission,workspace_scope=data.workspace_scope,mode=data.mode,node_scope_id=data.node_scope_id,branch_root_id=data.branch_root_id,label=data.label,agent_identity=data.agent_identity,expires_at=data.expires_at,persistent=data.persistent);db.add(g)
    try: await db.commit()
    except IntegrityError:
        await db.rollback()
        if await db.get(AgentGrant,grant_id): raise HTTPException(409,{"code":"ID_CONFLICT","message":"Grant ID already exists"})
        if data.workspace_scope=="workspace":
            active=(await db.execute(select(AgentGrant.id).where(AgentGrant.workspace_scope=="workspace",AgentGrant.status=="active",AgentGrant.revoked_at.is_(None)))).scalar_one_or_none()
            if active: raise HTTPException(409,{"code":"WORKSPACE_GRANT_ACTIVE","message":"An active workspace grant already exists"})
        raise HTTPException(503,"Unable to allocate grant")
    await db.refresh(g)
    return {**public_grant(g),"token":raw,"warning":"Copy now. GrowthMap stores only a strong hash and cannot show this token again."}
@human_router.post("/agent-port/grants/{old_grant_id}/rotate",status_code=201)
async def rotate_workspace_grant(old_grant_id:str,data:GrantCreate,db:AsyncSession=Depends(get_db)):
    old_id=uuid_value(old_grant_id,"old_grant_id")
    if data.workspace_scope!="workspace": raise HTTPException(422,{"code":"WORKSPACE_ROTATION_REQUIRED","message":"Replacement must be a workspace grant"})
    if not data.id: raise HTTPException(422,{"code":"REPLACEMENT_ID_REQUIRED","message":"Rotation requires a caller-selected replacement ID"})
    new_id=uuid_value(data.id,"id")
    if new_id==old_id: raise HTTPException(409,{"code":"ID_CONFLICT","message":"Replacement ID must differ from current grant"})
    existing=await db.get(AgentGrant,new_id)
    old=await db.get(AgentGrant,old_id)
    if existing:
        if old and old.workspace_scope=="workspace" and old.revoked_at and existing.workspace_scope=="workspace" and existing.status=="active" and existing.revoked_at is None:
            raise HTTPException(409,{"code":"ROTATION_ALREADY_COMMITTED","message":"The exact replacement already exists; its token cannot be shown again"})
        raise HTTPException(409,{"code":"ID_CONFLICT","message":"Grant ID already exists"})
    if not old or old.workspace_scope!="workspace" or old.status!="active" or old.revoked_at is not None:
        raise HTTPException(409,{"code":"WORKSPACE_GRANT_STALE","message":"Current workspace grant identity is stale or inactive"})
    active=(await db.execute(select(AgentGrant.id).where(AgentGrant.workspace_scope=="workspace",AgentGrant.status=="active",AgentGrant.revoked_at.is_(None)))).scalars().all()
    if active!=[old_id]: raise HTTPException(409,{"code":"WORKSPACE_GRANT_CONFLICT","message":"Workspace master state is ambiguous"})
    prefix=None
    for _ in range(8):
        candidate=secrets.token_hex(6)
        if not (await db.execute(select(AgentGrant.id).where(AgentGrant.token_prefix==candidate))).scalar_one_or_none(): prefix=candidate;break
    if not prefix: raise HTTPException(503,"Unable to allocate token prefix")
    secret=secrets.token_urlsafe(32);salt=secrets.token_hex(16);raw=f"gm1.{prefix}.{secret}"
    old.revoked_at=now();old.status="revoked"
    replacement=AgentGrant(id=new_id,token_prefix=prefix,token_salt=salt,token_hash=hash_secret(secret,salt),project_id=None,permission=data.permission,workspace_scope="workspace",mode=data.mode,label=data.label,agent_identity=data.agent_identity,expires_at=data.expires_at,persistent=data.persistent)
    db.add(replacement)
    try: await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409,{"code":"WORKSPACE_GRANT_CONFLICT","message":"Workspace master changed during rotation"})
    await db.refresh(replacement)
    return {**public_grant(replacement),"token":raw,"warning":"Copy now. GrowthMap stores only a strong hash and cannot show this token again."}

@human_router.get("/agent-port/grants")
async def grants(project_id:str|None=None,db:AsyncSession=Depends(get_db)):
    where=[] if project_id is None else [AgentGrant.project_id==uuid_value(project_id,"project_id")]
    rows=(await db.execute(select(AgentGrant).where(*where).order_by(AgentGrant.created_at.desc()).limit(100))).scalars().all();return [public_grant(g) for g in rows]
@human_router.post("/agent-port/grants/{grant_id}/revoke")
async def revoke(grant_id:str,db:AsyncSession=Depends(get_db)):
    g=await db.get(AgentGrant,uuid_value(grant_id));
    if not g: raise HTTPException(404,"Grant not found")
    if not g.revoked_at:g.revoked_at=now();g.status="revoked";await db.commit()
    return public_grant(g)
@human_router.get("/agent-port/activity")
async def activity(project_id:str,target_node_id:str|None=None,db:AsyncSession=Depends(get_db)):
    pid=uuid_value(project_id,"project_id")
    target=None
    if target_node_id is not None:
        target=uuid_value(target_node_id,"target_node_id")
        node=await db.get(Node,target)
        # A project mismatch is intentionally indistinguishable from a missing node.
        if not node or node.project_id!=pid: raise HTTPException(404,"Node not found")
    proposal_where=[AgentProposal.project_id==pid]
    event_where=[AgentEvent.project_id==pid]
    readback_where=[AgentReadback.project_id==pid]
    if target:
        proposal_where.append(AgentProposal.target_node_id==target)
        event_where.append(AgentEvent.target_node_id==target)
        readback_where.append(AgentReadback.target_node_id==target)
    proposals=(await db.execute(select(AgentProposal).where(*proposal_where).order_by(AgentProposal.created_at.desc()).limit(100))).scalars().all()
    event_rows=(await db.execute(select(AgentEvent).where(*event_where).order_by(AgentEvent.created_at.desc()).limit(100))).scalars().all()
    # The recent-state projection is bounded and coalesces only consecutive,
    # low-value duplicate events. Durable rows and canonical action logs remain
    # untouched. Newest-first ordering makes aggregation deterministic.
    events=[]
    for row in event_rows:
        key=(row.event_type,row.message,row.target_node_id,canonical(row.payload or {}))
        if events and events[-1][0]==key: events[-1][2]+=1
        else: events.append([key,row,1])
    # Preserve durable readbacks even if an imported/legacy database cannot
    # resolve their grant relationship. Grant metadata is useful enrichment,
    # never a condition for returning implementation evidence.
    readback_rows=(await db.execute(select(AgentReadback,AgentGrant).outerjoin(AgentGrant,AgentReadback.grant_id==AgentGrant.id).where(*readback_where).order_by(AgentReadback.created_at.desc()).limit(100))).all()
    return {"proposals":[{"id":x.id,"title":x.title,"rationale":x.rationale,"operations":x.operations,"status":x.status,"target_node_id":x.target_node_id,"expected_project_revision":x.expected_project_revision,"review_note":x.review_note,"created_at":iso(x.created_at)} for x in proposals],"events":[{"id":x.id,"event_type":x.event_type,"message":x.message,"target_node_id":x.target_node_id,"payload":x.payload,"repeat_count":count,"created_at":iso(x.created_at)} for _,x,count in events[:100]],"readbacks":[public_readback(x,grant) for x,grant in readback_rows]}
@human_router.post("/agent-port/proposals/{proposal_id}/{decision}")
async def review(proposal_id:str,decision:Literal["approve","reject"],body:ReviewIn,request:Request,db:AsyncSession=Depends(get_db)):
    row=await db.get(AgentProposal,uuid_value(proposal_id));
    if not row: raise HTTPException(404,"Proposal not found")
    if row.status!="pending": return {"proposal_id":row.id,"status":row.status}
    note=body.review_note
    reviewer=getattr(request.state,"human_identity","local-human")
    if decision=="reject": row.status="rejected";row.review_note=note;row.reviewed_at=now();await db.commit();return {"proposal_id":row.id,"status":row.status}
    grant=await db.get(AgentGrant,row.grant_id)
    if not active_grant(grant) or PERMISSIONS.get(grant.permission,-1)<PERMISSIONS["propose"]: raise HTTPException(409,{"code":"GRANT_INACTIVE","message":"Revocation/expiry invalidates pending proposals"})
    # Workspace grants are intentionally unbound at rest. Rebind only to the
    # proposal's immutable project for human approval; never infer UI selection.
    grant=await project_grant(db,grant,row.project_id)
    row.review_note=note
    # Snapshot all wire primitives before apply_batch commits and expires row.
    proposal_id, expected_revision, operations = row.id, row.expected_project_revision, row.operations
    result=await apply_batch(db,grant,{"expected_project_revision":expected_revision,"idempotency_key":f"proposal:{proposal_id}","operations":operations},actor=reviewer,proposal=row)
    return {"proposal_id":proposal_id,"status":"approved","receipt":result}
