"""Desktop-authenticated canonical revision, delta, and SSE invalidation routes."""
import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from models.models import Project, Node, Edge, ContentBlock, Branch, CanonicalChange
from api.canonical_changes import change_hub, MAX_SAFE_INTEGER, MAX_IDS
from desktop import security as desktop_security

router=APIRouter()
NO_STORE={"Cache-Control":"no-store, max-age=0","Pragma":"no-cache"}

async def _project(project_id:str,db:AsyncSession)->Project:
    if not desktop_security.DESKTOP_MODE:raise HTTPException(404,"Not found")
    if len(project_id)>64:raise HTTPException(404,"Project not found")
    row=await db.get(Project,project_id)
    if not row:raise HTTPException(404,"Project not found")
    return row

@router.get("/projects/{project_id}/revision")
async def project_revision(project_id:str,db:AsyncSession=Depends(get_db)):
    row=await _project(project_id,db)
    return JSONResponse({"project_id":str(row.id),"revision":int(row.revision)},headers=NO_STORE)

@router.get("/projects/{project_id}/changes")
async def project_changes(project_id:str,since_revision:int=Query(ge=1,le=MAX_SAFE_INTEGER),limit:int=Query(128,ge=1,le=256),db:AsyncSession=Depends(get_db)):
    project=await _project(project_id,db);current=int(project.revision)
    if since_revision>current:raise HTTPException(409,{"code":"REVISION_AHEAD","current_revision":current})
    if since_revision==current:return JSONResponse({"schema":1,"project_id":project_id,"since_revision":since_revision,"current_revision":current,"complete":True,"full_refresh_required":False,"gap":False,"changes":[],"nodes":[],"edges":[],"content_blocks":[],"branches":[]},headers=NO_STORE)
    rows=(await db.execute(select(CanonicalChange).where(CanonicalChange.project_id==project_id,CanonicalChange.project_revision>since_revision).order_by(CanonicalChange.project_revision,CanonicalChange.created_at,CanonicalChange.id).limit(limit+1))).scalars().all()
    truncated=len(rows)>limit;rows=rows[:limit]
    revisions=[int(r.project_revision) for r in rows]
    expected=list(range(since_revision+1,(max(revisions)+1) if revisions else since_revision+1))
    gap=not rows or revisions!=expected
    complete=bool(rows) and revisions[-1]==current and not truncated and not gap
    full=gap or not complete or any(r.kind!="graph" for r in rows)
    ids={"nodes":[],"edges":[],"blocks":[],"branches":[],"parents":[]}
    changes=[]
    for row in rows:
        hints=row.hints if isinstance(row.hints,dict) else {}
        clean={k:[str(v) for v in hints.get(k,[])[:MAX_IDS] if isinstance(v,str) and len(v)<=64] for k in ids}
        for key in ids:
            for value in clean[key]:
                if value not in ids[key] and len(ids[key])<MAX_IDS:ids[key].append(value)
        if hints.get("overflow") is True:full=True
        changes.append({"schema":1,"kind":row.kind,"project_id":project_id,"revision":int(row.project_revision),"cursor":row.id,"hints":clean})
    if any(len(v)>=MAX_IDS for v in ids.values()):full=True
    nodes=[];edges=[];blocks=[];branches=[]
    if not full:
        node_ids=list(dict.fromkeys(ids["nodes"]+ids["parents"]))
        if node_ids:nodes=list((await db.execute(select(Node).where(Node.project_id==project_id,Node.id.in_(node_ids)))).scalars())
        if ids["edges"]:edges=list((await db.execute(select(Edge).where(Edge.project_id==project_id,Edge.id.in_(ids["edges"])))).scalars())
        if ids["blocks"]:
            blocks=list((await db.execute(select(ContentBlock).join(Node,Node.id==ContentBlock.node_id).where(Node.project_id==project_id,ContentBlock.id.in_(ids["blocks"])))).scalars())
        if ids["branches"]:branches=list((await db.execute(select(Branch).where(Branch.project_id==project_id,Branch.id.in_(ids["branches"])))).scalars())
        # Missing hinted entities means delete/race/corruption: never infer deletion.
        if len(nodes)!=len(node_ids) or len(edges)!=len(ids["edges"]) or len(blocks)!=len(ids["blocks"]) or len(branches)!=len(ids["branches"]):full=True
    def node(n):return {"id":n.id,"project_id":n.project_id,"branch_id":n.branch_id,"title":n.title,"summary":n.summary,"node_type":n.node_type,"status":n.status,"maturity":n.maturity,"priority":n.priority,"confidence":n.confidence,"description":n.description,"rules_text":n.rules_text,"constraints_text":n.constraints_text,"examples_text":n.examples_text,"questions_text":n.questions_text,"decision_notes":n.decision_notes,"tags":n.tags or [],"workflow_status":n.workflow_status,"file_paths":n.file_paths or [],"position_x":n.position_x,"position_y":n.position_y,"revision":n.revision}
    def edge(e):return {"id":e.id,"project_id":e.project_id,"from_node_id":e.from_node_id,"to_node_id":e.to_node_id,"relation_type":e.relation_type,"weight":e.weight,"note":e.note,"is_mainline":bool(e.is_mainline),"revision":e.revision}
    def block(b):return {"id":b.id,"node_id":b.node_id,"block_type":b.block_type,"content":b.content,"order_index":b.order_index,"revision":b.revision}
    def branch(b):return {"id":b.id,"project_id":b.project_id,"name":b.name,"description":b.description,"source_node_id":b.source_node_id,"status":b.status,"revision":b.revision}
    return JSONResponse({"schema":1,"project_id":project_id,"since_revision":since_revision,"current_revision":current,"complete":complete,"full_refresh_required":full,"gap":gap,"truncated":truncated,"changes":changes,"nodes":[] if full else [node(x) for x in nodes],"edges":[] if full else [edge(x) for x in edges],"content_blocks":[] if full else [block(x) for x in blocks],"branches":[] if full else [branch(x) for x in branches]},headers=NO_STORE)

async def canonical_sse_events(request:Request,sub,heartbeat_seconds:float=20):
    """Directly testable stream generator; route transport need not be held open."""
    try:
        yield "retry: 3000\nevent: ready\ndata: {\"schema\":1}\n\n"
        while True:
            try:payload=await asyncio.wait_for(change_hub.next(sub),timeout=heartbeat_seconds)
            except asyncio.TimeoutError:
                if await request.is_disconnected():break
                yield ": heartbeat\n\n";continue
            yield "id: "+payload["cursor"]+"\nevent: canonical-change\ndata: "+json.dumps(payload,separators=(",",":"))+"\n\n"
    finally:change_hub.unsubscribe(sub)

@router.get("/changes/stream")
async def changes_stream(request:Request):
    if not desktop_security.DESKTOP_MODE:raise HTTPException(404,"Not found")
    sub=change_hub.subscribe()
    heartbeat=float(getattr(request.app.state,"canonical_sse_heartbeat_seconds",20))
    return StreamingResponse(canonical_sse_events(request,sub,heartbeat),media_type="text/event-stream",headers={**NO_STORE,"X-Accel-Buffering":"no"})
