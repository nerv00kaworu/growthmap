import httpx
import asyncio
import pytest
from ai.diagnostics import classify_ai_exception, LLMInvalidResponse

def response_error(status):
    request=httpx.Request("POST","https://redacted.invalid")
    return httpx.HTTPStatusError("raw-secret-upstream",request=request,response=httpx.Response(status,request=request))

def test_stable_taxonomy_is_safe():
    cases=[(httpx.ReadTimeout("secret prompt"),504,"LLM_TIMEOUT"),(response_error(401),401,"LLM_AUTH_FAILED"),(response_error(403),401,"LLM_AUTH_FAILED"),(response_error(429),429,"LLM_RATE_LIMITED"),(response_error(503),502,"LLM_UPSTREAM_ERROR"),(httpx.ConnectError("key=secret"),502,"LLM_UPSTREAM_ERROR")]
    for exc,status,code in cases:
        d=classify_ai_exception(exc); assert (d.status,d.code)==(status,code); assert "secret" not in d.message
    d=classify_ai_exception(LLMInvalidResponse("raw secret")); assert (d.status,d.code)==(502,"LLM_INVALID_RESPONSE") and "secret" not in d.message

@pytest.mark.parametrize("failure",["get","add","commit","rollback"])
def test_actual_isolated_failure_log_matrix_preserves_sanitized_payload(monkeypatch,failure):
    from ai import routes
    counts={k:0 for k in ["get","add","commit","rollback"]}; captured=[]
    class LogSession:
        async def __aenter__(self): return self
        async def __aexit__(self,*_): return False
        async def get(self,*_): counts["get"]+=1; (_ for _ in ()).throw(RuntimeError()) if failure=="get" else None; return type("N",(),{"project_id":"p"})()
        def add(self,row): counts["add"]+=1; captured.append(row.payload); (_ for _ in ()).throw(RuntimeError()) if failure=="add" else None
        async def commit(self): counts["commit"]+=1; (_ for _ in ()).throw(RuntimeError()) if failure in {"commit","rollback"} else None
        async def rollback(self): counts["rollback"]+=1; (_ for _ in ()).throw(RuntimeError()) if failure=="rollback" else None
    monkeypatch.setattr(routes,"async_session",lambda:LogSession())
    asyncio.run(routes._log_ai_failure("n","expand","provider","model",0,"LLM_TIMEOUT","0123456789abcdef"))
    assert counts[failure]>=1
    if captured: assert set(captured[0])=={"code","request_id","provider_id","model","elapsed_ms","outcome"}
    assert all("secret" not in str(x) for x in captured)


def test_request_rollback_failure_is_swallowed_and_original_error_stable(monkeypatch):
    from ai import routes
    class RequestDB:
        commits=0;rollbacks=0
        async def rollback(self): self.rollbacks+=1; raise RuntimeError("rollback")
    db=RequestDB();monkeypatch.setattr(routes,"_log_ai_failure",lambda *_: asyncio.sleep(0))
    asyncio.run(routes._best_effort_rollback(db));assert db.rollbacks==1 and db.commits==0
    first=routes._safe_error(httpx.ReadTimeout("raw secret"),"0123456789abcdef")
    second=routes._safe_error(httpx.ReadTimeout("different"),"0123456789abcdef")
    assert (first.status_code,first.detail["code"],first.detail["request_id"])==(second.status_code,second.detail["code"],second.detail["request_id"])
