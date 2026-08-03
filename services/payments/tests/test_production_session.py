import ctypes
import ctypes.util
import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import growthmap_payments.api as api
from growthmap_payments.api import Limiter,MockFacilitator,create_app
from growthmap_payments.facilitator import OfficialX402Facilitator
from growthmap_payments.finality import AuthenticatedFinalityReconciler
from growthmap_payments.public_config import APPROVED_BASE_RECIPIENT
from growthmap_payments.session import (
    ARGON2_ITERATIONS_MAX,ARGON2_MEMORY_MAX_KIB,ARGON2_PARALLELISM_MAX,
    AdminSessionVerifier,Argon2idSessionVerifier,
)
from test_payments import CSRF,HEAD,ORIGIN,config


# The production admin hash-file verifier deliberately depends on POSIX
# ownership, mode, no-follow and nonblocking-open guarantees. Windows desktop
# packaging does not host this server boundary and must not pretend NTFS ACLs
# are equivalent. Linux CI runs this complete module; non-POSIX platforms
# verify the explicit fail-closed contract in test_payments.py instead.
pytestmark=pytest.mark.skipif(os.name!="posix",reason="production admin hash-file verifier requires POSIX file-security semantics")


def phc(token=b"correct horse",memory=65536,iterations=3,parallelism=1,variant=2,salt=b"0123456789abcdef",hash_len=32):
    lib=ctypes.CDLL(ctypes.util.find_library("argon2"))
    fn=lib.argon2_hash
    fn.argtypes=[ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_char_p,ctypes.c_size_t,ctypes.c_int,ctypes.c_uint32]
    out=ctypes.create_string_buffer(1024)
    encoded=ctypes.create_string_buffer(1024)
    assert fn(iterations,memory,parallelism,token,len(token),salt,len(salt),out,hash_len,encoded,len(encoded),variant,0x13)==0
    return encoded.value


def hash_file(path,raw=None):
    path.write_bytes(raw or phc());path.chmod(0o600);return path


def loaded(tmp_path,raw=None):
    return Argon2idSessionVerifier.from_hash_file(hash_file(tmp_path/"session.phc",raw))


def test_protocol_and_valid_invalid_bounded_tokens(tmp_path):
    verifier=loaded(tmp_path)
    assert isinstance(verifier,AdminSessionVerifier)
    assert verifier.verify("correct horse") is True
    assert verifier.verify("wrong") is False
    assert verifier.verify("") is False
    assert verifier.verify("x"*4097) is False
    assert verifier.verify("x"*1_000_000) is False
    assert verifier.verify("💳"*1025) is False
    assert verifier.verify("💳"*250_000) is False
    assert verifier.verify("\ud800") is False
    with pytest.raises(TypeError):Argon2idSessionVerifier()


@pytest.mark.parametrize("raw",[
    lambda:phc(variant=1),
    lambda:phc(memory=65535),
    lambda:phc(iterations=2),
    lambda:phc().replace(b"m=65536",b"m=1048577"),
    lambda:phc().replace(b"t=3",b"t=11"),
    lambda:phc().replace(b"p=1",b"p=17"),
    lambda:phc().replace(b"m=65536",b"m=+65536"),
    lambda:phc().replace(b"m=65536",b"m=99999999999"),
    lambda:phc().replace(b"MDEyMzQ1Njc4OWFiY2RlZg",b"c2hvcnQ"),
    lambda:phc().replace(b"MDEyMzQ1Njc4OWFiY2RlZg",b"MDEyMzQ1Njc4OWFiY2RlZh"),
    lambda:phc(salt=b"s"*65),
    lambda:phc(hash_len=31),
    lambda:phc(hash_len=65),
    lambda:b"$argon2id$malformed",
    lambda:phc()+b"\n",
    lambda:b"\xff",
])
def test_rejects_non_argon2id_weak_malformed_and_nonexact(tmp_path,raw):
    path=hash_file(tmp_path/"bad.phc",raw())
    with pytest.raises(RuntimeError,match="admin session verifier unavailable") as caught:Argon2idSessionVerifier.from_hash_file(path)
    assert "argon2" not in str(caught.value).lower() and "correct horse" not in str(caught.value)


def test_rejects_symlink_nonregular_and_oversize_generically(tmp_path):
    good=hash_file(tmp_path/"good")
    link=tmp_path/"link";link.symlink_to(good)
    directory=tmp_path/"directory";directory.mkdir()
    huge=hash_file(tmp_path/"huge",b"x"*1025)
    for path in (link,directory,huge,tmp_path/"missing"):
        with pytest.raises(RuntimeError,match="^admin session verifier unavailable$"):Argon2idSessionVerifier.from_hash_file(path)


def test_fifo_without_writer_fails_closed_without_blocking(tmp_path):
    fifo=tmp_path/"session.fifo";os.mkfifo(fifo,0o600);result=[]
    def load():
        try:Argon2idSessionVerifier.from_hash_file(fifo)
        except Exception as error:result.append(error)
    thread=threading.Thread(target=load,daemon=True);thread.start();thread.join(1)
    assert not thread.is_alive()
    assert len(result)==1 and str(result[0])=="admin session verifier unavailable"


def test_missing_nonblock_fails_closed(tmp_path,monkeypatch):
    path=hash_file(tmp_path/"session.phc")
    monkeypatch.delattr(os,"O_NONBLOCK",raising=False)
    with pytest.raises(RuntimeError,match="^admin session verifier unavailable$"):
        Argon2idSessionVerifier.from_hash_file(path)


def test_argon2_operational_boundaries_without_high_cost_hashing(tmp_path):
    base=phc()
    accepted=(
        base.replace(b"m=65536",f"m={ARGON2_MEMORY_MAX_KIB}".encode()),
        base.replace(b"t=3",f"t={ARGON2_ITERATIONS_MAX}".encode()),
        base.replace(b"p=1",f"p={ARGON2_PARALLELISM_MAX}".encode()),
    )
    for index,raw in enumerate(accepted):
        Argon2idSessionVerifier.from_hash_file(hash_file(tmp_path/f"accepted-{index}",raw))
    rejected=(
        base.replace(b"m=65536",f"m={ARGON2_MEMORY_MAX_KIB+1}".encode()),
        base.replace(b"t=3",f"t={ARGON2_ITERATIONS_MAX+1}".encode()),
        base.replace(b"p=1",f"p={ARGON2_PARALLELISM_MAX+1}".encode()),
    )
    for index,raw in enumerate(rejected):
        with pytest.raises(RuntimeError,match="^admin session verifier unavailable$"):
            Argon2idSessionVerifier.from_hash_file(hash_file(tmp_path/f"rejected-{index}",raw))


class Authority:
    def handshake(self):return {}
    def create_external_entitlement(self,**kwargs):return {}
    def read_external_entitlement_acknowledgement(self,**kwargs):return {}
    def issue_activation_challenge(self,**kwargs):return {}
    def activate_challenge(self,**kwargs):return {}


def production(tmp_path):
    return replace(config(tmp_path/"prod.sqlite"),recipient=APPROVED_BASE_RECIPIENT,production=True,admin_secret_hash="")


def exact_dependencies(tmp_path):
    class Client:pass
    class Provider:
        def finality_evidence(self,intent):return b"{}"
    facilitator=OfficialX402Facilitator("https://facilitator.test",client=Client(),_allow_test_origin=True)
    reconciler=AuthenticatedFinalityReconciler(Provider(),b"k"*32,payee=APPROVED_BASE_RECIPIENT)
    verifier=loaded(tmp_path)
    return facilitator,reconciler,Authority(),verifier


def test_production_unconditionally_rejects_real_nominal_and_allocation_forged_dependencies(tmp_path):
    cfg=production(tmp_path);deps=list(exact_dependencies(tmp_path))
    candidates=[deps,[None,None,None,None],[
        object.__new__(OfficialX402Facilitator),
        object.__new__(AuthenticatedFinalityReconciler),
        Authority(),
        object.__new__(Argon2idSessionVerifier),
    ],[
        type("SubFac",(OfficialX402Facilitator,),{})("https://facilitator.test",client=object(),_allow_test_origin=True),
        type("SubRec",(AuthenticatedFinalityReconciler,),{})(deps[1].provider,b"k"*32,payee=APPROVED_BASE_RECIPIENT),
        Authority(),Mock(spec=Argon2idSessionVerifier),
    ]]
    for candidate in candidates:
        with pytest.raises(RuntimeError,match="^production service blocked: reviewed dependencies unavailable$"):
            create_app(cfg,*candidate[:3],session_verifier=candidate[3])


def test_admin_verifier_origin_csrf_and_development_compatibility(tmp_path):
    verifier=loaded(tmp_path)
    client=TestClient(create_app(config(tmp_path/"admin.sqlite"),MockFacilitator(),session_verifier=verifier))
    url="/v1/admin/orders"
    good={"Authorization":"Bearer correct horse","Origin":ORIGIN,"X-CSRF-Token":CSRF}
    assert client.get(url,headers=good).status_code==200
    for headers in ({**good,"Authorization":"Bearer wrong"},{**good,"Origin":"https://wrong.test"},{**good,"X-CSRF-Token":"wrong"}):
        assert client.get(url,headers=headers).status_code==403
        assert "correct horse" not in client.get(url,headers=headers).text
    legacy=TestClient(create_app(config(tmp_path/"legacy.sqlite"),MockFacilitator()))
    assert legacy.get(url,headers=HEAD).status_code==200


def test_from_env_production_only_loads_new_hash_file_and_stays_closed(tmp_path,monkeypatch):
    monkeypatch.setenv("GROWTHMAP_PAYMENTS_ENV","production")
    monkeypatch.setenv("GROWTHMAP_X402_RECIPIENT",APPROVED_BASE_RECIPIENT)
    path=tmp_path/"session.phc";path.write_bytes(phc());monkeypatch.setenv("GROWTHMAP_ADMIN_SESSION_HASH_FILE",str(path))
    with pytest.raises(RuntimeError,match="reviewed dependencies unavailable"):api.from_env()
    monkeypatch.setenv("GROWTHMAP_ADMIN_SESSION_SHA256","forged-signal")
    with pytest.raises(RuntimeError,match="reviewed dependencies unavailable"):api.from_env()


def test_hash_file_rejects_insecure_metadata_and_missing_nofollow(tmp_path,monkeypatch):
    path=hash_file(tmp_path/"permissions.phc")
    path.chmod(0o644)
    with pytest.raises(RuntimeError,match="^admin session verifier unavailable$"):
        Argon2idSessionVerifier.from_hash_file(path)
    path.chmod(0o600)
    hardlink=tmp_path/"hardlink.phc";os.link(path,hardlink)
    with pytest.raises(RuntimeError,match="^admin session verifier unavailable$"):
        Argon2idSessionVerifier.from_hash_file(path)
    hardlink.unlink()
    real_lstat=os.lstat
    def wrong_owner(candidate):
        value=real_lstat(candidate)
        fields={name:getattr(value,name) for name in dir(value) if name.startswith("st_")}
        fields["st_uid"]=value.st_uid+1
        return SimpleNamespace(**fields)
    monkeypatch.setattr(os,"lstat",wrong_owner)
    with pytest.raises(RuntimeError,match="^admin session verifier unavailable$"):
        Argon2idSessionVerifier.from_hash_file(path)
    monkeypatch.undo()
    monkeypatch.delattr(os,"O_NOFOLLOW",raising=False)
    with pytest.raises(RuntimeError,match="^admin session verifier unavailable$"):
        Argon2idSessionVerifier.from_hash_file(path)


def test_hash_file_rejects_same_inode_metadata_race(tmp_path,monkeypatch):
    path=hash_file(tmp_path/"race.phc")
    real_fstat=os.fstat;calls=0
    def raced(fd):
        nonlocal calls
        calls+=1
        value=real_fstat(fd)
        if calls==2:
            os.utime(path,ns=(value.st_atime_ns,value.st_mtime_ns+1_000_000_000))
            value=real_fstat(fd)
        return value
    monkeypatch.setattr(os,"fstat",raced)
    with pytest.raises(RuntimeError,match="^admin session verifier unavailable$"):
        Argon2idSessionVerifier.from_hash_file(path)


def test_limiter_blocks_expensive_verifier_before_call_and_errors_are_generic(tmp_path,caplog):
    class CountingVerifier:
        def __init__(self):self.calls=0
        def verify(self,token):self.calls+=1;return False
    verifier=CountingVerifier();cfg=replace(config(tmp_path/"limited.sqlite"),rate_limit=1)
    client=TestClient(create_app(cfg,MockFacilitator(),session_verifier=verifier),raise_server_exceptions=False)
    url="/v1/admin/orders";headers={"Authorization":"Bearer sensitive-token","Origin":ORIGIN,"X-CSRF-Token":CSRF}
    first=client.get(url,headers=headers);second=client.get(url,headers=headers)
    assert first.status_code==403 and second.status_code==429 and verifier.calls==1
    assert "sensitive-token" not in first.text+second.text+caplog.text


class TruthyVerifierResult:
    def __bool__(self):return True


@pytest.mark.parametrize("name,result,raises,expected_status",[
    ("false",False,False,403),
    ("none",None,False,403),
    ("string","ok",False,403),
    ("integer-one",1,False,403),
    ("object",object(),False,403),
    ("custom-truthy",TruthyVerifierResult(),False,403),
    ("throw",None,True,403),
    ("exact-true",True,False,200),
])
def test_injected_verifier_accepts_only_builtin_true_once_and_finalizes_policy(tmp_path,name,result,raises,expected_status):
    class Verifier:
        def __init__(self):self.calls=0
        def verify(self,token):
            self.calls+=1
            if raises:raise RuntimeError("verifier failure")
            return result
    verifier=Verifier();app=create_app(replace(config(tmp_path/(name+".sqlite")),rate_limit=2),MockFacilitator(),session_verifier=verifier)
    response=TestClient(app).get("/v1/admin/orders",headers={"Authorization":"Bearer bounded-token","Origin":ORIGIN,"X-CSRF-Token":CSRF})
    assert response.status_code==expected_status and verifier.calls==1
    limiter=app.state.admin_limiter;coarse=("admin-ip-failed","testclient");action=("admin-action","testclient")
    finger_key=next(key for key in limiter.rows if key[0]=="admin-auth")
    if result is True and not raises:
        assert not limiter.rows[coarse] and not limiter.rows[finger_key] and len(limiter.rows[action])==1
    else:
        assert response.json()=={"detail":"admin authentication failed"}
        assert len(limiter.rows[coarse])==1 and len(limiter.rows[finger_key])==1 and not limiter.rows[action]


@pytest.mark.parametrize("name,result",[
    ("string","forged-truthy"),
    ("integer-one",1),
    ("custom-truthy",TruthyVerifierResult()),
])
def test_injected_isolated_fixture_subclass_cannot_select_legacy_path(tmp_path,name,result):
    class ForgedIsolatedVerifier(api._IsolatedTestSessionVerifier):
        def __init__(self):super().__init__("");self.calls=0
        def verify(self,token):self.calls+=1;return result
    verifier=ForgedIsolatedVerifier()
    cfg=replace(config(tmp_path/("forged-"+name+".sqlite")),isolated_test=False,rate_limit=2)
    app=create_app(cfg,MockFacilitator(),session_verifier=verifier)
    response=TestClient(app).get("/v1/admin/orders",headers={"Authorization":"Bearer bounded-token","Origin":ORIGIN,"X-CSRF-Token":CSRF})
    assert response.status_code==403 and response.json()=={"detail":"admin authentication failed"}
    assert verifier.calls==1
    limiter=app.state.admin_limiter;coarse=("admin-ip-failed","testclient");action=("admin-action","testclient")
    finger_key=next(key for key in limiter.rows if key[0]=="admin-auth")
    assert len(limiter.rows[coarse])==1 and len(limiter.rows[finger_key])==1 and not limiter.rows[action]


def test_internal_exact_isolated_fixture_retains_legacy_compatibility(tmp_path):
    cfg=replace(config(tmp_path/"internal-isolated.sqlite"),isolated_test=True)
    app=create_app(cfg,MockFacilitator())
    response=TestClient(app).get("/v1/admin/orders",headers=HEAD)
    assert response.status_code==200
    limiter=app.state.admin_limiter
    assert len(limiter.rows[("admin-action","testclient")])==1
    assert not limiter.rows[("admin-ip-failed","testclient")]
    assert not any(key[0]=="admin-auth" for key in limiter.rows)


def test_coarse_limiter_blocks_rotating_tokens_without_verifier_calls(tmp_path):
    class CountingVerifier:
        def __init__(self):self.calls=0
        def verify(self,token):self.calls+=1;return False
    verifier=CountingVerifier();app=create_app(replace(config(tmp_path/"coarse.sqlite"),rate_limit=1),MockFacilitator(),session_verifier=verifier)
    app.state.admin_limiter.rows[("admin-ip-failed","testclient")].append(float("inf"))
    response=TestClient(app).get("/v1/admin/orders",headers={"Authorization":"Bearer rotated","Origin":ORIGIN,"X-CSRF-Token":CSRF})
    assert response.status_code==429 and verifier.calls==0


def concurrent_admin(tmp_path,tokens,succeeds=False,limit=1):
    class Verifier:
        def __init__(self):self.calls=0;self.lock=threading.Lock()
        def verify(self,token):
            with self.lock:self.calls+=1
            return succeeds
    verifier=Verifier();app=create_app(replace(config(tmp_path/"concurrent.sqlite"),rate_limit=limit),MockFacilitator(),session_verifier=verifier)
    client=TestClient(app);start=threading.Barrier(len(tokens))
    def request(token):
        start.wait()
        return client.get("/v1/admin/orders",headers={"Authorization":"Bearer "+token,"Origin":ORIGIN,"X-CSRF-Token":CSRF}).status_code
    with ThreadPoolExecutor(max_workers=len(tokens)) as pool:statuses=list(pool.map(request,tokens))
    return verifier.calls,statuses


def test_atomic_reservation_same_token_and_rotating_tokens(tmp_path):
    calls,statuses=concurrent_admin(tmp_path,["same"]*8)
    assert calls<=1 and statuses.count(403)==1 and statuses.count(429)==7
    calls,statuses=concurrent_admin(tmp_path,[f"rotated-{i}" for i in range(8)])
    assert calls<=1 and statuses.count(403)==1 and statuses.count(429)==7


def test_action_saturation_reserved_before_successful_expensive_verify(tmp_path):
    calls,statuses=concurrent_admin(tmp_path,["valid"]*8,succeeds=True)
    assert calls<=1 and statuses.count(200)==1 and statuses.count(429)==7


def test_oversized_headers_rejected_before_injected_verifier(tmp_path):
    huge="x"*100_000
    class Verifier:
        calls=0
        def verify(self,token):self.calls+=1;return True
    verifier=Verifier();client=TestClient(create_app(config(tmp_path/(hashlib.sha256(huge[:1].encode()).hexdigest()+".sqlite")),MockFacilitator(),session_verifier=verifier))
    response=client.get("/v1/admin/orders",headers={"Authorization":"Bearer "+huge,"Origin":ORIGIN,"X-CSRF-Token":CSRF})
    assert response.status_code==403 and verifier.calls==0 and huge[:100] not in response.text


def admin_boundary(app):
    endpoint=next(route.endpoint for route in app.routes if getattr(route,"path",None)=="/v1/admin/orders")
    return next(cell.cell_contents for cell in endpoint.__closure__ if getattr(cell.cell_contents,"__name__",None)=="admin")


def direct_request(origin=ORIGIN):
    return Request({"type":"http","method":"GET","path":"/v1/admin/orders","headers":[(b"origin",origin.encode())],"client":("testclient",50000)})


@pytest.mark.parametrize("token,expected_calls",[
    ("💳"*1025,0),("\ud800",0),("x"*4096,1),("é"*2048,1),
])
def test_api_utf8_byte_bound_precedes_injected_verifier(tmp_path,token,expected_calls):
    class Verifier:
        def __init__(self):self.calls=0
        def verify(self,value):self.calls+=1;return False
    verifier=Verifier();app=create_app(replace(config(tmp_path/(str(expected_calls)+hashlib.sha256(repr(token).encode()).hexdigest()+".sqlite")),rate_limit=2),MockFacilitator(),session_verifier=verifier)
    with pytest.raises(HTTPException) as caught:
        admin_boundary(app)(direct_request(),"Bearer "+token,CSRF)
    assert caught.value.status_code==403 and verifier.calls==expected_calls


def test_limiter_retain_removes_only_its_owner_slots():
    limiter=Limiter(2);coarse=("admin-ip-failed","shared");finger=("admin-auth","shared:fingerprint");action=("admin-action","shared")
    first=limiter.reserve(coarse,finger,action);second=limiter.reserve(coarse,finger,action)
    limiter.retain(first,coarse)
    assert list(limiter.rows[coarse])==[first[0][1],second[0][1]]
    assert list(limiter.rows[finger])==[second[1][1]]
    assert list(limiter.rows[action])==[second[2][1]]


@pytest.mark.parametrize("field",["origin","csrf"])
def test_post_reservation_encoding_failure_retains_only_coarse_without_stale_slots(tmp_path,field):
    class Verifier:
        def __init__(self):self.calls=0
        def verify(self,token):self.calls+=1;return True
    verifier=Verifier();cfg=replace(config(tmp_path/(field+"-exception.sqlite")),rate_limit=1)
    if field=="origin":cfg=replace(cfg,allowed_admin_origin="\ud800")
    else:cfg=replace(cfg,csrf_secret="\ud800")
    app=create_app(cfg,MockFacilitator(),session_verifier=verifier);admin=admin_boundary(app);limiter=app.state.admin_limiter
    with pytest.raises(HTTPException) as first:
        admin(direct_request(),"Bearer valid",CSRF)
    assert first.value.status_code==403
    coarse=("admin-ip-failed","testclient");finger_key=next(key for key in limiter.rows if key[0]=="admin-auth");action=("admin-action","testclient")
    assert len(limiter.rows[coarse])==1 and not limiter.rows[finger_key] and not limiter.rows[action]
    with pytest.raises(HTTPException) as second:
        admin(direct_request(),"Bearer valid",CSRF)
    assert second.value.status_code==429 and verifier.calls==1


def test_new_hash_precedes_legacy_and_development_never_enables_legacy(tmp_path,monkeypatch):
    monkeypatch.setenv("GROWTHMAP_PAYMENTS_ENV","test")
    monkeypatch.setenv("GROWTHMAP_PAYMENTS_TEST_MODE","1")
    monkeypatch.setenv("GROWTHMAP_X402_RECIPIENT","0x1111111111111111111111111111111111111111")
    monkeypatch.setenv("GROWTHMAP_ADMIN_SESSION_SHA256","not-the-new-token")
    path=hash_file(tmp_path/"precedence.phc");monkeypatch.setenv("GROWTHMAP_ADMIN_SESSION_HASH_FILE",str(path))
    monkeypatch.setattr(api,"PaymentService",lambda config,facilitator:type("Service",(),{"config":config})())
    app=api.from_env()
    assert app.state.payments.config.admin_secret_hash=="" and app.state.payments.config.isolated_test is False
    monkeypatch.delenv("GROWTHMAP_ADMIN_SESSION_HASH_FILE")
    monkeypatch.setenv("GROWTHMAP_PAYMENTS_ENV","development")
    app=api.from_env()
    assert app.state.payments.config.admin_secret_hash=="" and app.state.payments.config.isolated_test is False


def test_load_failure_and_http_logging_never_leak_phc_path_or_token(tmp_path,monkeypatch,caplog):
    secret_path=tmp_path/"secret-session-name.phc";hash_file(secret_path,b"bad")
    monkeypatch.setenv("GROWTHMAP_PAYMENTS_ENV","test")
    monkeypatch.setenv("GROWTHMAP_ADMIN_SESSION_HASH_FILE",str(secret_path))
    with pytest.raises(RuntimeError) as caught:api.from_env()
    assert str(secret_path) not in str(caught.value) and "bad" not in str(caught.value)
    class ExplodingVerifier:
        def verify(self,token):raise RuntimeError(token)
    client=TestClient(create_app(config(tmp_path/"logs.sqlite"),MockFacilitator(),session_verifier=ExplodingVerifier()),raise_server_exceptions=False)
    response=client.get("/v1/admin/orders",headers={"Authorization":"Bearer never-log-token","Origin":ORIGIN,"X-CSRF-Token":CSRF})
    assert response.status_code==403 and "never-log-token" not in response.text+caplog.text
