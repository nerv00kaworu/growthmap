"""Executable two-OS-process provider recovery/crash protocol evidence."""
import asyncio, json, multiprocessing as mp, os, sqlite3, time
from pathlib import Path
import pytest


def _child(db_url, provider_id, revision, operation, recorder, start, result, cut=None, fail_store=False, fail_finalize=False):
    os.environ["DATABASE_URL"]=db_url
    from db.database import async_session
    from models.models import ProviderConfig
    from api.provider_authority import recover_external_secret
    async def run():
        async with async_session() as session:
            provider=await session.get(ProviderConfig,provider_id)
            start.wait(10)
            def record():
                if fail_store: raise RuntimeError("external unavailable")
                with open(recorder,"a",encoding="utf8") as f:
                    f.write(json.dumps({"operation":operation,"revision":revision,"provider":provider_id})+"\n");f.flush();os.fsync(f.fileno())
            def after_claim():
                if cut=="after-claim": os._exit(71)
            def after_mutate():
                if cut=="after-mutate": os._exit(72)
            if fail_finalize:
                original=session.commit; calls=0
                async def commit():
                    nonlocal calls
                    calls+=1
                    if calls==2: raise RuntimeError("finalize unavailable")
                    return await original()
                session.commit=commit
            try:
                await recover_external_secret(session,provider,revision,None,record,after_claim=after_claim,after_mutate=after_mutate)
                result.put(("ok",None))
            except BaseException as e:
                result.put(("error",getattr(e,"status_code",type(e).__name__),str(e)))
    try: asyncio.run(run())
    except BaseException as error:
        try: result.put(("child-error",type(error).__name__,str(error)))
        finally: raise


def _db(tmp_path):
    path=tmp_path/"recovery.sqlite"
    con=sqlite3.connect(path)
    con.execute("CREATE TABLE provider_configs (id VARCHAR(36) PRIMARY KEY,name TEXT NOT NULL,provider_type VARCHAR(30) NOT NULL,endpoint TEXT,auth_type VARCHAR(20),secret_env_key VARCHAR(128),model_name TEXT,capabilities JSON,cost_level VARCHAR(10),enabled BOOLEAN,settings JSON,created_at DATETIME,updated_at DATETIME,revision INTEGER NOT NULL,secret_change_pending BOOLEAN NOT NULL,secret_change_claim VARCHAR(64),secret_change_operation_id VARCHAR(64))")
    con.execute("INSERT INTO provider_configs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",("provider","P","mock","","env","KEY","m","[]","none",1,"{}",None,None,2,1,None,None))
    con.commit();con.close();return path

def _state(path):
    con=sqlite3.connect(path);row=con.execute("SELECT revision,secret_change_pending,secret_change_claim FROM provider_configs WHERE id='provider'").fetchone();con.close();return row

def _run(tmp_path, operations, cuts=None, failures=None, spellings=None):
    db=_db(tmp_path);recorder=tmp_path/"mutations.jsonl";ctx=mp.get_context("spawn");start=ctx.Event();result=ctx.Queue();children=[]
    cuts=cuts or [None]*len(operations);failures=failures or [{} for _ in operations]
    urls=spellings or [f"sqlite+aiosqlite:///{db}"]*len(operations)
    for operation,cut,failure,url in zip(operations,cuts,failures,urls):
        p=ctx.Process(target=_child,args=(url,"provider",2,operation,str(recorder),start,result,cut,failure.get("store",False),failure.get("finalize",False)));p.start();children.append(p)
    start.set()
    deadline=time.monotonic()+60
    try:
        for p in children:
            p.join(max(0,deadline-time.monotonic()))
            assert not p.is_alive(),f"provider recovery child {p.pid} exceeded measured custody bound"
    finally:
        for p in children:
            if p.is_alive():p.terminate()
        for p in children:p.join(5)
    outcomes=[]
    while not result.empty():outcomes.append(result.get())
    records=[json.loads(x) for x in recorder.read_text().splitlines()] if recorder.exists() else []
    return db,children,outcomes,records

@pytest.mark.parametrize("operation",["set","delete"])
def test_two_process_same_revision_has_one_external_winner_and_stale_loser(tmp_path,operation):
    db,_,outcomes,records=_run(tmp_path,[operation,operation])
    assert sorted(x[0] for x in outcomes)==["error","ok"]
    errors=[x for x in outcomes if x[0]=="error"]
    assert [x[1] for x in errors]==[409],errors
    assert records==[{"operation":operation,"revision":2,"provider":"provider"}]
    assert _state(db)==(2,0,None)

def test_set_delete_ordering_and_equivalent_sqlite_spellings_share_lock(tmp_path):
    db=tmp_path/"recovery.sqlite"
    urls=[f"sqlite+aiosqlite:///{db}",f"sqlite+aiosqlite:///{db.parent}/./recovery.sqlite"]
    actual,_,outcomes,records=_run(tmp_path,["set","delete"],spellings=urls)
    assert sorted(x[0] for x in outcomes)==["error","ok"] and len(records)==1
    assert records[0]["operation"] in {"set","delete"} and _state(actual)==(2,0,None)

@pytest.mark.parametrize("operation",["set","delete"])
def test_kill_after_claim_releases_os_lock_and_retry_mutates_once(tmp_path,operation):
    db,children,_,records=_run(tmp_path,[operation],cuts=["after-claim"])
    assert children[0].exitcode==71 and records==[] and _state(db)[:2]==(2,1)
    # Fresh process deterministically replaces the dead claim.
    ctx=mp.get_context("spawn");start=ctx.Event();q=ctx.Queue();p=ctx.Process(target=_child,args=(f"sqlite+aiosqlite:///{db}","provider",2,operation,str(tmp_path/"mutations.jsonl"),start,q));p.start();start.set();p.join(15)
    assert p.exitcode==0 and q.get()==("ok",None) and _state(db)==(2,0,None)

@pytest.mark.parametrize("operation",["set","delete"])
def test_kill_after_external_mutation_replays_at_least_once_with_same_identity(tmp_path,operation):
    db,children,_,records=_run(tmp_path,[operation],cuts=["after-mutate"])
    assert children[0].exitcode==72 and len(records)==1 and _state(db)[:2]==(2,1)
    ctx=mp.get_context("spawn");start=ctx.Event();q=ctx.Queue();p=ctx.Process(target=_child,args=(f"sqlite+aiosqlite:///{db}","provider",2,operation,str(tmp_path/"mutations.jsonl"),start,q));p.start();start.set();p.join(15)
    final=[json.loads(x) for x in (tmp_path/"mutations.jsonl").read_text().splitlines()]
    assert p.exitcode==0 and q.get()==("ok",None) and final==[records[0],records[0]] and _state(db)==(2,0,None)

@pytest.mark.parametrize("failure",["store","finalize"])
def test_external_or_finalize_failure_retains_pending_and_is_retryable(tmp_path,failure):
    db,_,outcomes,records=_run(tmp_path,["set"],failures=[{failure:True}])
    assert outcomes[0][0]=="error" and _state(db)[:2]==(2,1)
    assert len(records)==(1 if failure=="finalize" else 0)
    ctx=mp.get_context("spawn");start=ctx.Event();q=ctx.Queue();p=ctx.Process(target=_child,args=(f"sqlite+aiosqlite:///{db}","provider",2,"set",str(tmp_path/"mutations.jsonl"),start,q));p.start();start.set();p.join(15)
    assert p.exitcode==0 and q.get()==("ok",None) and _state(db)==(2,0,None)
