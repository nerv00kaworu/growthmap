import base64
import hashlib
import json
import os
from dataclasses import fields, replace
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import growthmap_payments.production_composition as pc
from growthmap_payments.api import create_app
from growthmap_payments.public_config import APPROVED_BASE_RECIPIENT, PUBLIC_CONFIG_SHA256
from test_payments import config

pytestmark = pytest.mark.skipif(os.name != "posix", reason="manifest safe-file contract is POSIX-only")
RELEASE = "05e1375449d504eae9d50a5a32705058810f67ca"
CONTEXT = "release-2026-08-03/r2"
ERROR = "^production dependency review manifest unavailable$"
PINS = {name: {key: format(index * 3 + offset, "064x") for offset, key in enumerate(pc._PIN_KEYS, 1)}
        for index, name in enumerate(pc.DEPENDENCIES)}

@pytest.fixture
def trust():
    # Deterministic, isolated test-only signing fixtures; production accepts public keys only.
    private = {name: Ed25519PrivateKey.from_private_bytes(hashlib.sha256(("fixture:" + name).encode()).digest())
               for name in ("release-builder", "security-a", "release-b", "extra-c")}
    public = {name: key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
              for name, key in private.items()}
    policy = {"policy_id": "growthmap-r2", "identities": {
        "release-builder": {"public_key": public["release-builder"], "roles": ["producer"], "organization": "build-org"},
        "security-a": {"public_key": public["security-a"], "roles": ["security_reviewer"], "organization": "security-org"},
        "release-b": {"public_key": public["release-b"], "roles": ["release_reviewer"], "organization": "release-org"},
        "extra-c": {"public_key": public["extra-c"], "roles": ["release_reviewer"], "organization": "extra-org"},
    }}
    return private, policy

def document(trust):
    private, policy = trust
    _, _, _, _, policy_id, policy_digest, identities = pc._snapshot_inputs(RELEASE, PUBLIC_CONFIG_SHA256, CONTEXT, PINS, policy)
    doc = {"schema": "growthmap-production-dependency-review", "version": 2,
           "environment": "production", "release_commit": RELEASE, "ceremony_context_id": CONTEXT,
           "public_config_sha256": PUBLIC_CONFIG_SHA256, "policy_id": policy_id, "policy_sha256": policy_digest,
           "producer_id": "release-builder", "producer_key_sha256": identities["release-builder"][1], "dependencies": {}}
    for name in pc.DEPENDENCIES:
        item = dict(PINS[name]); item["approvals"] = []
        for reviewer in ("security-a", "release-b"):
            role = identities[reviewer][2]
            statement = pc.approval_statement(release_commit=RELEASE, ceremony_context_id=CONTEXT,
                public_config_sha256=PUBLIC_CONFIG_SHA256, policy_id=policy_id, policy_sha256=policy_digest,
                producer_id="release-builder", producer_key_sha256=identities["release-builder"][1],
                dependency_name=name, pins=PINS[name], reviewer_id=reviewer,
                reviewer_key_sha256=identities[reviewer][1], reviewer_role=role)
            item["approvals"].append({"reviewer_id": reviewer, "reviewer_key_sha256": identities[reviewer][1],
                "reviewer_role": role, "signature": base64.b64encode(private[reviewer].sign(statement)).decode()})
        doc["dependencies"][name] = item
    return doc

def raw(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
def manifest(tmp_path, value, name="review.json"):
    path=tmp_path/name; path.write_bytes(raw(value)); path.chmod(0o600); return path
def load(path, trust, **changes):
    args=dict(expected_release_commit=RELEASE, expected_public_config_sha256=PUBLIC_CONFIG_SHA256,
              expected_ceremony_context_id=CONTEXT, expected_dependencies=PINS, trusted_policy=trust[1])
    args.update(changes); return pc.load_production_review_manifest(path, **args)

def test_valid_signed_manifest_returns_allowlisted_immutable_graph_and_no_secret_fields(tmp_path, trust):
    encoded=raw(document(trust)); lowered=encoded.lower()
    assert all(word not in lowered for word in (b"credential",b"private_key",b"token",b"secret"))
    result=load(manifest(tmp_path,document(trust)),trust)
    assert {f.name for f in fields(result)} == {"schema","version","environment","release_commit","ceremony_context_id","public_config_sha256","policy_id","policy_sha256","producer_id","producer_key_sha256","producer_organization","dependencies","manifest_sha256"}
    assert {f.name for f in fields(result.dependencies["facilitator"])} == {"artifact_sha256","config_sha256","evidence_sha256","approvals"}
    with pytest.raises(TypeError): result.dependencies["x"] = object()
    with pytest.raises(Exception): result.release_commit = "f"*40

@pytest.mark.parametrize("kind",["forged-hash","unknown","wrong-key","wrong-signature","self","single","duplicate-reviewer","duplicate-signature"])
def test_forged_or_untrusted_approvals_rejected(tmp_path, trust, kind):
    doc=document(trust); approvals=doc["dependencies"]["facilitator"]["approvals"]
    if kind=="forged-hash": approvals[0]["signature"]="a"*64
    elif kind=="unknown": approvals[0]["reviewer_id"]="stranger"
    elif kind=="wrong-key":
        wrong = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"fixture:wrong-key").digest())
        policy={"policy_id":trust[1]["policy_id"],"identities":{k:{**v,"roles":list(v["roles"])} for k,v in trust[1]["identities"].items()}}
        policy["identities"]["security-a"]["public_key"]=wrong.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        with pytest.raises(RuntimeError,match=ERROR): load(manifest(tmp_path,doc),trust,trusted_policy=policy)
        return
    elif kind=="wrong-signature": approvals[0]["signature"]=base64.b64encode(b"x"*64).decode()
    elif kind=="self": approvals[0]["reviewer_id"]="release-builder"
    elif kind=="single": approvals.pop()
    elif kind=="duplicate-reviewer": approvals[1]=dict(approvals[0])
    else: doc["dependencies"]["finality"]["approvals"][0]["signature"]=approvals[0]["signature"]
    with pytest.raises(RuntimeError,match=ERROR): load(manifest(tmp_path,doc),trust)

def test_producer_reviewer_collision_by_trusted_key_rejected_before_io(tmp_path, trust):
    policy={"policy_id":trust[1]["policy_id"],"identities":{k:dict(v) for k,v in trust[1]["identities"].items()}}; policy["identities"]["security-a"]["public_key"]=policy["identities"]["release-builder"]["public_key"]
    with pytest.raises(RuntimeError,match=ERROR): load(tmp_path/"never-opened",trust,trusted_policy=policy)

@pytest.mark.parametrize("replay",["dependency","release","public","pins","ceremony"])
def test_signature_replay_across_bound_context_rejected(tmp_path, trust, replay):
    doc=document(trust)
    if replay=="dependency": doc["dependencies"]["finality"]["approvals"][0]["signature"]=doc["dependencies"]["facilitator"]["approvals"][0]["signature"]
    elif replay=="release": doc["release_commit"]="f"*40
    elif replay=="public": doc["public_config_sha256"]="f"*64
    elif replay=="pins": doc["dependencies"]["facilitator"]["artifact_sha256"]="f"*64
    else: doc["ceremony_context_id"]="release-elsewhere"
    with pytest.raises(RuntimeError,match=ERROR): load(manifest(tmp_path,doc),trust)

def test_duplicate_evidence_digest_rejected_before_file_io(tmp_path, trust):
    pins={name:dict(value) for name,value in PINS.items()}; pins["finality"]["evidence_sha256"]=pins["facilitator"]["evidence_sha256"]
    with pytest.raises(RuntimeError,match=ERROR): load(tmp_path/"absent",trust,expected_dependencies=pins)

def test_caller_inputs_are_snapshotted_before_file_io(tmp_path, trust, monkeypatch):
    path=manifest(tmp_path,document(trust)); pins={n:dict(v) for n,v in PINS.items()}; policy={"policy_id":trust[1]["policy_id"],"identities":{k:{**v,"roles":list(v["roles"])} for k,v in trust[1]["identities"].items()}}; real=pc._load
    def mutate_then_load(candidate):
        pins["facilitator"]["artifact_sha256"]="f"*64; policy["identities"]["security-a"]["public_key"]=b"x"*32
        return real(candidate)
    monkeypatch.setattr(pc,"_load",mutate_then_load)
    assert pc.load_production_review_manifest(path,expected_release_commit=RELEASE,expected_public_config_sha256=PUBLIC_CONFIG_SHA256,
        expected_ceremony_context_id=CONTEXT,expected_dependencies=pins,trusted_policy=policy).environment=="production"

def test_nfkc_collision_invalid_utf8_bool_and_noncanonical_rejected(tmp_path, trust):
    texts=[]; base=raw(document(trust)).decode()
    texts += [base.replace('"schema":','"Ｓchema":0,"schema":',1), base.replace('"version":2','"version":true'), json.dumps(document(trust),indent=2)]
    for i,text in enumerate(texts):
        path=tmp_path/f"bad{i}"; path.write_text(text); path.chmod(0o600)
        with pytest.raises(RuntimeError,match=ERROR): load(path,trust)
    path=tmp_path/"utf8"; path.write_bytes(b"\xff"); path.chmod(0o600)
    with pytest.raises(RuntimeError,match=ERROR): load(path,trust)

def test_extra_missing_wrong_type_oversize_depth_and_error_redaction(tmp_path, trust):
    docs=[]; extra=document(trust); extra["private_key"]="do-not-leak"; docs.append(extra)
    missing=document(trust); del missing["dependencies"]["finality"]; docs.append(missing)
    wrong=document(trust); wrong["dependencies"]["finality"]["approvals"]={}; docs.append(wrong)
    deep=document(trust); value="x"
    for _ in range(10): value=[value]
    deep["extra"]=value; docs.append(deep)
    for i,doc in enumerate(docs):
        path=manifest(tmp_path,doc,f"sensitive-token-{i}")
        with pytest.raises(RuntimeError) as caught: load(path,trust)
        assert str(caught.value)==pc._ERROR and str(path) not in str(caught.value) and "do-not-leak" not in str(caught.value)
    path=tmp_path/"large"; path.write_bytes(b"x"*(pc._MAX_BYTES+1)); path.chmod(0o600)
    with pytest.raises(RuntimeError,match=ERROR): load(path,trust)

def test_symlink_fifo_directory_hardlink_mode_owner_and_missing_primitive(tmp_path, trust, monkeypatch):
    path=manifest(tmp_path,document(trust)); link=tmp_path/"link"; link.symlink_to(path)
    for unsafe in (link,tmp_path):
        with pytest.raises(RuntimeError,match=ERROR): load(unsafe,trust)
    fifo=tmp_path/"fifo"; os.mkfifo(fifo,0o600)
    with pytest.raises(RuntimeError,match=ERROR): load(fifo,trust)
    hard=tmp_path/"hard"; os.link(path,hard)
    with pytest.raises(RuntimeError,match=ERROR): load(path,trust)
    hard.unlink(); path.chmod(0o644)
    with pytest.raises(RuntimeError,match=ERROR): load(path,trust)
    path.chmod(0o600); real=os.lstat
    def wrong_owner(p):
        v=real(p); values={n:getattr(v,n) for n in dir(v) if n.startswith("st_")}; values["st_uid"]=v.st_uid+1; return SimpleNamespace(**values)
    monkeypatch.setattr(os,"lstat",wrong_owner)
    with pytest.raises(RuntimeError,match=ERROR): load(path,trust)
    monkeypatch.undo(); monkeypatch.delattr(os,"O_NOFOLLOW",raising=False)
    with pytest.raises(RuntimeError,match=ERROR): load(path,trust)

@pytest.mark.parametrize("race",["grow","shrink","replace"])
def test_file_metadata_races_rejected(tmp_path, trust, monkeypatch, race):
    path=manifest(tmp_path,document(trust)); real_fstat=os.fstat; real_lstat=os.lstat; calls=0
    if race in ("grow","shrink"):
        def raced(fd):
            nonlocal calls
            calls+=1; v=real_fstat(fd)
            if calls==2:
                values={n:getattr(v,n) for n in dir(v) if n.startswith("st_")}; values["st_size"]=v.st_size+(1 if race=="grow" else -1); return SimpleNamespace(**values)
            return v
        monkeypatch.setattr(os,"fstat",raced)
    else:
        def replaced(p):
            nonlocal calls
            calls+=1; v=real_lstat(p)
            if calls==2:
                values={n:getattr(v,n) for n in dir(v) if n.startswith("st_")}; values["st_ino"]=v.st_ino+1; return SimpleNamespace(**values)
            return v
        monkeypatch.setattr(os,"lstat",replaced)
    with pytest.raises(RuntimeError,match=ERROR): load(path,trust)

def test_policy_roles_fingerprints_replacement_and_old_v1_rejected(tmp_path, trust):
    mutations=[]
    for field in ("policy_id", "policy_sha256", "producer_key_sha256"):
        doc=document(trust); doc[field] = "f"*64 if field != "policy_id" else "swapped-policy"; mutations.append(doc)
    for field, value in (("reviewer_key_sha256", "f"*64), ("reviewer_role", "release_reviewer")):
        doc=document(trust); doc["dependencies"]["facilitator"]["approvals"][0][field]=value; mutations.append(doc)
    old=document(trust); old["version"]=1; old["ceremony_id"]=old.pop("ceremony_context_id"); mutations.append(old)
    for i,doc in enumerate(mutations):
        with pytest.raises(RuntimeError,match=ERROR): load(manifest(tmp_path,doc,f"mutation-{i}"),trust)
    for identity, role in (("release-builder","security_reviewer"),("security-a","producer"),("extra-c","producer")):
        policy={"policy_id":trust[1]["policy_id"],"identities":{k:{**v,"roles":list(v["roles"])} for k,v in trust[1]["identities"].items()}}
        policy["identities"][identity]["roles"]=[role]
        with pytest.raises(RuntimeError,match=ERROR): load(tmp_path/"absent",trust,trusted_policy=policy)
    policy={"policy_id":"replacement","identities":{k:{**v,"roles":list(v["roles"])} for k,v in trust[1]["identities"].items()}}
    with pytest.raises(RuntimeError,match=ERROR): load(manifest(tmp_path,document(trust)),trust,trusted_policy=policy)


def test_public_statement_monkeypatch_cannot_weaken_verifier(tmp_path, trust, monkeypatch):
    valid=document(trust); monkeypatch.setattr(pc,"approval_statement",lambda **kw: b"weak:"+kw["reviewer_id"].encode())
    assert load(manifest(tmp_path,valid,"valid"),trust).version == 2
    weak=document(trust)
    for name in pc.DEPENDENCIES:
        for approval in weak["dependencies"][name]["approvals"]:
            approval["signature"]=base64.b64encode(trust[0][approval["reviewer_id"]].sign(pc.approval_statement(reviewer_id=approval["reviewer_id"]))).decode()
    with pytest.raises(RuntimeError,match=ERROR): load(manifest(tmp_path,weak,"weak"),trust)


def test_close_failure_is_generic_and_never_succeeds(tmp_path, trust, monkeypatch):
    path=manifest(tmp_path,document(trust)); real_close=os.close
    monkeypatch.setattr(os,"close",lambda fd: (_ for _ in ()).throw(OSError("sensitive-close")))
    with pytest.raises(RuntimeError,match=ERROR): load(path,trust)
    monkeypatch.setattr(os,"read",lambda *_: (_ for _ in ()).throw(OSError("sensitive-body")))
    with pytest.raises(RuntimeError,match=ERROR) as caught: load(path,trust)
    assert "sensitive" not in str(caught.value)
    monkeypatch.setattr(os,"close",real_close)


def test_unauthorized_member_same_org_and_role_slot_rejected(tmp_path, trust):
    doc=document(trust)
    doc["dependencies"]["facilitator"]["approvals"][1]["reviewer_id"]="extra-c"
    with pytest.raises(RuntimeError,match=ERROR): load(manifest(tmp_path,doc),trust)
    policy={"policy_id":trust[1]["policy_id"],"identities":{k:{**v,"roles":list(v["roles"])} for k,v in trust[1]["identities"].items()}}
    policy["identities"]["release-b"]["organization"]="security-org"
    with pytest.raises(RuntimeError,match=ERROR): load(manifest(tmp_path,document(trust),"same-org"),trust,trusted_policy=policy)


@pytest.mark.parametrize("reviewer", ["security-a", "release-b"])
def test_valid_resigned_manifest_rejects_reviewer_in_producer_org(tmp_path, trust, reviewer):
    policy={"policy_id":trust[1]["policy_id"],"identities":{k:{**v,"roles":list(v["roles"])} for k,v in trust[1]["identities"].items()}}
    policy["identities"][reviewer]["organization"]=policy["identities"]["release-builder"]["organization"]
    altered_trust=(trust[0],policy)
    resigned=document(altered_trust)
    with pytest.raises(RuntimeError,match=ERROR): load(manifest(tmp_path,resigned,f"producer-org-{reviewer}"),altered_trust)


def test_valid_crypto_manifest_and_duck_objects_still_cannot_authorize(tmp_path, trust):
    assert load(manifest(tmp_path,document(trust)),trust).environment=="production"
    cfg=replace(config(tmp_path/"prod.sqlite"),recipient=APPROVED_BASE_RECIPIENT,production=True,admin_secret_hash="")
    class Duck:
        production_authorized=True
        def verify(self,*_): return True
        def settle(self,*_): return {"success":True}
    with pytest.raises(RuntimeError,match="^production service blocked: reviewed dependencies unavailable$"):
        create_app(cfg,Duck(),Duck(),Duck(),session_verifier=Duck())
