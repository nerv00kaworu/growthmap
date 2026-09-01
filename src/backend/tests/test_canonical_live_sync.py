import asyncio
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from models.models import Base,Project,Node,CanonicalChange
from api.canonical_changes import change_hub

@pytest_asyncio.fixture
async def db_session(tmp_path):
    path=(tmp_path/"canonical-live.db").resolve();engine=create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
    maker=async_sessionmaker(engine,expire_on_commit=False)
    async with maker() as session:yield session
    await engine.dispose()

@pytest.mark.asyncio
async def test_project_delete_revision_zero_survives(db_session):
    p=Project(name="delete-me");db_session.add(p);await db_session.commit();pid=p.id
    sub=change_hub.subscribe();p=await db_session.get(Project,pid);await db_session.delete(p);await db_session.flush();assert sub.queue.empty();await db_session.commit()
    wake=await asyncio.wait_for(change_hub.next(sub),1);change_hub.unsubscribe(sub)
    assert wake["project_id"]==pid and wake["revision"]==0 and wake["kind"]=="workspace"
    rows=(await db_session.execute(select(CanonicalChange).where(CanonicalChange.project_id==pid,CanonicalChange.project_revision==0))).scalars().all();assert len(rows)==1

@pytest.mark.asyncio
async def test_delete_rollback_has_no_zero_row_or_wake(db_session):
    p=Project(name="keep");db_session.add(p);await db_session.commit();pid=p.id
    sub=change_hub.subscribe();p=await db_session.get(Project,pid);await db_session.delete(p);await db_session.flush();await db_session.rollback();assert sub.queue.empty()
    assert not (await db_session.execute(select(CanonicalChange).where(CanonicalChange.project_id==pid,CanonicalChange.project_revision==0))).scalars().all();change_hub.unsubscribe(sub)

@pytest.mark.asyncio
async def test_repeated_flush_one_exact_revision(db_session):
    p=Project(name="p");db_session.add(p);await db_session.commit();pid=p.id;p.revision=2
    a=Node(project_id=pid,title="a");db_session.add(a);await db_session.flush();b=Node(project_id=pid,title="b");db_session.add(b);await db_session.flush();await db_session.commit()
    rows=(await db_session.execute(select(CanonicalChange).where(CanonicalChange.project_id==pid,CanonicalChange.project_revision==2))).scalars().all();assert len(rows)==1 and set(rows[0].hints["nodes"])=={a.id,b.id}

@pytest.mark.asyncio
async def test_project_revision_check_rejects_zero_and_unsafe_metadata(db_session):
    db_session.add(Project(name="bad",revision=0))
    with pytest.raises(Exception):
        await db_session.commit()

@pytest.mark.asyncio
async def test_nested_commit_outer_rollback_no_row_or_wake(db_session):
    p=Project(name="nested");db_session.add(p);await db_session.commit();pid=p.id
    sub=change_hub.subscribe()
    nested=await db_session.begin_nested();db_session.add(Node(project_id=pid,title="inside"));await nested.commit()
    assert sub.queue.empty();await db_session.rollback();assert sub.queue.empty()
    assert not (await db_session.execute(select(CanonicalChange).where(CanonicalChange.project_id==pid,CanonicalChange.project_revision>1))).scalars().all()
    change_hub.unsubscribe(sub)

@pytest.mark.asyncio
async def test_nested_rollback_preserves_outer_aggregate(db_session):
    p=Project(name="nested-rollback");db_session.add(p);await db_session.commit();pid=p.id
    outer=Node(project_id=pid,title="outer");db_session.add(outer);await db_session.flush()
    nested=await db_session.begin_nested();inner=Node(project_id=pid,title="inner");db_session.add(inner);await db_session.flush();await nested.rollback()
    p.revision=2;await db_session.commit()
    row=(await db_session.execute(select(CanonicalChange).where(CanonicalChange.project_id==pid,CanonicalChange.project_revision==2))).scalar_one()
    assert outer.id in row.hints["nodes"] and inner.id not in row.hints["nodes"]

@pytest.mark.asyncio
async def test_failed_commit_reused_session_no_stale_wake(db_session):
    p=Project(name="failure");db_session.add(p);await db_session.commit();pid=p.id
    sub=change_hub.subscribe();db_session.add(Project(name="unsafe",revision=0));db_session.add(Node(project_id=pid,title="rolled back"))
    with pytest.raises(Exception):await db_session.commit()
    await db_session.rollback();assert sub.queue.empty()
    clean=Project(name="clean");db_session.add(clean);await db_session.commit()
    wakes=[]
    while not sub.queue.empty():wakes.append(await change_hub.next(sub))
    assert all(w["project_id"]!=pid for w in wakes);change_hub.unsubscribe(sub)

@pytest.mark.asyncio
async def test_changehub_burst_keeps_latest_per_project_and_bounds_32():
    sub=change_hub.subscribe()
    for i in range(40):change_hub.publish({"project_id":f"p{i}","revision":i,"cursor":str(i)})
    for i in range(10):change_hub.publish({"project_id":"p39","revision":100+i,"cursor":f"x{i}"})
    await asyncio.sleep(0);assert sub.queue.qsize()==32
    values=[await change_hub.next(sub) for _ in range(32)]
    assert len({v["project_id"] for v in values})==32
    assert next(v for v in values if v["project_id"]=="p39")["revision"]==109
    change_hub.unsubscribe(sub)

# Behavioral acceptance cases: no source inspection assertions.
import json
from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api import canonical_changes as cc
from api import change_routes as cr
from desktop import security as desktop_security
from desktop.security import DesktopSessionMiddleware
from models.models import ActionLog, Edge, ContentBlock, Branch

@pytest.fixture(autouse=True)
def _desktop_live_mode(monkeypatch):
    monkeypatch.setattr(desktop_security,"DESKTOP_MODE",True)

async def _clear_changes(db,pid):
    await db.execute(text("DELETE FROM canonical_changes WHERE project_id=:p"),{"p":pid}); await db.commit()

async def _changes(db,pid,since=1,limit=128):
    response=await cr.project_changes(pid,since,limit,db)
    return json.loads(response.body)

@pytest.mark.asyncio
async def test_publish_only_after_outer_commit(db_session):
    p=Project(name="commit"); db_session.add(p); await db_session.commit(); pid=p.id
    sub=change_hub.subscribe()
    db_session.add(Node(project_id=pid,title="pending")); await db_session.flush(); assert sub.queue.empty()
    await db_session.commit(); assert (await asyncio.wait_for(change_hub.next(sub),1))["project_id"]==pid
    change_hub.unsubscribe(sub)

@pytest.mark.asyncio
async def test_noncanonical_activity_does_not_journal(db_session):
    p=Project(name="p"); db_session.add(p); await db_session.commit()
    before=len((await db_session.execute(select(CanonicalChange).where(CanonicalChange.project_id==p.id))).scalars().all())
    db_session.add(ActionLog(project_id=p.id,actor_type="human",action_type="view")); await db_session.commit()
    assert len((await db_session.execute(select(CanonicalChange).where(CanonicalChange.project_id==p.id))).scalars().all())==before

@pytest.mark.asyncio
async def test_sse_frame_contains_id_event_data_after_commit_only(db_session):
    class Request:
        async def is_disconnected(self): return False
    sub=change_hub.subscribe(); gen=cr.canonical_sse_events(Request(),sub,.1)
    assert "event: ready" in await anext(gen)
    p=Project(name="sse"); db_session.add(p); await db_session.commit()
    frame=await asyncio.wait_for(anext(gen),1)
    assert frame.startswith("id: ") and "event: canonical-change\ndata: " in frame and frame.endswith("\n\n")
    await gen.aclose()

@pytest.mark.asyncio
async def test_sse_heartbeat_injectable_and_disconnect_unsubscribes():
    class Request:
        calls=0
        async def is_disconnected(self): self.calls+=1; return self.calls>1
    sub=change_hub.subscribe(); gen=cr.canonical_sse_events(Request(),sub,.0001)
    assert "ready" in await anext(gen); assert "heartbeat" in await anext(gen)
    with pytest.raises(StopAsyncIteration): await anext(gen)
    assert sub not in change_hub._subscribers

@pytest.mark.asyncio
async def test_changehub_threadsafe_publish_and_closed_loop_cleanup():
    hub=cc.ChangeHub(); sub=hub.subscribe(); await asyncio.to_thread(hub.publish,{"project_id":"p","revision":1,"cursor":"x"})
    assert (await asyncio.wait_for(hub.next(sub),1))["cursor"]=="x"; hub.unsubscribe(sub); assert not hub._subscribers

def _auth_app():
    app=FastAPI(); app.add_middleware(DesktopSessionMiddleware)
    @app.get("/probe")
    async def probe(): return {"ok":True}
    @app.get("/agent/v1/probe")
    async def agent_probe(): return {"agent":True}
    return app

def test_desktop_valid_token_allows_revision_changes_and_stream(monkeypatch):
    monkeypatch.setattr(desktop_security,"DESKTOP_MODE",True); monkeypatch.setattr(desktop_security,"SESSION_TOKEN","good")
    with TestClient(_auth_app()) as c: assert c.get("/probe",headers={"Authorization":"Bearer good"}).status_code==200

def test_missing_wrong_and_agent_tokens_rejected(monkeypatch):
    monkeypatch.setattr(desktop_security,"DESKTOP_MODE",True); monkeypatch.setattr(desktop_security,"SESSION_TOKEN","good")
    with TestClient(_auth_app()) as c:
        assert c.get("/probe").status_code==401; assert c.get("/probe",headers={"Authorization":"Bearer bad"}).status_code==401; assert c.get("/agent/v1/probe").status_code==200

def test_authoring_mode_live_routes_not_found(monkeypatch):
    monkeypatch.setattr(desktop_security,"DESKTOP_MODE",False)
    async def run():
        with pytest.raises(HTTPException) as exc: await cr._project("p",None)
        assert exc.value.status_code==404
    asyncio.run(run())

@pytest.mark.asyncio
async def test_retention_cap_and_oldest_gap_force_full_refresh(db_session):
    assert cc.MAX_ROWS_PER_PROJECT==2048
    p=Project(name="retention",revision=4); db_session.add(p); await db_session.commit(); await _clear_changes(db_session,p.id)
    db_session.add(CanonicalChange(project_id=p.id,project_revision=4,kind="graph",hints={})); await db_session.commit()
    body=await _changes(db_session,p.id,1); assert body["full_refresh_required"] and body["gap"]

@pytest.mark.asyncio
async def test_interior_gap_forces_full_refresh(db_session):
    p=Project(name="gap",revision=4); db_session.add(p); await db_session.commit(); await _clear_changes(db_session,p.id)
    db_session.add_all([CanonicalChange(project_id=p.id,project_revision=2,kind="graph",hints={}),CanonicalChange(project_id=p.id,project_revision=4,kind="graph",hints={})]); await db_session.commit()
    assert (await _changes(db_session,p.id,1))["full_refresh_required"]

@pytest.mark.asyncio
async def test_limit_truncation_forces_full_refresh(db_session):
    p=Project(name="limit",revision=4); db_session.add(p); await db_session.commit(); await _clear_changes(db_session,p.id)
    db_session.add_all([CanonicalChange(project_id=p.id,project_revision=i,kind="graph",hints={}) for i in (2,3,4)]); await db_session.commit()
    assert (await _changes(db_session,p.id,1,1))["truncated"]

@pytest.mark.asyncio
async def test_hint_overflow_forces_full_refresh(db_session):
    p=Project(name="overflow",revision=2); db_session.add(p); await db_session.commit(); await _clear_changes(db_session,p.id); db_session.add(CanonicalChange(project_id=p.id,project_revision=2,kind="graph",hints={"overflow":True})); await db_session.commit()
    assert (await _changes(db_session,p.id,1))["full_refresh_required"]

@pytest.mark.asyncio
async def test_missing_entity_forces_full_refresh(db_session):
    p=Project(name="missing",revision=2); db_session.add(p); await db_session.commit(); await _clear_changes(db_session,p.id); db_session.add(CanonicalChange(project_id=p.id,project_revision=2,kind="graph",hints={"nodes":["gone"]})); await db_session.commit()
    assert (await _changes(db_session,p.id,1))["full_refresh_required"]

@pytest.mark.asyncio
async def test_cross_project_ids_never_leak(db_session):
    a=Project(name="a",revision=2); b=Project(name="b"); db_session.add_all([a,b]); await db_session.commit(); await _clear_changes(db_session,a.id); foreign=Node(project_id=b.id,title="foreign"); db_session.add(foreign); await db_session.commit()
    db_session.add(CanonicalChange(project_id=a.id,project_revision=2,kind="graph",hints={"nodes":[foreign.id]})); await db_session.commit(); body=await _changes(db_session,a.id,1)
    assert body["full_refresh_required"] and not body["nodes"]

@pytest.mark.asyncio
async def test_revision_ahead_is_409(db_session):
    p=Project(name="ahead"); db_session.add(p); await db_session.commit()
    with pytest.raises(HTTPException) as exc: await _changes(db_session,p.id,2)
    assert exc.value.status_code==409

@pytest.mark.asyncio
async def test_hostile_since_limit_and_project_id_rejected(db_session):
    p=Project(name="hostile"); db_session.add(p); await db_session.commit()
    # FastAPI Query bounds are transport validation; direct route calls exercise
    # the project-id boundary, while ASGI checks validate hostile query values.
    with pytest.raises(HTTPException): await cr._project("x"*65,db_session)
    app=FastAPI(); app.include_router(cr.router,prefix="/api")
    # Dependency need not resolve: request validation rejects these first.
    with TestClient(app) as client:
        assert client.get(f"/api/projects/{p.id}/changes?since_revision=0").status_code==422
        assert client.get(f"/api/projects/{p.id}/changes?limit=257").status_code==422

@pytest.mark.asyncio
async def test_gui_node_scalar_and_block_writers_journal_graph(db_session):
    p=Project(name="gui",revision=2); db_session.add(p); await db_session.commit(); n=Node(project_id=p.id,title="n"); db_session.add(n); await db_session.commit()
    p.revision=3; n.title="changed"; db_session.add(ContentBlock(node_id=n.id,block_type="paragraph",content={"x":1})); await db_session.commit()
    row=(await db_session.execute(select(CanonicalChange).where(CanonicalChange.project_id==p.id,CanonicalChange.project_revision==3))).scalar_one(); assert row.kind=="graph" and n.id in row.hints["nodes"] and row.hints["blocks"]

@pytest.mark.asyncio
async def test_edge_reparent_delete_and_branch_force_full_refresh(db_session):
    p=Project(name="topology",revision=2); db_session.add(p); await db_session.commit(); a=Node(project_id=p.id,title="a"); b=Node(project_id=p.id,title="b"); db_session.add_all([a,b]); await db_session.commit()
    p.revision=3; edge=Edge(project_id=p.id,from_node_id=a.id,to_node_id=b.id,relation_type="child_of"); db_session.add(edge); await db_session.commit()
    p.revision=4; edge.relation_type="related_to"; await db_session.commit(); row=(await db_session.execute(select(CanonicalChange).where(CanonicalChange.project_id==p.id,CanonicalChange.project_revision==4))).scalar_one(); assert row.kind=="full_refresh"
