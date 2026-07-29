import hashlib, hmac, json, secrets, time, uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from models.models import Project,Node,Edge,ContentBlock,Branch,ActionLog,AgentGrant,AgentProposal,AgentEvent,AgentReadback
from agent_port.service import apply_batch,allowed_nodes,canonical,digest,validate_scope

router=APIRouter(); human_router=APIRouter(); _hits=defaultdict(deque)
PERMISSIONS={"read":0,"propose":1,"write":2}

def now(): return datetime.now(timezone.utc)
def iso(value): return value.isoformat() if value else None
def uuid_value(value,name="id"):
    try: return str(uuid.UUID(value))
    except Exception: raise HTTPException(422,f"Invalid {name}")
def public_grant(g): return {"id":g.id,"token_prefix":g.token_prefix,"project_id":g.project_id,"permission":g.permission,"node_scope_id":g.node_scope_id,"branch_root_id":g.branch_root_id,"label":g.label,"agent_identity":g.agent_identity,"status":g.status,"expires_at":iso(g.expires_at),"revoked_at":iso(g.revoked_at),"last_used_at":iso(g.last_used_at),"created_at":iso(g.created_at)}
def hash_secret(secret,salt): return hashlib.scrypt(secret.encode(),salt=bytes.fromhex(salt),n=2**14,r=8,p=1,dklen=32).hex()

class Strict(BaseModel): model_config=ConfigDict(extra="forbid")
class GrantCreate(Strict):
    project_id:str; permission:Literal["read","propose","write"]; node_scope_id:str|None=None; branch_root_id:str|None=None
    expires_at:datetime; label:str=Field(min_length=1,max_length=120); agent_identity:str=Field(min_length=1,max_length=120)
    @model_validator(mode="after")
    def scope(self):
        if self.node_scope_id and self.branch_root_id: raise ValueError("Choose node or branch scope, not both")
        if self.expires_at <= now()+timedelta(minutes=1) or self.expires_at > now()+timedelta(days=90): raise ValueError("Expiry must be finite, 1 minute to 90 days")
        return self
class Batch(Strict):
    expected_project_revision:int=Field(ge=1); idempotency_key:str=Field(min_length=8,max_length=80,pattern=r"^[A-Za-z0-9._:-]+$"); operations:list[dict[str,Any]]=Field(min_length=1,max_length=50)
class ProposalIn(Strict):
    idempotency_key:str=Field(min_length=8,max_length=80,pattern=r"^[A-Za-z0-9._:-]+$"); expected_project_revision:int=Field(ge=1); target_node_id:str|None=None; title:str=Field(min_length=1,max_length=200); rationale:str=Field(default="",max_length=4000); operations:list[dict[str,Any]]=Field(min_length=1,max_length=50)
class EventIn(Strict):
    idempotency_key:str=Field(min_length=8,max_length=80); target_node_id:str|None=None; event_type:Literal["started","progress","blocked","completed","failed"]; message:str=Field(min_length=1,max_length=4000); payload:dict[str,Any]=Field(default_factory=dict)
class ReadbackIn(Strict):
    idempotency_key:str=Field(min_length=8,max_length=80); target_node_id:str|None=None; summary:str=Field(default="",max_length=8000); commit_refs:list[str]=Field(default_factory=list,max_length=100); files:list[str]=Field(default_factory=list,max_length=500); tests:list[dict[str,Any]]=Field(default_factory=list,max_length=200); decisions:list[str]=Field(default_factory=list,max_length=200); risks:list[str]=Field(default_factory=list,max_length=200); todos:list[str]=Field(default_factory=list,max_length=200); evidence:list[dict[str,Any]]=Field(default_factory=list,max_length=200)

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
    expires=grant.expires_at.replace(tzinfo=timezone.utc) if grant.expires_at.tzinfo is None else grant.expires_at
    if grant.status!="active" or grant.revoked_at or expires<=now(): raise HTTPException(401,{"code":"GRANT_INACTIVE","message":"Grant is revoked or expired"})
    bucket=_hits[grant.id]; instant=time.monotonic()
    while bucket and bucket[0]<instant-60: bucket.popleft()
    if len(bucket)>=120: raise HTTPException(429,{"code":"RATE_LIMITED","message":"120 requests/minute limit"})
    bucket.append(instant);grant.last_used_at=now();await db.commit();return grant

def require(grant,permission):
    if PERMISSIONS[grant.permission]<PERMISSIONS[permission]: raise HTTPException(403,{"code":"PERMISSION_DENIED","message":f"{permission} permission required"})

@router.get("/capabilities",dependencies=[Depends(local_limit)])
async def capabilities(): return {"protocol":"growthmap-agent-port","version":"1.0","auth":"bearer","provider_neutral":True,"limits":{"request_bytes":1048576,"operations_per_batch":50,"requests_per_minute":120},"permissions":["read","propose","write"],"operations":["create_node","update_node","create_edge","create_content_block","create_branch"],"endpoints":["project","graph","context","proposals","batch","events","readbacks"]}

@router.get("/project")
async def project_read(grant=Depends(auth),db:AsyncSession=Depends(get_db)):
    p=await db.get(Project,grant.project_id); return {"id":p.id,"name":p.name,"description":p.description,"goal":p.goal,"status":p.status,"root_node_id":p.root_node_id,"revision":p.revision,"updated_at":iso(p.updated_at)}

async def graph_data(db,grant):
    ids=await allowed_nodes(db,grant); nodes=(await db.execute(select(Node).where(Node.id.in_(ids)).order_by(Node.created_at))).scalars().all(); edges=(await db.execute(select(Edge).where(Edge.project_id==grant.project_id,Edge.from_node_id.in_(ids),Edge.to_node_id.in_(ids)))).scalars().all(); blocks=(await db.execute(select(ContentBlock).where(ContentBlock.node_id.in_(ids)))).scalars().all()
    return {"project_id":grant.project_id,"nodes":[{"id":n.id,"title":n.title,"summary":n.summary,"node_type":n.node_type,"status":n.status,"maturity":n.maturity,"description":n.description,"constraints_text":n.constraints_text,"decision_notes":n.decision_notes,"tags":n.tags or [],"branch_id":n.branch_id,"revision":n.revision,"updated_at":iso(n.updated_at)} for n in nodes],"edges":[{"id":e.id,"from_node_id":e.from_node_id,"to_node_id":e.to_node_id,"relation_type":e.relation_type,"note":e.note,"revision":e.revision} for e in edges],"content_blocks":[{"id":b.id,"node_id":b.node_id,"block_type":b.block_type,"content":b.content,"order_index":b.order_index,"revision":b.revision} for b in blocks]}
@router.get("/graph")
async def graph_read(grant=Depends(auth),db:AsyncSession=Depends(get_db)): return await graph_data(db,grant)

@router.get("/context/{target_id}")
async def context(target_id:str,objective:str="",grant=Depends(auth),db:AsyncSession=Depends(get_db)):
    target_id=uuid_value(target_id); await validate_scope(db,grant,[target_id]); target=await db.get(Node,target_id)
    if not target or target.project_id!=grant.project_id: raise HTTPException(404,"Node not found")
    graph=await graph_data(db,grant); by={n["id"]:n for n in graph["nodes"]}; parents={e["to_node_id"]:e["from_node_id"] for e in graph["edges"] if e["relation_type"]=="child_of"}; ancestors=[];cur=target_id
    while cur in parents and parents[cur] in by: cur=parents[cur];ancestors.append(by[cur])
    children=[by[e["to_node_id"]] for e in graph["edges"] if e["from_node_id"]==target_id and e["to_node_id"] in by]
    relevant=[n for n in graph["nodes"] if n["node_type"] in {"decision","risk"} or n["constraints_text"] or n["decision_notes"]]
    p=await db.get(Project,grant.project_id); snapshot={"project_revision":p.revision,"target_revision":target.revision,"target":by[target_id],"ancestors":ancestors,"children":children,"relevant":relevant,"relations":graph["edges"]}
    return {"objective":objective[:2000],**snapshot,"snapshot_digest":digest(snapshot)}

async def store_once(db,grant,key,payload,kind,create):
    from models.models import AgentReceipt
    req=digest(payload); prior=(await db.execute(select(AgentReceipt).where(AgentReceipt.grant_id==grant.id,AgentReceipt.idempotency_key==key))).scalar_one_or_none()
    if prior:
        if not hmac.compare_digest(prior.request_digest,req): raise HTTPException(409,{"code":"IDEMPOTENCY_MISMATCH","message":"Key payload mismatch"})
        return prior.response
    response=await create(); db.add(AgentReceipt(grant_id=grant.id,project_id=grant.project_id,idempotency_key=key,request_digest=req,action_type=kind,status="recorded",response=response));await db.commit();return response

@router.post("/proposals",status_code=201)
async def propose(data:ProposalIn,grant=Depends(auth),db:AsyncSession=Depends(get_db)):
    require(grant,"propose"); payload=data.model_dump(mode="json"); await validate_scope(db,grant,[data.target_node_id] if data.target_node_id else [])
    async def create():
        p=await db.get(Project,grant.project_id)
        if data.expected_project_revision!=p.revision: raise HTTPException(409,{"code":"REVISION_CONFLICT","message":"Project revision is stale","current":p.revision})
        proposal=AgentProposal(grant_id=grant.id,project_id=grant.project_id,target_node_id=data.target_node_id,title=data.title,rationale=data.rationale,operations=data.operations,expected_project_revision=data.expected_project_revision);db.add(proposal);await db.flush();return {"proposal_id":proposal.id,"status":"pending","project_revision":p.revision,"canonical_changed":False}
    return await store_once(db,grant,data.idempotency_key,payload,"proposal",create)

@router.post("/batch")
async def batch(data:Batch,grant=Depends(auth),db:AsyncSession=Depends(get_db)): require(grant,"write");return await apply_batch(db,grant,data.model_dump())

@router.post("/events",status_code=201)
async def event(data:EventIn,grant=Depends(auth),db:AsyncSession=Depends(get_db)):
    require(grant,"propose");await validate_scope(db,grant,[data.target_node_id] if data.target_node_id else []);payload=data.model_dump(mode="json")
    async def create():
        row=AgentEvent(grant_id=grant.id,project_id=grant.project_id,target_node_id=data.target_node_id,event_type=data.event_type,message=data.message,payload=data.payload);db.add(row);await db.flush();return {"event_id":row.id,"status":"recorded"}
    return await store_once(db,grant,data.idempotency_key,payload,"event",create)
@router.post("/readbacks",status_code=201)
async def readback(data:ReadbackIn,grant=Depends(auth),db:AsyncSession=Depends(get_db)):
    require(grant,"propose");await validate_scope(db,grant,[data.target_node_id] if data.target_node_id else []);payload=data.model_dump(mode="json")
    if len(canonical(payload))>262144: raise HTTPException(413,"Readback exceeds 256 KiB")
    async def create():
        vals=data.model_dump(exclude={"idempotency_key"});row=AgentReadback(grant_id=grant.id,project_id=grant.project_id,**vals);db.add(row);await db.flush();db.add(ActionLog(project_id=grant.project_id,node_id=data.target_node_id,actor_type="agent",actor_id=grant.agent_identity,action_type="agent_readback",payload={"readback_id":row.id,"summary":data.summary[:500]}));return {"readback_id":row.id,"status":"recorded"}
    return await store_once(db,grant,data.idempotency_key,payload,"readback",create)

@human_router.post("/agent-port/grants",status_code=201)
async def create_grant(data:GrantCreate,db:AsyncSession=Depends(get_db)):
    p=await db.get(Project,uuid_value(data.project_id,"project_id"));
    if not p: raise HTTPException(404,"Project not found")
    for value,name in ((data.node_scope_id,"node_scope_id"),(data.branch_root_id,"branch_root_id")):
        if value:
            n=await db.get(Node,uuid_value(value,name));
            if not n or n.project_id!=p.id: raise HTTPException(422,"Scope must belong to project")
    prefix=secrets.token_hex(6);secret=secrets.token_urlsafe(32);salt=secrets.token_hex(16);raw=f"gm1.{prefix}.{secret}"
    g=AgentGrant(token_prefix=prefix,token_salt=salt,token_hash=hash_secret(secret,salt),project_id=p.id,permission=data.permission,node_scope_id=data.node_scope_id,branch_root_id=data.branch_root_id,label=data.label,agent_identity=data.agent_identity,expires_at=data.expires_at);db.add(g);await db.commit();await db.refresh(g)
    return {**public_grant(g),"token":raw,"warning":"Copy now. GrowthMap stores only a strong hash and cannot show this token again."}
@human_router.get("/agent-port/grants")
async def grants(project_id:str,db:AsyncSession=Depends(get_db)):
    rows=(await db.execute(select(AgentGrant).where(AgentGrant.project_id==uuid_value(project_id,"project_id")).order_by(AgentGrant.created_at.desc()))).scalars().all();return [public_grant(g) for g in rows]
@human_router.post("/agent-port/grants/{grant_id}/revoke")
async def revoke(grant_id:str,db:AsyncSession=Depends(get_db)):
    g=await db.get(AgentGrant,uuid_value(grant_id));
    if not g: raise HTTPException(404,"Grant not found")
    if not g.revoked_at:g.revoked_at=now();g.status="revoked";await db.commit()
    return public_grant(g)
@human_router.get("/agent-port/activity")
async def activity(project_id:str,db:AsyncSession=Depends(get_db)):
    pid=uuid_value(project_id); proposals=(await db.execute(select(AgentProposal).where(AgentProposal.project_id==pid).order_by(AgentProposal.created_at.desc()))).scalars().all();events=(await db.execute(select(AgentEvent).where(AgentEvent.project_id==pid).order_by(AgentEvent.created_at.desc()).limit(100))).scalars().all();readbacks=(await db.execute(select(AgentReadback).where(AgentReadback.project_id==pid).order_by(AgentReadback.created_at.desc()).limit(100))).scalars().all()
    return {"proposals":[{"id":x.id,"title":x.title,"rationale":x.rationale,"operations":x.operations,"status":x.status,"target_node_id":x.target_node_id,"expected_project_revision":x.expected_project_revision,"review_note":x.review_note,"created_at":iso(x.created_at)} for x in proposals],"events":[{"id":x.id,"event_type":x.event_type,"message":x.message,"target_node_id":x.target_node_id,"payload":x.payload,"created_at":iso(x.created_at)} for x in events],"readbacks":[{"id":x.id,"target_node_id":x.target_node_id,"summary":x.summary,"commit_refs":x.commit_refs,"files":x.files,"tests":x.tests,"decisions":x.decisions,"risks":x.risks,"todos":x.todos,"evidence":x.evidence,"created_at":iso(x.created_at)} for x in readbacks]}
@human_router.post("/agent-port/proposals/{proposal_id}/{decision}")
async def review(proposal_id:str,decision:Literal["approve","reject"],body:dict,db:AsyncSession=Depends(get_db)):
    row=await db.get(AgentProposal,uuid_value(proposal_id));
    if not row: raise HTTPException(404,"Proposal not found")
    if row.status!="pending": raise HTTPException(409,"Proposal already reviewed")
    note=str(body.get("review_note", ""))[:2000]
    if decision=="reject": row.status="rejected";row.review_note=note;row.reviewed_at=now();await db.commit();return {"proposal_id":row.id,"status":row.status}
    grant=await db.get(AgentGrant,row.grant_id)
    result=await apply_batch(db,grant,{"expected_project_revision":row.expected_project_revision,"idempotency_key":f"proposal:{row.id}","operations":row.operations},actor="human-review")
    row=await db.get(AgentProposal,row.id);row.status="approved";row.review_note=note;row.reviewed_at=now();await db.commit();return {"proposal_id":row.id,"status":row.status,"receipt":result}
