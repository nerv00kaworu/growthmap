import asyncio
import pytest
from ai import routes

SECRET="sk-cancel-never-log"
class DB:
    def __init__(self,stage,entered): self.stage=stage;self.entered=entered;self.commits=0;self.rollbacks=0;self.added=[];self.rollback_fails=False
    async def get(self,*_):
        if self.stage=="get": self.entered.set();await asyncio.Future()
        if self.stage in {"keyboard","system"}: raise KeyboardInterrupt() if self.stage=="keyboard" else SystemExit()
        return type("N",(),{"project_id":"p"})()
    def add(self,v): self.added.append(v)
    async def commit(self):
        if self.stage=="commit": self.entered.set();await asyncio.Future()
        self.commits+=1
    async def rollback(self):
        self.rollbacks+=1
        if self.rollback_fails: raise RuntimeError(SECRET)
class Factory:
    def __init__(self,stage,exit_failure=False,rollback_failure=False):
        self.stage=stage;self.entered=asyncio.Event();self.db=DB(stage,self.entered);self.db.rollback_fails=rollback_failure;self.exits=0;self.exit_args=[];self.exit_failure=exit_failure
    def __call__(self): return self
    async def __aenter__(self):
        if self.stage=="enter": self.entered.set();await asyncio.Future()
        return self.db
    async def __aexit__(self,*args):
        self.exits+=1;self.exit_args.append(args)
        if self.stage=="exit": self.entered.set();await asyncio.Future()
        if self.exit_failure: raise RuntimeError(SECRET)
        return False

async def invoke():
    await routes._log_ai_failure("n","expand","p","m",0,"LLM_TIMEOUT","0123456789abcdef")

@pytest.mark.asyncio
@pytest.mark.parametrize("stage",["enter","get","commit","exit"])
@pytest.mark.parametrize("exit_failure",[False,True],ids=["exit-ok","exit-runtime"])
@pytest.mark.parametrize("rollback_failure",[False,True],ids=["rollback-ok","rollback-runtime"])
async def test_cancellation_at_each_logger_await_preserves_original(monkeypatch,stage,exit_failure,rollback_failure):
    factory=Factory(stage,exit_failure,rollback_failure);monkeypatch.setattr(routes,"async_session",factory)
    task=asyncio.create_task(invoke());await factory.entered.wait();task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    expected_rollbacks = 1 if exit_failure and stage in {"get","commit"} else 0
    assert factory.db.commits==(1 if stage=="exit" else 0) and factory.db.rollbacks==expected_rollbacks
    assert factory.exits==(0 if stage=="enter" else 1)
    if factory.exit_args:
        typ,exc,tb=factory.exit_args[0]
        if stage=="exit": assert typ is None and exc is None and tb is None
        else: assert typ is asyncio.CancelledError and isinstance(exc,asyncio.CancelledError) and tb is not None
    assert SECRET not in repr(factory.db.added)

@pytest.mark.asyncio
@pytest.mark.parametrize("stage,exc",[("keyboard",KeyboardInterrupt),("system",SystemExit)])
@pytest.mark.parametrize("exit_failure",[False,True])
async def test_process_control_baseexceptions_survive_exit_failure(monkeypatch,stage,exc,exit_failure):
    factory=Factory(stage,exit_failure=exit_failure);monkeypatch.setattr(routes,"async_session",factory)
    with pytest.raises(exc): await invoke()
    assert factory.db.commits==0 and factory.exits==1
    typ,value,tb=factory.exit_args[0];assert typ is exc and isinstance(value,exc) and tb is not None

@pytest.mark.asyncio
async def test_nested_rollback_does_not_consume_process_control(monkeypatch):
    factory=Factory("ordinary",rollback_failure=True)
    async def commit(): raise RuntimeError("ordinary logger failure")
    async def rollback(): factory.db.rollbacks+=1;raise SystemExit()
    factory.db.commit=commit;factory.db.rollback=rollback;monkeypatch.setattr(routes,"async_session",factory)
    with pytest.raises(SystemExit): await invoke()
    assert factory.db.commits==0 and factory.db.rollbacks==1

class TransformingFactory(Factory):
    def __init__(self,stage,rollback_failure=False): super().__init__(stage,rollback_failure=rollback_failure)
    async def __aenter__(self):
        if self.stage=="transform-enter":
            self.entered.set()
            try: await asyncio.Future()
            except asyncio.CancelledError: raise RuntimeError(SECRET)
        return self.db
    async def __aexit__(self,*args):
        self.exits+=1;self.exit_args.append(args)
        if self.stage=="transform-exit":
            self.entered.set()
            try: await asyncio.Future()
            except asyncio.CancelledError: raise RuntimeError(SECRET)
        return False

@pytest.mark.asyncio
@pytest.mark.parametrize("stage",["transform-enter","transform-exit"])
@pytest.mark.parametrize("rollback_failure",[False,True],ids=["rollback-ok","rollback-runtime"])
async def test_transformed_cancellation_uses_entry_baseline_and_propagates(monkeypatch,stage,rollback_failure):
    factory=TransformingFactory(stage,rollback_failure);monkeypatch.setattr(routes,"async_session",factory)
    task=asyncio.create_task(invoke());await factory.entered.wait();task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert factory.exits==(1 if stage=="transform-exit" else 0)
    assert factory.db.commits==(1 if stage=="transform-exit" else 0)
    assert factory.db.rollbacks==(1 if stage=="transform-exit" else 0)
    assert SECRET not in repr(factory.db.added)

@pytest.mark.asyncio
async def test_preexisting_cancellation_count_does_not_convert_ordinary_logger_failure(monkeypatch):
    factory=Factory("ordinary");monkeypatch.setattr(routes,"async_session",factory)
    async def get(*_): raise RuntimeError(SECRET)
    factory.db.get=get
    class ExistingCancellation:
        def cancelling(self): return 1
    monkeypatch.setattr(routes.asyncio,"current_task",lambda:ExistingCancellation())
    await invoke()
    assert factory.db.rollbacks==1
