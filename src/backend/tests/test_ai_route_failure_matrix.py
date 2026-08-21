import asyncio
import httpx
import pytest
from fastapi import HTTPException
from ai import routes

SECRET = "sk-live-never-log"
REQUEST_ID = "0123456789abcdef"

class RequestDB:
    def __init__(self, rollback_fails=False):
        self.commits=0; self.rollbacks=0; self.rollback_fails=rollback_fails
    async def rollback(self):
        self.rollbacks += 1
        if self.rollback_fails: raise RuntimeError(SECRET)
    async def get(self,*_): return None

class LogDB:
    def __init__(self, stage):
        self.stage=stage; self.added=[]; self.commits=0; self.rollbacks=0
    async def get(self,*_):
        if self.stage=="get": raise RuntimeError(SECRET)
        return type("N",(),{"project_id":"project"})()
    def add(self,value):
        if self.stage=="add": raise RuntimeError(SECRET)
        self.added.append(value)
    async def commit(self):
        self.commits += 1
        if self.stage in {"commit","rollback"}: raise RuntimeError(SECRET)
    async def rollback(self):
        self.rollbacks += 1
        if self.stage=="rollback": raise RuntimeError(SECRET)

class SessionFactory:
    def __init__(self, stage): self.stage=stage; self.db=LogDB(stage); self.entered=0; self.exited=0
    def __call__(self):
        if self.stage=="factory": raise RuntimeError(SECRET)
        return self
    async def __aenter__(self):
        self.entered += 1
        if self.stage=="enter": raise RuntimeError(SECRET)
        return self.db
    async def __aexit__(self,*_):
        self.exited += 1
        if self.stage=="exit": raise RuntimeError(SECRET)


def context():
    return {"children":[],"siblings":[],"ancestor_path":[],"current":{"title":"x","summary":""}}

ROUTES=[
 ("expand", routes.expand_node, lambda: routes.ExpandRequest(node_id="node",provider_id="provider",provider_revision=1,selection_revision=1)),
 ("deepen", routes.deepen_node, lambda: routes.DeepenRequest(node_id="node",provider_id="provider",provider_revision=1,selection_revision=1)),
]
FAILURES=[
 ("timeout",lambda:httpx.ReadTimeout(SECRET),504,"LLM_TIMEOUT"),
 ("auth",lambda:httpx.HTTPStatusError(SECRET,request=httpx.Request("POST","https://provider.invalid"),response=httpx.Response(401)),401,"LLM_AUTH_FAILED"),
 ("network",lambda:httpx.ConnectError(SECRET),502,"LLM_UPSTREAM_ERROR"),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("route_name,route,request_factory",ROUTES)
@pytest.mark.parametrize("failure_name,failure,status,code",FAILURES)
@pytest.mark.parametrize("request_rollback_fails",[False,True],ids=["request-rollback-ok","request-rollback-fails"])
@pytest.mark.parametrize("logger_stage",["success","factory","enter","get","add","commit","rollback","exit"])
async def test_real_route_and_isolated_logger_failure_matrix(monkeypatch,route_name,route,request_factory,failure_name,failure,status,code,request_rollback_fails,logger_stage):
    request_db=RequestDB(request_rollback_fails)
    session=SessionFactory(logger_stage)
    async def config(*_): return type("Config",(),{"model":"bounded-model"})(),"provider"
    class Provider:
        async def complete(self,*_,**__): raise failure()
    async def build(*_): return context()
    monkeypatch.setattr(routes,"build_node_context",build)
    monkeypatch.setattr(routes,"_to_llm_config",config)
    monkeypatch.setattr(routes,"get_provider",lambda _:Provider())
    monkeypatch.setattr(routes,"_request_id",lambda:REQUEST_ID)
    monkeypatch.setattr(routes,"async_session",session)
    with pytest.raises(HTTPException) as caught:
        await route(request_factory(),request_db)
    diagnostic=(caught.value.status_code,caught.value.detail["code"],caught.value.detail["request_id"])
    assert diagnostic==(status,code,REQUEST_ID)
    assert request_db.commits==0 and request_db.rollbacks==1
    assert SECRET not in repr(caught.value.detail)
    if logger_stage=="success":
        assert session.db.commits==1 and session.db.rollbacks==0 and len(session.db.added)==1
        entry=session.db.added[0]
        assert entry.action_type==f"ai_{route_name}_failed"
        assert entry.payload.keys()=={"code","request_id","provider_id","model","elapsed_ms","outcome"}
        assert entry.payload|{"elapsed_ms":0}=={"code":code,"request_id":REQUEST_ID,"provider_id":"provider","model":"bounded-model","elapsed_ms":0,"outcome":"failed"}
        assert SECRET not in repr(entry.payload)
    elif logger_stage not in {"factory","enter"}:
        assert session.db.rollbacks==1
    assert SECRET not in repr(session.db.added)
