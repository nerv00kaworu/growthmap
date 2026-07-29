import hashlib, hmac, json, secrets, uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from models.models import Project, Node, Edge, ContentBlock, Branch, ActionLog, AgentReceipt

NODE_TYPES={"idea","concept","task","question","decision","risk","resource","note","module","spec"}
RELATIONS={"child_of","extends","depends_on","supports","alternative_to","refines","references","conflicts_with"}
BLOCK_TYPES={"paragraph","bullet_list","rule_set","example","risk_note","decision_log","todo","prompt_context","code","quote","table"}

def canonical(value): return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()
def conflict(detail, **extra): raise HTTPException(409,{"code":"REVISION_CONFLICT","message":detail,**extra})
def bump(project, *entities):
    project.revision=(project.revision or 1)+1; project.updated_at=datetime.now(timezone.utc)
    for entity in entities:
        if hasattr(entity,"revision"): entity.revision=(entity.revision or 1)+1

async def descendants(db, root_id):
    edges=(await db.execute(select(Edge.from_node_id,Edge.to_node_id).where(Edge.relation_type=="child_of"))).all(); children={}
    for a,b in edges: children.setdefault(a,[]).append(b)
    out=set(); stack=[root_id]
    while stack:
        cur=stack.pop()
        if cur in out: continue
        out.add(cur); stack.extend(children.get(cur,[]))
    return out

async def allowed_nodes(db, grant):
    if grant.node_scope_id: return {grant.node_scope_id}
    if grant.branch_root_id: return await descendants(db,grant.branch_root_id)
    rows=await db.execute(select(Node.id).where(Node.project_id==grant.project_id)); return set(rows.scalars())

async def validate_scope(db, grant, ids):
    allowed=await allowed_nodes(db,grant)
    if any(x not in allowed for x in ids if x): raise HTTPException(403,{"code":"SCOPE_DENIED","message":"Target is outside grant scope"})

async def apply_batch(db, grant, body, actor=None):
    project=await db.get(Project,grant.project_id)
    if not project: raise HTTPException(404,"Project not found")
    key=body["idempotency_key"]; req_digest=digest(body)
    prior=(await db.execute(select(AgentReceipt).where(AgentReceipt.grant_id==grant.id,AgentReceipt.idempotency_key==key))).scalar_one_or_none()
    if prior:
        if not hmac.compare_digest(prior.request_digest,req_digest): raise HTTPException(409,{"code":"IDEMPOTENCY_MISMATCH","message":"Key was used with different payload"})
        return prior.response
    if body["expected_project_revision"] != project.revision: conflict("Project revision is stale",expected=body["expected_project_revision"],current=project.revision)
    operations=body["operations"]
    if not 1<=len(operations)<=50: raise HTTPException(422,"operations must contain 1..50 items")
    referenced=[]
    for op in operations:
        referenced += [op.get(k) for k in ("node_id","parent_id","from_node_id","to_node_id","source_node_id") if op.get(k)]
    await validate_scope(db,grant,referenced)
    # all expected entity revisions and shapes are validated before writes
    for op in operations:
        kind=op.get("op")
        if kind=="update_node":
            node=await db.get(Node,op.get("node_id"));
            if not node or node.project_id!=project.id: raise HTTPException(404,"Node not found")
            if op.get("expected_revision")!=node.revision: conflict("Entity revision is stale",entity_id=node.id,expected=op.get("expected_revision"),current=node.revision)
            fields=op.get("fields",{}); allowed={"title","summary","description","rules_text","constraints_text","examples_text","questions_text","decision_notes","tags","status","maturity","priority","confidence","workflow_status","file_paths"}
            if not fields or set(fields)-allowed: raise HTTPException(422,"Invalid update_node fields")
        elif kind=="create_node":
            if not isinstance(op.get("title"),str) or not op["title"].strip() or len(op["title"])>500 or op.get("node_type","idea") not in NODE_TYPES: raise HTTPException(422,"Invalid create_node")
        elif kind=="create_edge":
            if op.get("relation_type","child_of") not in RELATIONS: raise HTTPException(422,"Invalid relation")
            for k in ("from_node_id","to_node_id"):
                n=await db.get(Node,op.get(k));
                if not n or n.project_id!=project.id: raise HTTPException(422,"Edge nodes must exist in project")
        elif kind=="create_content_block":
            n=await db.get(Node,op.get("node_id"));
            if not n or n.project_id!=project.id or op.get("block_type","paragraph") not in BLOCK_TYPES or len(canonical(op.get("content",{})))>65536: raise HTTPException(422,"Invalid content block")
        elif kind=="create_branch":
            n=await db.get(Node,op.get("source_node_id"));
            if not n or n.project_id!=project.id or not str(op.get("name","")).strip(): raise HTTPException(422,"Invalid branch")
        else: raise HTTPException(422,f"Unsupported operation: {kind}")
    results=[]; touched=[]
    for op in operations:
        kind=op["op"]
        if kind=="create_node":
            n=Node(id=op.get("id") or str(uuid.uuid4()),project_id=project.id,title=op["title"].strip(),summary=op.get("summary",""),node_type=op.get("node_type","idea"),branch_id=op.get("branch_id"),created_by=actor or grant.agent_identity,last_edited_by=actor or grant.agent_identity);db.add(n);await db.flush();touched.append(n)
            if op.get("parent_id"): db.add(Edge(project_id=project.id,from_node_id=op["parent_id"],to_node_id=n.id,relation_type="child_of",is_mainline=False))
            results.append({"op":kind,"id":n.id})
        elif kind=="update_node":
            n=await db.get(Node,op["node_id"])
            for k,v in op["fields"].items(): setattr(n,k,v)
            n.last_edited_by=actor or grant.agent_identity;touched.append(n);results.append({"op":kind,"id":n.id,"revision":n.revision+1})
        elif kind=="create_edge":
            e=Edge(id=op.get("id") or str(uuid.uuid4()),project_id=project.id,from_node_id=op["from_node_id"],to_node_id=op["to_node_id"],relation_type=op.get("relation_type","child_of"),weight=op.get("weight",1.0),note=op.get("note",""),is_mainline=False);db.add(e);touched.append(e);results.append({"op":kind,"id":e.id})
        elif kind=="create_content_block":
            b=ContentBlock(id=op.get("id") or str(uuid.uuid4()),node_id=op["node_id"],block_type=op.get("block_type","paragraph"),content=op.get("content",{}),order_index=op.get("order_index",0),created_by=actor or grant.agent_identity);db.add(b);touched.append(b);results.append({"op":kind,"id":b.id})
        else:
            b=Branch(id=op.get("id") or str(uuid.uuid4()),project_id=project.id,source_node_id=op["source_node_id"],name=op["name"].strip(),description=op.get("description",""));db.add(b);touched.append(b);results.append({"op":kind,"id":b.id})
    bump(project,*touched)
    response={"receipt_id":str(uuid.uuid4()),"project_id":project.id,"project_revision":project.revision,"results":results,"request_digest":req_digest}
    db.add(AgentReceipt(id=response["receipt_id"],grant_id=grant.id,project_id=project.id,idempotency_key=key,request_digest=req_digest,action_type="batch",status="applied",response=response))
    db.add(ActionLog(project_id=project.id,actor_type="agent" if not actor else "human",actor_id=actor or grant.agent_identity,action_type="agent_batch_applied",payload={"receipt_id":response["receipt_id"],"operation_count":len(operations),"request_digest":req_digest}))
    await db.commit(); return response
