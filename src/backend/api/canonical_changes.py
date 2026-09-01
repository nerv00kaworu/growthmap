"""Transactional canonical graph journal and bounded, hint-only live wakeups."""
from __future__ import annotations
import asyncio, threading, uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from models.models import Project,Node,Edge,ContentBlock,Branch,CanonicalChange

MAX_SAFE_INTEGER=9007199254740991
MAX_IDS=128
MAX_ROWS_PER_PROJECT=2048
GRAPH_TYPES=(Project,Node,Edge,ContentBlock,Branch)


def _state(): return {"nodes":set(),"edges":set(),"blocks":set(),"branches":set(),"parents":set(),"deleted":False,"workspace":False,"overflow":False}
def _add(bucket:set,value):
    if value is None:return False
    if len(bucket)>=MAX_IDS and str(value) not in bucket:return True
    bucket.add(str(value));return False

def mark_canonical_change(session:Session,project_id:str,*,kind="graph",nodes=(),edges=(),blocks=(),branches=(),parents=()):
    """Explicit marker for Core SQL/bulk paths not visible to ORM unit-of-work."""
    pending=session.info.setdefault("canonical_change_aggregate",{})
    row=pending.setdefault(str(project_id),_state())
    for key,values in (("nodes",nodes),("edges",edges),("blocks",blocks),("branches",branches),("parents",parents)):
        for value in values:row["overflow"]|=_add(row[key],value)
    if kind in {"full_refresh","workspace"}:row["deleted"]=True
    if kind=="workspace":row["workspace"]=True


def _project_id(obj:Any,session:Session):
    if isinstance(obj,Project):return str(obj.id) if obj.id else None
    if isinstance(obj,(Node,Edge,Branch)):return str(obj.project_id) if obj.project_id else None
    if isinstance(obj,ContentBlock):
        if not obj.node_id:return None
        # Pending nodes are not guaranteed to be identity-map addressable while
        # before_flush is running; never issue a recursive query from that hook.
        node=next((candidate for candidate in session.new if isinstance(candidate,Node) and str(candidate.id)==str(obj.node_id)),None)
        if node is None:node=session.identity_map.get((Node,(obj.node_id,),None))
        if node is None and not session._flushing:node=session.get(Node,obj.node_id)
        return str(node.project_id) if node else None


def install_journal_hooks():
    if getattr(Session,"_growthmap_change_hooks",False):return
    Session._growthmap_change_hooks=True

    @event.listens_for(Session,"before_flush")
    def collect(session,_ctx,_instances):
        changed=[]
        for obj in (*session.new,*session.deleted):
            if isinstance(obj,GRAPH_TYPES):changed.append(obj)
        for obj in session.dirty:
            if isinstance(obj,GRAPH_TYPES) and session.is_modified(obj,include_collections=False):changed.append(obj)
        for obj in changed:
            if obj in session.new and hasattr(obj,"id") and not obj.id:obj.id=str(uuid.uuid4())
        for obj in changed:
            pid=_project_id(obj,session)
            if not pid:continue
            kind="full_refresh" if obj in session.deleted or isinstance(obj,Branch) else "graph"
            kw={}
            if isinstance(obj,Node):kw["nodes"]=(obj.id,)
            elif isinstance(obj,Edge):
                kw["edges"]=(obj.id,);kw["parents"]=(obj.from_node_id,)
                if obj.relation_type=="child_of":kw["nodes"]=(obj.from_node_id,obj.to_node_id)
                # Only a newly inserted child_of edge can represent an incremental
                # attachment. Existing containment or arbitrary graph edge changes
                # alter topology/edge projections and require fenced refresh.
                if obj not in session.new:kind="full_refresh"
                elif obj.relation_type!="child_of":kind="full_refresh"
            elif isinstance(obj,ContentBlock):kw["blocks"]=(obj.id,);kw["nodes"]=(obj.node_id,)
            elif isinstance(obj,Branch):kw["branches"]=(obj.id,)
            elif isinstance(obj,Project) and obj in session.deleted:kind="workspace"
            mark_canonical_change(session,pid,kind=kind,**kw)

    @event.listens_for(Session,"before_commit")
    def materialize(session):
        if session.in_nested_transaction():return
        # before_commit precedes SQLAlchemy's automatic flush. Flush once to collect
        # every final scalar mutation, then insert exactly one row/project/revision.
        if session.info.get("canonical_change_materializing"):return
        session.info["canonical_change_materializing"]=True
        try:
            session.flush()
            aggregate=session.info.get("canonical_change_aggregate",{})
            publish=[]
            for pid,hints in aggregate.items():
                project=session.get(Project,pid)
                workspace=bool(hints["workspace"] or not project or project in session.deleted)
                revision=int(project.revision or 1) if project and project not in session.deleted else 0
                kind="workspace" if workspace else "full_refresh" if hints["deleted"] or hints["branches"] or hints["overflow"] else "graph"
                # Containment edges may be implicitly inserted with a generated ID
                # during flush; derive the authoritative edge and both endpoints.
                if project and not workspace and hints["nodes"]:
                    node_ids=tuple(hints["nodes"])
                    for edge in session.query(Edge).filter(Edge.project_id==pid,Edge.relation_type=="child_of",Edge.to_node_id.in_(node_ids)).all():
                        hints["overflow"]|=_add(hints["edges"],edge.id);hints["overflow"]|=_add(hints["parents"],edge.from_node_id);hints["overflow"]|=_add(hints["nodes"],edge.from_node_id)
                clean={k:sorted(v) for k,v in hints.items() if isinstance(v,set)}|{"overflow":bool(hints["overflow"])}
                existing=session.query(CanonicalChange).filter(CanonicalChange.project_id==pid,CanonicalChange.project_revision==revision).one_or_none()
                if existing:
                    prior=existing.hints if isinstance(existing.hints,dict) else {}
                    for key in ("nodes","edges","blocks","branches","parents"):clean[key]=sorted(set(clean[key])|set(prior.get(key,())))[:MAX_IDS]
                    clean["overflow"]|=bool(prior.get("overflow")) or any(len(set(clean[k])|set(prior.get(k,())))>MAX_IDS for k in ("nodes","edges","blocks","branches","parents"))
                    kind="workspace" if "workspace" in (kind,existing.kind) else "full_refresh" if "full_refresh" in (kind,existing.kind) or clean["overflow"] else "graph"
                    existing.kind=kind;existing.hints=clean;cursor=existing.id
                else:
                    cursor=str(uuid.uuid4());session.add(CanonicalChange(id=cursor,project_id=pid,project_revision=revision,kind=kind,hints=clean))
                publish.append({"schema":1,"kind":kind,"project_id":pid,"revision":revision,"cursor":cursor,"hints":clean})
            if publish:
                session.flush()
                for payload in publish:
                    if payload["revision"]:
                        session.execute(text("DELETE FROM canonical_changes WHERE project_id=:p AND id NOT IN (SELECT id FROM canonical_changes WHERE project_id=:p ORDER BY created_at DESC,id DESC LIMIT :n)"),{"p":payload["project_id"],"n":MAX_ROWS_PER_PROJECT})
                session.info["canonical_change_publish"]=publish
        finally:session.info.pop("canonical_change_materializing",None)

    @event.listens_for(Session,"after_commit")
    def committed(session):
        # SQLAlchemy emits after_commit for SAVEPOINT commits too. Preserve the
        # outer aggregate and never wake until the real transaction commits.
        if session.in_nested_transaction():return
        payloads=session.info.pop("canonical_change_publish",[])
        session.info.pop("canonical_change_aggregate",None)
        session.info.pop("canonical_change_savepoints",None)
        for payload in payloads:change_hub.publish(payload)

    @event.listens_for(Session,"after_transaction_create")
    def snapshot_nested(session,transaction):
        if transaction.nested:
            source=session.info.get("canonical_change_aggregate",{})
            session.info.setdefault("canonical_change_savepoints",{})[id(transaction)]={pid:{k:(set(v) if isinstance(v,set) else v) for k,v in row.items()} for pid,row in source.items()}

    @event.listens_for(Session,"after_soft_rollback")
    def restore_savepoint(session,transaction):
        snapshots=session.info.get("canonical_change_savepoints",{})
        if transaction.nested:
            session.info["canonical_change_aggregate"]=snapshots.pop(id(transaction),{})
        else:
            session.info.pop("canonical_change_publish",None);session.info.pop("canonical_change_aggregate",None);snapshots.clear()

    @event.listens_for(Session,"after_rollback")
    def discard_outer(session):
        if not session.in_nested_transaction():
            session.info.pop("canonical_change_publish",None);session.info.pop("canonical_change_aggregate",None)

@dataclass(eq=False)
class _Subscriber:
    loop:asyncio.AbstractEventLoop
    queue:asyncio.Queue=field(default_factory=lambda:asyncio.Queue(maxsize=32))
    latest:dict=field(default_factory=dict)

class ChangeHub:
    """Thread/loop-safe; coalesces per project without losing other projects."""
    def __init__(self):self._subscribers:set[_Subscriber]=set();self._lock=threading.Lock()
    def subscribe(self):
        sub=_Subscriber(asyncio.get_running_loop())
        with self._lock:self._subscribers.add(sub)
        return sub
    def unsubscribe(self,sub):
        with self._lock:self._subscribers.discard(sub)
    def publish(self,payload):
        with self._lock:subscribers=tuple(self._subscribers)
        for sub in subscribers:
            def deliver(s=sub,p=dict(payload)):
                key=p["project_id"];s.latest[key]=p
                if key in tuple(s.queue._queue):return
                if s.queue.full():
                    try:old=s.queue.get_nowait();s.latest.pop(old,None)
                    except asyncio.QueueEmpty:pass
                try:s.queue.put_nowait(key)
                except asyncio.QueueFull:pass
            try:sub.loop.call_soon_threadsafe(deliver)
            except RuntimeError:self.unsubscribe(sub)
    async def next(self,sub):
        key=await sub.queue.get();return sub.latest.pop(key)

change_hub=ChangeHub();install_journal_hooks()
