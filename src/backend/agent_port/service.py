"""Transactional authorization, scope and canonical mutation service for Agent Port."""
import asyncio,hashlib,hmac,json,threading,uuid
from datetime import datetime,timezone
from fastapi import HTTPException
from sqlalchemy import select,update
from sqlalchemy.exc import IntegrityError,OperationalError
from models.models import Project,Node,Edge,ContentBlock,Branch,ActionLog,AgentReceipt
from api.branching import deep_copy_branch
from services.canonical_nodes import CreateNodeInput, validate_create_node, apply_create_node
from services.canonical_node_updates import (UpdateNodeInput, validate_update_node,
    apply_update_node, finalize_update_maturity)
from services.canonical_edges import (CreateEdgeInput, validate_create_edge,
    apply_create_edge)
from services.canonical_content_blocks import (CreateContentBlockInput,
    validate_create_content_block, apply_create_content_block,
    UpdateContentBlockInput, validate_update_content_block,
    apply_update_content_block, DeleteContentBlockInput,
    validate_delete_content_block, apply_delete_content_block,
    finalize_content_block_maturity)
from services.revisions import TouchedEntities

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

async def descendants(db,project_id,root_id,limit=5000):
    rows=(await db.execute(select(Edge.from_node_id,Edge.to_node_id).where(Edge.project_id==project_id,Edge.relation_type=="child_of"))).all()
    node_projects=dict((await db.execute(select(Node.id,Node.project_id))).all())
    children={}
    for a,b in rows:
        if node_projects.get(a)!=project_id or node_projects.get(b)!=project_id:
            raise HTTPException(409,{"code":"INVALID_GRAPH_SCOPE","message":"Containment edge crosses project boundary"})
        children.setdefault(a,[]).append(b)
    out=set();stack=[root_id]
    while stack:
        cur=stack.pop()
        if cur in out:continue
        out.add(cur)
        if len(out)>limit:raise HTTPException(413,{"code":"SCOPE_TOO_LARGE","message":"Scope traversal exceeds limit"})
        stack.extend(children.get(cur,()))
    return out
async def allowed_nodes(db,grant):
    if grant.node_scope_id:return {grant.node_scope_id}
    if grant.branch_root_id:return await descendants(db,grant.project_id,grant.branch_root_id)
    ids=set((await db.execute(select(Node.id).where(Node.project_id==grant.project_id).limit(5001))).scalars())
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
        # Proposal persistence from older builds materialized omitted optional
        # NodeFields as null. Wire-level explicit null is rejected by Pydantic;
        # discard only this trusted legacy representation here.
        if op.get("op") in {"update_node", "update_content_block"} and isinstance(op.get("fields"), dict):
            op["fields"] = {key: value for key, value in op["fields"].items() if value is not None}
        if op["op"].startswith("create_"):
            oid=op.get("id") or str(uuid.uuid4());op["id"]=oid
            try: uuid.UUID(oid)
            except Exception:raise HTTPException(422,"Invalid generated/provided id")
            if oid in used:raise HTTPException(409,{"code":"ID_CONFLICT","message":"Entity id already exists"})
            used.add(oid)
            if op["op"]=="create_node":new_nodes[oid]=op
            if op["op"]=="create_branch":new_branches[oid]=op
        normalized.append(op)
    # Resolve containment authorization as a fixed point so caller order does not
    # affect scope validation for forward-created parent chains.
    if not (grant.node_scope_id or grant.branch_root_id):
        allowed.update(new_nodes)
    else:
        changed=True
        while changed:
            changed=False
            for nid, candidate in new_nodes.items():
                if nid not in allowed and candidate.get("parent_id") in allowed:
                    allowed.add(nid);changed=True
    def node_ref(nid):
        if nid in known:return known[nid]
        if nid in new_nodes:return new_nodes[nid]
        raise HTTPException(422,{"code":"INVALID_REFERENCE","message":"Node reference does not exist in project"})
    def node_branch(n):return n.branch_id if isinstance(n,Node) else n.get("branch_id")
    def check_ref_revision(n, expected, field):
        current=n.revision if isinstance(n,Node) else 1
        if expected!=current:
            conflict("Entity revision is stale",entity_id=n.id if isinstance(n,Node) else n["id"],expected=expected,current=current,field=field)
    edge_keys=set((await db.execute(select(Edge.from_node_id,Edge.to_node_id,Edge.relation_type).where(
        Edge.project_id==project_id))).all())
    created_block_ids={op["id"] for op in normalized if op["op"]=="create_content_block"}
    deleted_block_ids=set()
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
        elif kind=="update_node":
            n=node_ref(op["node_id"]);refs.append(op["node_id"])
            if not isinstance(n,Node):raise HTTPException(422,"Cannot update a not-yet-created node")
            if op["expected_revision"]!=n.revision:conflict("Entity revision is stale",entity_id=n.id,expected=op["expected_revision"],current=n.revision)
            if not op["fields"]:raise HTTPException(422,"update_node fields cannot be empty")
        elif kind=="create_edge":
            a=node_ref(op["from_node_id"]);b=node_ref(op["to_node_id"]);refs += [op["from_node_id"],op["to_node_id"]]
            check_ref_revision(a,op["expected_from_revision"],"expected_from_revision")
            check_ref_revision(b,op["expected_to_revision"],"expected_to_revision")
            if op["from_node_id"]==op["to_node_id"]:raise HTTPException(422,{"code":"SELF_RELATION","message":"Cannot create a self-relation"})
            edge_key=(op["from_node_id"],op["to_node_id"],op["relation_type"])
            if edge_key in edge_keys:raise HTTPException(409,{"code":"DUPLICATE_RELATION","message":"Duplicate relation"})
            edge_keys.add(edge_key)
            if op["relation_type"]=="child_of" and node_branch(a)!=node_branch(b):raise HTTPException(422,{"code":"BRANCH_MISMATCH","message":"Containment endpoints must share branch"})
        elif kind=="create_content_block":
            n=node_ref(op["node_id"]);refs.append(op["node_id"])
            check_ref_revision(n,op["expected_node_revision"],"expected_node_revision")
        elif kind=="update_content_block":
            if op["block_id"] in used and any(candidate.get("id") == op["block_id"] and candidate["op"] == "create_content_block" for candidate in normalized):
                raise HTTPException(422,{"code":"NEW_BLOCK_UPDATE_UNSUPPORTED","message":"update_content_block supports pre-existing blocks only"})
            block=await db.get(ContentBlock,op["block_id"])
            if not block: raise HTTPException(404,"Block not found")
            n=known.get(block.node_id)
            if not n: raise HTTPException(404,"Node not found")
            refs.append(n.id)
            if op["expected_revision"]!=block.revision: conflict("Entity revision is stale",entity_id=block.id,expected=op["expected_revision"],current=block.revision)
            check_ref_revision(n,op["expected_node_revision"],"expected_node_revision")
            if not op["fields"]: raise HTTPException(422,{"code":"INVALID_CONTENT_BLOCK_UPDATE","message":"update_content_block fields cannot be empty"})
        elif kind=="delete_content_block":
            if op["block_id"] in created_block_ids:
                raise HTTPException(422,{"code":"NEW_BLOCK_DELETE_UNSUPPORTED","message":"delete_content_block supports pre-existing blocks only"})
            if op["block_id"] in deleted_block_ids:
                raise HTTPException(422,{"code":"DUPLICATE_CONTENT_BLOCK_DELETE","message":"Content block may be deleted only once per batch"})
            deleted_block_ids.add(op["block_id"])
            block=await db.get(ContentBlock,op["block_id"])
            if not block: raise HTTPException(404,"Block not found")
            n=known.get(block.node_id)
            if not n: raise HTTPException(404,"Node not found")
            refs.append(n.id)
            if op["expected_revision"]!=block.revision: conflict("Entity revision is stale",entity_id=block.id,expected=op["expected_revision"],current=block.revision)
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
        elif kind in {"update_content_block","delete_content_block"}:
            remember(op["block_id"],op["expected_revision"],"expected_revision")
            block=await db.get(ContentBlock,op["block_id"])
            if block: remember(block.node_id,op["expected_node_revision"],"expected_node_revision")
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
        elif kind in {"update_content_block","delete_content_block"}:
            block=await db.get(ContentBlock,op["block_id"])
            if block: touched_node_ids.add(block.node_id)
    touched_node_ids &= existing_node_ids
    if touched_node_ids:
        existing_touched=(await db.execute(select(Node).where(Node.id.in_(touched_node_ids)))).scalars().all()
    ordered_results=[None]*len(ops)
    result_entities={}
    result_owner_entities={}
    canonical_touched=TouchedEntities()
    update_node_ids={op["node_id"] for op in ops if op["op"] == "update_node"}
    manual_maturity_node_ids={op["node_id"] for op in ops
                              if op["op"] == "update_node" and "maturity" in op["fields"]}
    content_block_owner_ids={op["node_id"] for op in ops
                             if op["op"] == "create_content_block"}
    existing_block_ids={op["block_id"] for op in ops
                        if op["op"] in {"update_content_block","delete_content_block"}}
    existing_blocks={b.id:b for b in (await db.execute(select(ContentBlock).where(
        ContentBlock.id.in_(existing_block_ids)))).scalars().all()} if existing_block_ids else {}
    content_block_owner_ids.update(b.node_id for b in existing_blocks.values())
    for op_index in execution_order:
        op=ops[op_index];kind=op["op"]
        if kind=="create_node":
            identity=actor or grant.agent_identity
            spec=CreateNodeInput(project_id=project.id,node_id=op["id"],parent_id=op.get("parent_id"),branch_id=op.get("branch_id"),title=op["title"],summary=op.get("summary",""),node_type=op.get("node_type","idea"),actor_type="human" if actor else "agent",actor_id=identity,created_by=identity,provenance={"entry":"agent_port"})
            validated=await validate_create_node(db,spec)
            n=await apply_create_node(db,validated,touched=canonical_touched)
            ordered_results[op_index]={"op":kind,"id":n.id,"revision":1};result_entities[op_index]=n
        elif kind=="update_node":
            identity=actor or grant.agent_identity
            spec=UpdateNodeInput(project_id=project.id,node_id=op["node_id"],
                changes=op["fields"],actor_type="human" if actor else "agent",
                actor_id=identity,last_edited_by=identity,
                provenance={"entry":"agent_port","operation_index":op_index})
            validated=await validate_update_node(db,spec)
            n=await apply_update_node(db,validated,touched=canonical_touched,defer_maturity=True)
            ordered_results[op_index]={"op":kind,"id":n.id,"revision":n.revision};result_entities[op_index]=n
        elif kind=="create_edge":
            identity=actor or grant.agent_identity
            spec=CreateEdgeInput(project_id=project.id,edge_id=op["id"],
                from_node_id=op["from_node_id"],to_node_id=op["to_node_id"],
                relation_type=op["relation_type"],weight=op["weight"],note=op["note"],
                is_mainline=False,actor_type="human" if actor else "agent",actor_id=identity,
                provenance={"entry":"agent_port","operation_index":op_index})
            validated=await validate_create_edge(db,spec,allowed_relation_types={
                "child_of","extends","depends_on","supports","alternative_to","refines","references","conflicts_with"})
            e,_=await apply_create_edge(db,validated,touched=canonical_touched,
                touch_endpoint_ids=existing_node_ids)
            ordered_results[op_index]={"op":kind,"id":e.id,"revision":1}
        elif kind=="create_content_block":
            identity=actor or grant.agent_identity
            spec=CreateContentBlockInput(project_id=project.id,node_id=op["node_id"],
                block_id=op["id"],block_type=op["block_type"],content=op["content"],
                order_index=op["order_index"],actor_type="human" if actor else "agent",
                actor_id=identity,created_by=identity,
                provenance={"entry":"agent_port","operation_index":op_index})
            validated=await validate_create_content_block(db,spec)
            b=await apply_create_content_block(db,validated,touched=canonical_touched)
            ordered_results[op_index]={"op":kind,"id":b.id,"revision":1}
        elif kind=="update_content_block":
            identity=actor or grant.agent_identity
            spec=UpdateContentBlockInput(project_id=project.id,block_id=op["block_id"],
                changes=op["fields"],actor_type="human" if actor else "agent",actor_id=identity,
                provenance={"entry":"agent_port","operation_index":op_index})
            validated=await validate_update_content_block(db,spec)
            b=await apply_update_content_block(db,validated,touched=canonical_touched)
            ordered_results[op_index]={"op":kind,"id":b.id,"revision":b.revision}
            result_entities[op_index]=b
            result_owner_entities[op_index]=validated.node
        elif kind=="delete_content_block":
            identity=actor or grant.agent_identity
            spec=DeleteContentBlockInput(project_id=project.id,block_id=op["block_id"],
                actor_type="human" if actor else "agent",actor_id=identity,
                provenance={"entry":"agent_port","operation_index":op_index})
            validated=await validate_delete_content_block(db,spec)
            await apply_delete_content_block(db,validated,touched=canonical_touched)
            ordered_results[op_index]={"op":kind,"id":op["block_id"]}
            result_owner_entities[op_index]=validated.node
        else:
            b=await deep_copy_branch(db,project_id=project.id,source_node_id=op["source_node_id"],name=op["name"].strip(),description=op["description"],branch_id=op["id"],actor=actor or grant.agent_identity)
            ordered_results[op_index]={"op":kind,"id":b.id,"revision":1}
    results=ordered_results
    await finalize_update_maturity(db,update_node_ids,
        manual_maturity_node_ids=manual_maturity_node_ids,touched=canonical_touched)
    await finalize_content_block_maturity(db,
        content_block_owner_ids - manual_maturity_node_ids,touched=canonical_touched)
    canonical_touched.add(*existing_touched)
    canonical_touched.apply()
    # Results are authoritative after union touch application. This matters when
    # a node created earlier in the batch later becomes a parent or is updated.
    for index, entity in result_entities.items():
        ordered_results[index]["revision"]=entity.revision or 1
    for index, owner in result_owner_entities.items():
        ordered_results[index]["node_id"]=owner.id
        ordered_results[index]["node_revision"]=owner.revision or 1
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
        try:
            return await _apply_batch_serialized(db,grant,body,actor=actor,commit=commit,proposal=proposal)
        except Exception:
            # Explicitly release every staged CAS/canonical write for both direct
            # batches and proposal-owned commit=False transactions.
            await db.rollback()
            raise
    finally:
        lock.release()
