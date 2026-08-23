"""Transactional authorization, scope and canonical mutation service for Agent Port."""
import asyncio,hashlib,hmac,json,threading,uuid
from datetime import datetime,timezone
from fastapi import HTTPException
from sqlalchemy import select,update
from sqlalchemy.exc import IntegrityError,OperationalError
from models.models import Project,Node,Edge,ContentBlock,Branch,ActionLog,AgentReceipt
from api.branching import deep_copy_branch
from api.content_ordering import insert_blocks

def canonical(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)

# Process-local serialization complements the database unique constraint and
# keeps SQLite from surfacing `database locked`.  Fixed stripes keep this
# supplemental lock structure bounded under attacker-controlled keys.
_IDEMPOTENCY_LOCK_STRIPES = tuple(threading.Lock() for _ in range(256))
def idempotency_lock(grant_id: str, key: str) -> threading.Lock:
    token = f"{grant_id}\0{key}".encode()
    index = int.from_bytes(hashlib.sha256(token).digest()[:2], "big") % len(_IDEMPOTENCY_LOCK_STRIPES)
    return _IDEMPOTENCY_LOCK_STRIPES[index]
def digest(v): return hashlib.sha256(canonical(v).encode()).hexdigest()
def conflict(msg,**extra): raise HTTPException(409,{"code":"REVISION_CONFLICT","message":msg,**extra})

def bump(entities=()):
    # Existing entities change once per transaction. New entities remain revision 1.
    seen=set()
    for e in entities:
        if e.id in seen: continue
        seen.add(e.id);e.revision=(e.revision or 1)+1

async def validated_scoped_graph(db,project_id,root_id,limit=5000,allow_external_root_parent=False):
    """Validate an exact project/branch child closure before projecting it."""
    root=await db.get(Node,root_id)
    if not root or root.project_id!=project_id:
        raise HTTPException(409,{"code":"MALFORMED_SCOPE","message":"Grant root is outside its project"})
    branch_id=root.branch_id
    if branch_id is not None:
        branch=await db.get(Branch,branch_id)
        if not branch or branch.project_id!=project_id:
            raise HTTPException(409,{"code":"MALFORMED_SCOPE","message":"Scope branch is outside its project"})
    out={root_id};frontier={root_id};incoming=set();edge_ids=set();parents={}
    while frontier:
        sources=(await db.execute(select(Node).where(Node.id.in_(frontier)))).scalars().all()
        if len(sources)!=len(frontier) or any(n.project_id!=project_id or n.branch_id!=branch_id for n in sources):
            raise HTTPException(409,{"code":"MALFORMED_SCOPE","message":"Scope source crosses project or branch"})
        # Do not trust Edge.project_id to hide a hostile outgoing endpoint.
        edges=(await db.execute(select(Edge).where(
            Edge.from_node_id.in_(frontier),Edge.relation_type=="child_of"
        ))).scalars().all()
        target_ids={edge.to_node_id for edge in edges}
        targets={n.id:n for n in (await db.execute(select(Node).where(Node.id.in_(target_ids)))).scalars().all()} if target_ids else {}
        for edge in edges:
            target=targets.get(edge.to_node_id)
            if (edge.id in edge_ids or edge.to_node_id in incoming or edge.to_node_id in out
                    or edge.project_id!=project_id or not target
                    or target.project_id!=project_id or target.branch_id!=branch_id):
                raise HTTPException(409,{"code":"MALFORMED_SCOPE","message":"Scope graph is not an exact project/branch tree"})
            edge_ids.add(edge.id);incoming.add(edge.to_node_id);parents[edge.to_node_id]=edge.from_node_id
        frontier=target_ids;out.update(frontier)
        if len(out)>limit:raise HTTPException(413,{"code":"SCOPE_TOO_LARGE","message":"Scope traversal exceeds limit"})

    # Outgoing traversal cannot see a second/external parent into the closure.
    inbound=(await db.execute(select(Edge).where(
        Edge.to_node_id.in_(out),Edge.relation_type=="child_of"
    ))).scalars().all()
    source_ids={edge.from_node_id for edge in inbound}
    source_nodes={n.id:n for n in (await db.execute(select(Node).where(Node.id.in_(source_ids)))).scalars().all()} if source_ids else {}
    by_target={}
    for edge in inbound:
        source=source_nodes.get(edge.from_node_id)
        if (edge.project_id!=project_id or not source
                or source.project_id!=project_id or source.branch_id!=branch_id):
            raise HTTPException(409,{"code":"MALFORMED_SCOPE","message":"Scope graph is not an exact project/branch tree"})
        by_target.setdefault(edge.to_node_id,[]).append(edge)
    for target_id in out:
        edges=by_target.get(target_id,[])
        if target_id==root_id:
            if (not allow_external_root_parent and edges) or len(edges)>1:
                raise HTTPException(409,{"code":"MALFORMED_SCOPE","message":"Scope root has invalid ownership"})
        elif len(edges)!=1 or edges[0].from_node_id!=parents.get(target_id):
            raise HTTPException(409,{"code":"MALFORMED_SCOPE","message":"Scope descendant has invalid ownership"})
    return out

async def descendants(db,project_id,root_id,limit=5000):
    return await validated_scoped_graph(db,project_id,root_id,limit)
async def allowed_nodes(db,grant):
    if grant.node_scope_id:
        # A node grant projects only the singleton, but validates its closure.
        await validated_scoped_graph(db,grant.project_id,grant.node_scope_id,allow_external_root_parent=True)
        return {grant.node_scope_id}
    if grant.branch_root_id:return await validated_scoped_graph(db,grant.project_id,grant.branch_root_id)
    ids=set((await db.execute(select(Node.id).where(
        Node.project_id==grant.project_id,Node.branch_id.is_(None)
    ).limit(5001))).scalars())
    if len(ids)>5000:raise HTTPException(413,{"code":"SCOPE_TOO_LARGE","message":"Project graph exceeds Agent Port limit"})
    return ids
async def validate_scope(db,grant,ids):
    allowed=await allowed_nodes(db,grant)
    if any(x and x not in allowed for x in ids):raise HTTPException(403,{"code":"SCOPE_DENIED","message":"Target is outside grant scope"})

async def validate_operations(db,grant,operations):
    """Validate every existing/new reference and exact create containment before writes."""
    project_id=grant.project_id;allowed=await allowed_nodes(db,grant);known=dict()
    rows=(await db.execute(select(Node).where(Node.project_id==project_id))).scalars().all()
    known.update({n.id:n for n in rows});new_nodes={}
    existing_ids={n.id for n in rows}
    branch_rows=(await db.execute(select(Branch).where(Branch.project_id==project_id))).scalars().all()
    branches={b.id:b for b in branch_rows};new_branches={}
    used=set(existing_ids)|set(branches)
    # First reserve all provided/generated IDs so same-batch forward references work.
    normalized=[]
    for model in operations:
        op=model.model_dump(exclude_none=True) if hasattr(model,"model_dump") else dict(model)
        if op["op"].startswith("create_"):
            oid=op.get("id") or str(uuid.uuid4());op["id"]=oid
            try: uuid.UUID(oid)
            except Exception:raise HTTPException(422,"Invalid generated/provided id")
            if oid in used:raise HTTPException(409,{"code":"ID_CONFLICT","message":"Entity id already exists"})
            used.add(oid)
            if op["op"]=="create_node":new_nodes[oid]=op
            if op["op"]=="create_branch":new_branches[oid]=op
        normalized.append(op)
    def node_ref(nid):
        if nid in known:return known[nid]
        if nid in new_nodes:return new_nodes[nid]
        raise HTTPException(422,{"code":"INVALID_REFERENCE","message":"Node reference does not exist in project"})
    def node_branch(n):return n.branch_id if isinstance(n,Node) else n.get("branch_id")
    def check_ref_revision(n, expected, field):
        current=n.revision if isinstance(n,Node) else 1
        if expected!=current:
            conflict("Entity revision is stale",entity_id=n.id if isinstance(n,Node) else n["id"],expected=expected,current=current,field=field)
    for op in normalized:
        kind=op["op"]
        refs=[]
        if kind=="create_node":
            parent=op.get("parent_id")
            # Node/branch scopes cannot create roots; containment must be explicit.
            if (grant.node_scope_id or grant.branch_root_id) and not parent:raise HTTPException(403,{"code":"SCOPE_DENIED","message":"Scoped create_node requires an in-scope parent"})
            if parent:
                pn=node_ref(parent);refs.append(parent)
                check_ref_revision(pn,op["expected_parent_revision"],"expected_parent_revision")
                inherited=node_branch(pn)
                if op.get("branch_id") is None and inherited:op["branch_id"]=inherited
                elif inherited and op.get("branch_id")!=inherited:raise HTTPException(422,{"code":"BRANCH_MISMATCH","message":"Child must inherit parent branch"})
            bid=op.get("branch_id")
            if bid:
                b=branches.get(bid) or new_branches.get(bid)
                if not b:raise HTTPException(422,{"code":"INVALID_BRANCH","message":"Branch must exist in project"})
                if isinstance(b,Branch) and b.status!="active":raise HTTPException(422,{"code":"INACTIVE_BRANCH","message":"Branch is not active"})
                # Branch scoped grants may only use the branch containing their root.
                if grant.branch_root_id and bid!=node_branch(known.get(grant.branch_root_id)):raise HTTPException(403,{"code":"SCOPE_DENIED","message":"Branch outside grant"})
            # Newly created nodes become allowed only through an allowed/newly-contained parent.
            if parent and (parent in allowed or parent in new_nodes):allowed.add(op["id"])
        elif kind=="update_node":
            n=node_ref(op["node_id"]);refs.append(op["node_id"])
            if not isinstance(n,Node):raise HTTPException(422,"Cannot update a not-yet-created node")
            if op["expected_revision"]!=n.revision:conflict("Entity revision is stale",entity_id=n.id,expected=op["expected_revision"],current=n.revision)
            if not op["fields"]:raise HTTPException(422,"update_node fields cannot be empty")
        elif kind=="create_edge":
            a=node_ref(op["from_node_id"]);b=node_ref(op["to_node_id"]);refs += [op["from_node_id"],op["to_node_id"]]
            check_ref_revision(a,op["expected_from_revision"],"expected_from_revision")
            check_ref_revision(b,op["expected_to_revision"],"expected_to_revision")
            if op["relation_type"]=="child_of" and node_branch(a)!=node_branch(b):raise HTTPException(422,{"code":"BRANCH_MISMATCH","message":"Containment endpoints must share branch"})
        elif kind=="create_content_block":
            n=node_ref(op["node_id"]);refs.append(op["node_id"])
            check_ref_revision(n,op["expected_node_revision"],"expected_node_revision")
        elif kind=="create_branch":
            n=node_ref(op["source_node_id"]);refs.append(op["source_node_id"])
            check_ref_revision(n,op["expected_source_revision"],"expected_source_revision")
            if grant.node_scope_id:raise HTTPException(403,{"code":"SCOPE_DENIED","message":"Node scope cannot create branches"})
        if any(r not in allowed for r in refs):raise HTTPException(403,{"code":"SCOPE_DENIED","message":"Every operation reference must be in scope"})
    return normalized

async def _apply_batch_serialized(db,grant,body,actor=None,commit=True,proposal=None):
    key=body["idempotency_key"];req_digest=digest(body);grant_id=grant.id;project_id=grant.project_id
    prior=(await db.execute(select(AgentReceipt).where(AgentReceipt.grant_id==grant_id,AgentReceipt.idempotency_key==key))).scalar_one_or_none()
    if prior:
        if not hmac.compare_digest(prior.request_digest,req_digest):raise HTTPException(409,{"code":"IDEMPOTENCY_MISMATCH","message":"Key was used with different payload"})
        return prior.response
    project=await db.get(Project,project_id)
    if not project:raise HTTPException(404,"Project not found")
    if body["expected_project_revision"]!=project.revision:conflict("Project revision is stale",expected=body["expected_project_revision"],current=project.revision)
    ops=await validate_operations(db,grant,body["operations"]);results=[];existing_touched=[]
    # A single expected revision per existing entity governs the whole pre-batch
    # snapshot. Reject contradictory values rather than depending on op order.
    expectations={}
    def remember(entity_id,expected,field):
        prior=expectations.setdefault(entity_id,expected)
        if prior!=expected: conflict("Conflicting entity revisions in atomic batch",entity_id=entity_id,expected=expected,current=prior,field=field)
    for op in ops:
        kind=op["op"]
        if kind=="update_node": remember(op["node_id"],op["expected_revision"],"expected_revision")
        elif kind=="create_node" and op.get("parent_id"): remember(op["parent_id"],op["expected_parent_revision"],"expected_parent_revision")
        elif kind=="create_edge":
            remember(op["from_node_id"],op["expected_from_revision"],"expected_from_revision")
            remember(op["to_node_id"],op["expected_to_revision"],"expected_to_revision")
        elif kind=="create_content_block": remember(op["node_id"],op["expected_node_revision"],"expected_node_revision")
        elif kind=="create_branch": remember(op["source_node_id"],op["expected_source_revision"],"expected_source_revision")
    # Execute creates only after their transaction-local FK/data dependencies.
    # Validation deliberately permits forward references, so caller order is not
    # an execution order. A stable topological sort preserves caller order among
    # independent operations and rejects impossible cycles before the CAS/write.
    producers={op.get("id"):index for index,op in enumerate(ops) if op["op"].startswith("create_")}
    dependencies=[]
    for op in ops:
        refs=()
        if op["op"]=="create_node": refs=(op.get("parent_id"),op.get("branch_id"))
        elif op["op"]=="create_branch": refs=(op.get("source_node_id"),)
        elif op["op"]=="create_edge": refs=(op.get("from_node_id"),op.get("to_node_id"))
        elif op["op"]=="create_content_block": refs=(op.get("node_id"),)
        dependencies.append({producers[ref] for ref in refs if ref in producers})
    pending=set(range(len(ops)));execution_order=[]
    while pending:
        ready=[index for index in sorted(pending) if dependencies[index].isdisjoint(pending)]
        if not ready:
            raise HTTPException(422,{"code":"CYCLIC_BATCH_DEPENDENCY","message":"Atomic batch contains cyclic create dependencies"})
        execution_order.extend(ready);pending.difference_update(ready)
    # Claim the shared Project CAS atomically after all schema/reference/entity
    # validation and before any canonical insert/update. This closes true
    # separate-session GUI/Agent and Agent/Agent races.
    now=datetime.now(timezone.utc)
    claim=await db.execute(update(Project).where(Project.id==project_id,Project.revision==body["expected_project_revision"]).values(revision=body["expected_project_revision"]+1,updated_at=now))
    if claim.rowcount!=1:
        await db.rollback()
        current=await db.get(Project,project_id)
        conflict("Project revision is stale",expected=body["expected_project_revision"],current=current.revision if current else None)
    project.revision=body["expected_project_revision"]+1;project.updated_at=now
    # Snapshot which node references predate this atomic batch. References to
    # intra-batch creates use expected revision 1 but never double-bump the new row.
    existing_node_ids=set((await db.execute(select(Node.id).where(Node.project_id==project_id))).scalars())
    touched_node_ids=set()
    for op in ops:
        kind=op["op"]
        if kind=="update_node": touched_node_ids.add(op["node_id"])
        elif kind=="create_node" and op.get("parent_id"): touched_node_ids.add(op["parent_id"])
        elif kind=="create_edge": touched_node_ids.update((op["from_node_id"],op["to_node_id"]))
        elif kind=="create_content_block": touched_node_ids.add(op["node_id"])
    touched_node_ids &= existing_node_ids
    if touched_node_ids:
        existing_touched=(await db.execute(select(Node).where(Node.id.in_(touched_node_ids)))).scalars().all()
    ordered_results=[None]*len(ops)
    block_insertions: dict[str, list[tuple[ContentBlock, int | None]]] = {}
    for op_index in execution_order:
        op=ops[op_index];kind=op["op"]
        if kind=="create_node":
            n=Node(id=op["id"],project_id=project.id,title=op["title"].strip(),summary=op.get("summary",""),node_type=op.get("node_type","idea"),branch_id=op.get("branch_id"),created_by=actor or grant.agent_identity,last_edited_by=actor or grant.agent_identity,revision=1);db.add(n)
            await db.flush()
            if op.get("parent_id"):db.add(Edge(project_id=project.id,from_node_id=op["parent_id"],to_node_id=n.id,relation_type="child_of",is_mainline=False,revision=1))
            ordered_results[op_index]={"op":kind,"id":n.id,"revision":1}
        elif kind=="update_node":
            n=await db.get(Node,op["node_id"])
            for k,v in op["fields"].items():
                if v is not None:setattr(n,k,v)
            n.last_edited_by=actor or grant.agent_identity;ordered_results[op_index]={"op":kind,"id":n.id,"revision":n.revision+1}
        elif kind=="create_edge":
            e=Edge(id=op["id"],project_id=project.id,from_node_id=op["from_node_id"],to_node_id=op["to_node_id"],relation_type=op["relation_type"],weight=op["weight"],note=op["note"],is_mainline=False,revision=1);db.add(e);ordered_results[op_index]={"op":kind,"id":e.id,"revision":1}
        elif kind=="create_content_block":
            b=ContentBlock(id=op["id"],node_id=op["node_id"],block_type=op["block_type"],content=op["content"],order_index=op["order_index"],created_by=actor or grant.agent_identity,revision=1)
            block_insertions.setdefault(op["node_id"],[]).append((b,op["order_index"]));ordered_results[op_index]={"op":kind,"id":b.id,"revision":1}
        else:
            b=await deep_copy_branch(db,project_id=project.id,source_node_id=op["source_node_id"],name=op["name"].strip(),description=op["description"],branch_id=op["id"],actor=actor or grant.agent_identity)
            ordered_results[op_index]={"op":kind,"id":b.id,"revision":1}
    changed_block_siblings=[]
    for node_id,insertions in block_insertions.items():
        changed_block_siblings.extend(await insert_blocks(db,node_id,insertions))
        db.add_all([block for block,_requested in insertions])
    results=ordered_results
    bump([*existing_touched,*changed_block_siblings])
    response={"receipt_id":str(uuid.uuid4()),"project_id":project.id,"project_revision":project.revision,"results":results,"request_digest":req_digest}
    db.add(AgentReceipt(id=response["receipt_id"],grant_id=grant_id,project_id=project.id,idempotency_key=key,request_digest=req_digest,action_type="batch",status="applied",response=response))
    db.add(ActionLog(project_id=project.id,actor_type="human" if actor else "agent",actor_id=actor or grant.agent_identity,action_type="agent_batch_applied",payload={"receipt_id":response["receipt_id"],"operation_count":len(ops),"request_digest":req_digest}))
    if proposal is not None:proposal.status="approved";proposal.reviewed_at=datetime.now(timezone.utc)
    try:
        await db.flush()
        if commit:await db.commit()
    except (IntegrityError,OperationalError):
        await db.rollback()
        prior=(await db.execute(select(AgentReceipt).where(AgentReceipt.grant_id==grant_id,AgentReceipt.idempotency_key==key))).scalar_one_or_none()
        if prior and hmac.compare_digest(prior.request_digest,req_digest):return prior.response
        if prior:raise HTTPException(409,{"code":"IDEMPOTENCY_MISMATCH","message":"Key payload mismatch"})
        # A winner proves a genuine same-key race and is recovered above. Other
        # integrity/operational failures are canonical write conflicts, not
        # idempotency races; keep the response stable without leaking DB detail.
        raise HTTPException(409,{"code":"CANONICAL_WRITE_CONFLICT","message":"Atomic canonical write could not be applied"})
    return response

async def apply_batch(db,grant,body,actor=None,commit=True,proposal=None):
    lock=idempotency_lock(grant.id,body["idempotency_key"])
    await asyncio.to_thread(lock.acquire)
    try:
        return await _apply_batch_serialized(db,grant,body,actor=actor,commit=commit,proposal=proposal)
    finally:
        lock.release()
