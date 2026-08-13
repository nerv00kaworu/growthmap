"""Closed production Authority transport composition candidate.

This module is source-only.  It deliberately does not claim TLS, Cloudflare, exact-host,
ceremony, backup, package, or deployment acceptance.  HTTP parsing before ASGI remains an
upstream boundary; :class:`StrictASGIGuard` validates the complete ASGI scope and receive stream
before calling FastAPI, but cannot bound bytes already accepted by the HTTP parser.

The request journal and Authority database are separate SQLite databases.  Distributed atomicity
is therefore not claimed.  A durable PENDING/COMMITTED state machine, an exclusive recovery lease,
and Authority's deterministic idempotent readback close response-loss recovery.  Coordinated
rollback of both stores, or rollback of one store past the other, remains an external witness /
backup-restore boundary.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.metadata
import json
import os
import re
import sqlite3
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .authority_api import (MAX_BODY_BYTES, MAX_HEADER_BYTES, MAX_HEADER_COUNT,
    MAX_HEADER_NAME_BYTES, MAX_HEADER_VALUE_BYTES, PeerDescriptor, ServiceAuthRequest,
    ServiceIdentity, create_authority_app)
from .authority_service import (_absolute, _file_identity, _open_parent, _read_fixed,
    _stat_at, _validate_regular, build_production_authority, load_production_config)

FIXED_CONFIG_PATH = Path("/etc/growthmap-authority-staging-r24/production-composition.json")
CONFIG_BASENAME = "production-composition.json"
CONFIG_FIELDS = {"schema_version","expected_uid","deployment_config_sha256","authority_config_path",
    "edge","replay","listen"}
EDGE_FIELDS = {"provider","identity","source","subject","audience","public_key_path","public_key_sha256"}
REPLAY_FIELDS = {"provider","path","expected_uid","max_entries","retention_seconds","lease_seconds"}
LISTEN_FIELDS = {"host","port"}
def _bind_native_ed25519_provider():
    """Authenticate and bind cryptography's native Ed25519 implementation.

    Python serialization modules and ``sys.modules`` cache entries are not trusted.  The
    constructor, concrete key type, and verify descriptor must be native objects exported by the
    RECORD-authenticated extension.  A fixed RFC 8032 known-answer verification runs before the
    provider is accepted.  A compromised interpreter or modified site-packages remains outside
    this source-level boundary.
    """
    distribution=importlib.metadata.distribution("cryptography")
    root=Path(distribution.locate_file("")).resolve()
    from cryptography.hazmat.bindings import _rust
    origin=Path(getattr(_rust,"__file__","")).resolve()
    try: origin.relative_to(root)
    except ValueError as exc: raise RuntimeError("cryptography_provider_provenance_invalid") from exc
    if not origin.is_file() or not re.fullmatch(r"_rust(?:\.[A-Za-z0-9_]+)*\.(?:so|pyd|dylib)",origin.name):
        raise RuntimeError("cryptography_provider_provenance_invalid")
    records=list(root.glob("cryptography-*.dist-info/RECORD"))
    if len(records)!=1: raise RuntimeError("cryptography_provider_provenance_invalid")
    expected=None
    with records[0].open(newline="",encoding="utf-8") as stream:
        for relative,digest,_size in csv.reader(stream):
            if (root/relative).resolve()==origin: expected=digest;break
    if not expected or not expected.startswith("sha256="):
        raise RuntimeError("cryptography_provider_provenance_invalid")
    actual=base64.urlsafe_b64encode(hashlib.sha256(origin.read_bytes()).digest()).decode().rstrip("=")
    if actual!=expected[7:]: raise RuntimeError("cryptography_provider_provenance_invalid")
    native=getattr(getattr(getattr(_rust,"openssl",None),"ed25519",None),"from_public_bytes",None)
    key_type=getattr(getattr(getattr(_rust,"openssl",None),"ed25519",None),"Ed25519PublicKey",None)
    if (type(key_type) is not type or not callable(native)
            or type(native).__module__!="builtins" or type(native).__name__ not in {"builtin_function_or_method","builtin_method"}
            or getattr(key_type,"__module__","")!="cryptography.hazmat.bindings._rust.openssl.ed25519"
            or type(getattr(key_type,"verify",None)).__name__ not in {"method_descriptor","wrapper_descriptor"}):
        raise RuntimeError("cryptography_provider_provenance_invalid")
    # RFC 8032 test vector 1 (empty message).
    public=bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    signature=bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
    try:
        reference=native(public)
        if type(reference) is not key_type: raise TypeError
        reference.verify(signature,b"")
        try: reference.verify(bytes(64),b"")
        except Exception: pass
        else: raise TypeError
    except Exception as exc: raise RuntimeError("cryptography_provider_known_answer_failed") from exc
    return native,key_type,origin,root

_NATIVE_ED25519_FROM_BYTES, _NATIVE_ED25519_TYPE, _CRYPTOGRAPHY_EXTENSION, _CRYPTOGRAPHY_ROOT = _bind_native_ed25519_provider()
_TCHAR = frozenset(b"!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def _closed_json(raw: bytes) -> dict[str, Any]:
    def pairs(values):
        out={}
        for key,value in values:
            if type(key) is not str or not key.isascii() or key in out: raise ValueError
            out[key]=value
        return out
    try: value=json.loads(raw,object_pairs_hook=pairs)
    except Exception as exc: raise RuntimeError("composition_config_invalid") from exc
    if type(value) is not dict: raise RuntimeError("composition_config_invalid")
    return value


def _digest(value: Any) -> bool:
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}",value) is not None


def _safe_text(value: Any, pattern: str, limit: int=128) -> bool:
    return type(value) is str and value.isascii() and len(value)<=limit and re.fullmatch(pattern,value) is not None


def _fixed_path(value: Any, basename: str) -> Path:
    path=_absolute(value,"composition_path")
    if path.name!=basename or any(ord(c)<0x21 or ord(c)>0x7e for c in str(path)):
        raise RuntimeError("composition_path_invalid")
    # Reject lexical aliases even before any filesystem access.
    if str(path)!=os.path.normpath(str(path)) or "//" in str(path): raise RuntimeError("composition_path_invalid")
    return path


def validate_composition_descriptor(value: dict[str,Any]) -> dict[str,Any]:
    if set(value)!=CONFIG_FIELDS or value.get("schema_version")!=1: raise RuntimeError("composition_config_invalid")
    if (type(value.get("expected_uid")) is not int or value["expected_uid"] <= 0
            or not _digest(value.get("deployment_config_sha256"))):
        raise RuntimeError("composition_config_invalid")
    edge=value.get("edge"); replay=value.get("replay"); listen=value.get("listen")
    if type(edge) is not dict or set(edge)!=EDGE_FIELDS or edge.get("provider")!="ed25519-fixed-v1":
        raise RuntimeError("composition_edge_invalid")
    if not all((_safe_text(edge.get("identity"),r"[A-Za-z0-9._-]{3,128}"),
                _safe_text(edge.get("source"),r"[a-z][a-z0-9_-]{0,31}",32),
                _safe_text(edge.get("subject"),r"[A-Za-z0-9._-]{3,128}"),
                _safe_text(edge.get("audience"),r"[a-z0-9][a-z0-9._-]{2,63}",64),
                _digest(edge.get("public_key_sha256")))): raise RuntimeError("composition_edge_invalid")
    _fixed_path(edge.get("public_key_path"),"edge-public.pem")
    if type(replay) is not dict or set(replay)!=REPLAY_FIELDS or replay.get("provider")!="sqlite-journal-v1":
        raise RuntimeError("composition_replay_invalid")
    _fixed_path(replay.get("path"),"request-journal.sqlite3")
    if (type(replay.get("expected_uid")) is not int or replay["expected_uid"] != value["expected_uid"]
            or type(replay.get("max_entries")) is not int or not 100<=replay["max_entries"]<=1_000_000
            or type(replay.get("retention_seconds")) is not int or not 3600<=replay["retention_seconds"]<=31_536_000
            or type(replay.get("lease_seconds")) is not int or not 1<=replay["lease_seconds"]<=300):
        raise RuntimeError("composition_replay_invalid")
    if type(listen) is not dict or set(listen)!=LISTEN_FIELDS or listen.get("host") not in {"127.0.0.1","::1"} or type(listen.get("port")) is not int or not 1024<=listen["port"]<=65535:
        raise RuntimeError("composition_listen_invalid")
    _fixed_path(value.get("authority_config_path"),"authority-production.json")
    return value


def load_composition_config(path: Path|str, *, expected_uid:int) -> dict[str,Any]:
    if type(expected_uid) is not int or expected_uid <= 0: raise RuntimeError("expected_service_uid_invalid")
    supplied=_absolute(str(path),"fixed_config")
    if supplied!=FIXED_CONFIG_PATH or supplied.name!=CONFIG_BASENAME: raise RuntimeError("fixed_composition_path_invalid")
    cfg=validate_composition_descriptor(_closed_json(_read_fixed(
        supplied,expected_uid=expected_uid,approved_directory_uids={0,expected_uid})))
    if cfg["expected_uid"] != expected_uid: raise RuntimeError("composition_uid_binding_mismatch")
    return cfg


@dataclass(frozen=True)
class AuthenticatedEdgeAdapter:
    """In-process fixed peer provenance; never consults headers, body, environment, or proxy data."""
    production_safe=True; fixture=False; process_local=False
    identity: str
    source: str
    def resolve(self, request) -> PeerDescriptor:
        client=request.scope.get("client")
        if (type(client) not in {tuple,list} or len(client)!=2 or client[0] not in {"127.0.0.1","::1"}):
            raise RuntimeError("untrusted_transport_peer")
        return PeerDescriptor(self.identity,self.source)


class Ed25519ServiceIdentityVerifier:
    production_safe=True; fixture=False; process_local=False
    def __init__(self,public_key:Ed25519PublicKey,*,identity:str,source:str,subject:str,audience:str):
        self.key=public_key; self.identity=identity; self.source=source; self.subject=subject; self.audience=audience
    @staticmethod
    def signed_bytes(request:ServiceAuthRequest)->bytes:
        peer=request.peer
        fields=(request.method,request.path,request.body_sha256,request.timestamp,request.nonce,
            request.audience,request.authority_id,peer.identity if peer else "",peer.source if peer else "")
        return b"growthmap-authority-edge-v1\0"+b"\0".join(v.encode("ascii") for v in fields)
    def verify(self,request):
        if (request.peer!=PeerDescriptor(self.identity,self.source) or request.audience!=self.audience
                or request.method!="POST" or not request.path.startswith("/v1/service/")):
            return None
        try:
            signature=base64.b64decode(request.credential,validate=True)
            if len(signature)!=64:return None
            self.key.verify(signature,self.signed_bytes(request))
        except Exception:return None
        return ServiceIdentity(self.subject,request.audience,request.authority_id)
    def close(self): self.key=None


class SQLiteRequestJournal:
    """Durable bounded request state machine. One process owns the fixed journal by flock."""
    production_safe=True; fixture=False; process_local=False
    NAME="request-journal.sqlite3"; LOCK=".request-journal.lock"
    def __init__(self,path:Path,expected_uid:int,*,max_entries:int,retention_seconds:int,lease_seconds:int):
        import fcntl
        self.path=_fixed_path(str(path),self.NAME); self.uid=expected_uid; self.max_entries=max_entries
        self.retention=retention_seconds; self.lease=lease_seconds; self._lock=threading.RLock(); self._closed=False
        self.dir_fd=-1;self.db_fd=-1;self.lock_fd=-1
        try:
            parent,name=_open_parent(self.path,{0,expected_uid}); os.close(parent)
            self.dir_fd=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC|os.O_NOFOLLOW)
            dst=os.fstat(self.dir_fd)
            if dst.st_uid!=expected_uid or stat.S_IMODE(dst.st_mode)!=0o700: raise RuntimeError("replay_directory_policy_invalid")
            self.lock_fd=os.open(self.LOCK,os.O_RDWR|os.O_CLOEXEC|os.O_NOFOLLOW,dir_fd=self.dir_fd)
            _validate_regular(os.fstat(self.lock_fd),expected_uid,0o600,"replay_lock_policy_invalid",max_bytes=4096)
            fcntl.flock(self.lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.db_fd=os.open(self.NAME,os.O_RDWR|os.O_CLOEXEC|os.O_NOFOLLOW,dir_fd=self.dir_fd)
            st=os.fstat(self.db_fd);_validate_regular(st,expected_uid,0o600,"replay_file_policy_invalid",max_bytes=4*1024**3)
            self.identity=_file_identity(st); self._check_entries(); self._bootstrap()
        except Exception: self.close(); raise
    def _check_entries(self):
        allowed={self.NAME,self.LOCK,self.NAME+"-journal"}
        if not set(os.listdir(self.dir_fd))<=allowed: raise RuntimeError("replay_directory_entry_unapproved")
        if self.db_fd>=0 and _file_identity(os.fstat(self.db_fd))!=_file_identity(_stat_at(self.dir_fd,self.NAME)):
            raise RuntimeError("replay_identity_changed")
    def _connect(self):
        if self._closed:raise RuntimeError("replay_closed")
        self._check_entries();db=sqlite3.connect(f"file:/proc/self/fd/{self.dir_fd}/{self.NAME}?mode=rw",uri=True,timeout=5,isolation_level=None)
        try:
            if db.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower()!="delete":raise RuntimeError("replay_invariant_invalid")
            db.execute("PRAGMA synchronous=FULL");db.execute("PRAGMA trusted_schema=OFF");db.execute("PRAGMA foreign_keys=ON");db.execute("PRAGMA busy_timeout=5000")
            if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":raise RuntimeError("replay_corrupt")
            return db
        except Exception:db.close();raise
    def _bootstrap(self):
        db=self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS request_journal (request_key TEXT PRIMARY KEY,binding TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('PENDING','COMMITTED')),lease_until INTEGER NOT NULL,response BLOB,created_at INTEGER NOT NULL,committed_at INTEGER)")
            db.execute("CREATE INDEX IF NOT EXISTS request_journal_retention ON request_journal(state,committed_at)");db.commit()
        except Exception:db.rollback();raise
        finally:db.close();self._check_entries()
    @staticmethod
    def binding(request:ServiceAuthRequest,subject:str)->str:
        peer=request.peer
        values=(subject,peer.identity if peer else "",peer.source if peer else "",request.nonce,request.timestamp,
            request.body_sha256,request.method,request.path,request.authority_id,request.audience)
        return hashlib.sha256(b"growthmap-journal-binding-v1\0"+b"\0".join(v.encode("ascii") for v in values)).hexdigest()
    def execute(self,request:ServiceAuthRequest,identity:ServiceIdentity,operation:Callable[[],Any]):
        binding=self.binding(request,identity.subject); key=hashlib.sha256((identity.subject+"\0"+request.nonce).encode()).hexdigest();now=int(time.time())
        with self._lock:
            db=self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM request_journal WHERE state='COMMITTED' AND committed_at<?",(now-self.retention,))
                row=db.execute("SELECT binding,state,lease_until,response FROM request_journal WHERE request_key=?",(key,)).fetchone()
                if row:
                    if row[0]!=binding:raise RuntimeError("replay_binding_conflict")
                    if row[1]=="COMMITTED":db.commit();return json.loads(bytes(row[3]))
                    if row[2]>=now:raise RuntimeError("replay_recovery_busy")
                    db.execute("UPDATE request_journal SET lease_until=? WHERE request_key=?",(now+self.lease,key))
                else:
                    count=db.execute("SELECT count(*) FROM request_journal").fetchone()[0]
                    if count>=self.max_entries:raise RuntimeError("replay_capacity_exhausted")
                    db.execute("INSERT INTO request_journal VALUES(?,?, 'PENDING',?,NULL,?,NULL)",(key,binding,now+self.lease,now))
                db.commit()
            except Exception:
                if db.in_transaction:db.rollback()
                db.close();raise
            db.close();self._check_entries()
            # External Authority effect occurs outside this journal transaction. It MUST be
            # deterministic/idempotent for the same binding; PENDING is retained on failure.
            result=operation();encoded=json.dumps(result,separators=(",",":"),sort_keys=True).encode()
            db=self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                row=db.execute("SELECT binding,state FROM request_journal WHERE request_key=?",(key,)).fetchone()
                if row!=(binding,"PENDING"):raise RuntimeError("replay_state_changed")
                db.execute("UPDATE request_journal SET state='COMMITTED',response=?,committed_at=?,lease_until=0 WHERE request_key=?",(encoded,int(time.time()),key));db.commit()
            except Exception:
                if db.in_transaction:db.rollback()
                raise
            finally:db.close();self._check_entries()
            return result
    def close(self):
        if getattr(self,"_closed",True):return
        self._closed=True
        for field in ("db_fd","lock_fd","dir_fd"):
            fd=getattr(self,field,-1)
            if fd>=0:
                try:os.close(fd)
                except OSError:pass
                setattr(self,field,-1)


class StrictASGIGuard:
    """Post-parser ASGI framing guard; upstream parser/Cloudflare limits remain mandatory."""
    production_safe=True; fixture=False; process_local=False
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope.get("type")!="http":return await self.app(scope,receive,send)
        headers=scope.get("headers")
        if type(headers) is not list or len(headers)>MAX_HEADER_COUNT:return await self._reject(send,400)
        seen=set();total=0;length=None
        for row in headers:
            if type(row) not in {tuple,list} or len(row)!=2 or type(row[0]) is not bytes or type(row[1]) is not bytes:return await self._reject(send,400)
            name,value=row;lower=name.lower();total+=len(name)+len(value)
            if (not name or lower in seen or len(name)>MAX_HEADER_NAME_BYTES or len(value)>MAX_HEADER_VALUE_BYTES or total>MAX_HEADER_BYTES
                    or any(c not in _TCHAR for c in name) or any(c<0x20 or c>=0x7f for c in value)):return await self._reject(send,400)
            seen.add(lower)
            if lower==b"transfer-encoding":return await self._reject(send,400)
            if lower==b"content-length":
                if not re.fullmatch(rb"(?:0|[1-9][0-9]*)",value) or len(value)>6:return await self._reject(send,400)
                length=int(value)
        if length is not None and length>MAX_BODY_BYTES:return await self._reject(send,413)
        size=0;terminal=False
        async def guarded_receive():
            nonlocal size,terminal
            message=await receive()
            if terminal:raise RuntimeError("receive_after_terminal")
            if message.get("type")=="http.disconnect":raise RuntimeError("request_disconnected")
            if message.get("type")!="http.request" or type(message.get("body",b"")) is not bytes:raise RuntimeError("request_frame_invalid")
            size+=len(message.get("body",b""))
            if size>MAX_BODY_BYTES or (length is not None and size>length):raise RuntimeError("request_frame_oversize")
            if not message.get("more_body",False):
                terminal=True
                if length is not None and size!=length:raise RuntimeError("request_frame_truncated")
            return message
        try:return await self.app(scope,guarded_receive,send)
        except RuntimeError:return await self._reject(send,400)
    @staticmethod
    async def _reject(send,status):
        await send({"type":"http.response.start","status":status,"headers":[(b"content-type",b"application/json"),(b"cache-control",b"no-store")]})
        await send({"type":"http.response.body","body":b'{"detail":"invalid request"}'})


# Capture reviewed identities and their interfaces once, at module load.  The tuples are held
# by the gate's default argument rather than looked up through a rebindable registry global.
# This is a packaging/accidental-substitution seal, not a sandbox: hostile co-resident Python
# can mutate function defaults or class objects and remains explicitly outside the boundary.
_PROVIDER_SEAL = (
    ("AuthenticatedEdgeAdapter", AuthenticatedEdgeAdapter, type,
     (("resolve", AuthenticatedEdgeAdapter.resolve),)),
    ("Ed25519ServiceIdentityVerifier", Ed25519ServiceIdentityVerifier, type,
     (("verify", Ed25519ServiceIdentityVerifier.verify), ("close", Ed25519ServiceIdentityVerifier.close))),
    ("SQLiteRequestJournal", SQLiteRequestJournal, type,
     (("execute", SQLiteRequestJournal.execute), ("close", SQLiteRequestJournal.close))),
    ("StrictASGIGuard", StrictASGIGuard, type,
     (("__call__", StrictASGIGuard.__call__),)),
    ("create_authority_app", create_authority_app, type(create_authority_app), ()),
    ("build_production_authority", build_production_authority, type(build_production_authority), ()),
)


def _providers_available(seal=_PROVIDER_SEAL) -> None:
    """Pure exact-provider gate; performs no construction, I/O, parsing, or provider calls."""
    namespace=globals()
    for name,expected,expected_type,interface in seal:
        supplied=namespace.get(name)
        if (supplied is not expected or type(supplied) is not expected_type or not callable(supplied)
                or getattr(supplied,"production_safe",None) is not True
                or getattr(supplied,"fixture",None) is not False
                or getattr(supplied,"process_local",None) is not False):
            raise RuntimeError("production_transport_providers_not_configured")
        if any(getattr(supplied,method,None) is not implementation for method,implementation in interface):
            raise RuntimeError("production_transport_providers_not_configured")


def _load_edge_provider(cfg, native=_NATIVE_ED25519_FROM_BYTES, key_type=_NATIVE_ED25519_TYPE):
    edge=cfg["edge"];raw=_read_fixed(Path(edge["public_key_path"]),expected_uid=cfg["expected_uid"],approved_directory_uids={0,cfg["expected_uid"]})
    if hashlib.sha256(raw).hexdigest()!=edge["public_key_sha256"]:raise RuntimeError("edge_public_key_digest_mismatch")
    # Parse the one accepted canonical Ed25519 SPKI shape without importing mutable Python
    # serialization loaders.  Construction and verification remain in the authenticated native
    # extension, and exact concrete type rejects fully implemented/no-op Python subclasses.
    try:
        if not raw.startswith(b"-----BEGIN PUBLIC KEY-----\n") or not raw.endswith(b"-----END PUBLIC KEY-----\n"):raise TypeError
        body=raw[len(b"-----BEGIN PUBLIC KEY-----\n"):-len(b"-----END PUBLIC KEY-----\n")]
        if not body or any(len(line)!=64 for line in body.splitlines()[:-1]) or len(body.splitlines()[-1])>64:raise TypeError
        der=base64.b64decode(b"".join(body.splitlines()),validate=True);prefix=bytes.fromhex("302a300506032b6570032100")
        if len(der)!=44 or not der.startswith(prefix):raise TypeError
        canonical=b"-----BEGIN PUBLIC KEY-----\n"+base64.b64encode(der)+b"\n-----END PUBLIC KEY-----\n"
        if raw!=canonical:raise TypeError
        key=native(der[len(prefix):])
        if type(key) is not key_type:raise TypeError
    except Exception as exc:raise RuntimeError("edge_public_key_invalid") from exc
    return Ed25519ServiceIdentityVerifier(key,identity=edge["identity"],source=edge["source"],subject=edge["subject"],audience=edge["audience"]),AuthenticatedEdgeAdapter(edge["identity"],edge["source"])


def compose(config_path:Path|str, *, expected_uid:int, release_digest:str):
    if type(release_digest) is not str or re.fullmatch(r"[a-f0-9]{64}", release_digest) is None:
        raise RuntimeError("release_digest_invalid")
    _providers_available();cfg=load_composition_config(config_path,expected_uid=expected_uid)
    authority_cfg=load_production_config(cfg["authority_config_path"],expected_uid=expected_uid)
    if (authority_cfg["deployment_config_sha256"]!=cfg["deployment_config_sha256"]
            or authority_cfg["expected_uid"]!=cfg["expected_uid"]
            or authority_cfg["listen"]!=cfg["listen"]):
        raise RuntimeError("composition_authority_binding_mismatch")
    verifier=edge_adapter=journal=authority=None
    try:
        verifier,edge_adapter=_load_edge_provider(cfg)
        r=cfg["replay"];journal=SQLiteRequestJournal(Path(r["path"]),r["expected_uid"],max_entries=r["max_entries"],retention_seconds=r["retention_seconds"],lease_seconds=r["lease_seconds"])
        authority=build_production_authority(cfg["authority_config_path"],expected_uid=expected_uid)
        authority_cfg=authority._production_config
        if authority_cfg["deployment_config_sha256"]!=cfg["deployment_config_sha256"]:
            raise RuntimeError("composition_authority_binding_mismatch")
        class Descriptor:
            production_safe=True;fixture=False;process_local=False
            def descriptor(self):return authority.handshake()|{"status":"active"}
        class Anchor:
            production_safe=True;fixture=False;process_local=False
            def verify(self,value):
                claim=authority.anchor.read()
                digest=hashlib.sha256(authority._ceremony_bytes).hexdigest()
                return claim=={"generation":value["generation"],"ceremony_sha256":digest}
        # Owner/private deactivation is intentionally not exposed by this service composition
        # until a concrete reviewed owner provider is supplied.
        class DenyOwner:
            production_safe=True;fixture=False;process_local=False
            def authorize(self,**_):return None
        app=create_authority_app(authority=authority,service_verifier=verifier,replay_store=None,
            request_journal=journal,owner_verifier=DenyOwner(),signer_descriptor_provider=Descriptor(),
            anchor_verifier=Anchor(),peer_resolver=edge_adapter.resolve,production=True,
            service_audience=cfg["edge"]["audience"],route_policy="service-only",
            release_sha256=release_digest)
        return StrictASGIGuard(app),cfg,(authority,journal,verifier)
    except Exception:
        for item in (authority,journal,verifier):
            if item is not None:
                try:item.close()
                except Exception:pass
        raise


def run(argv=None,*,server_runner=None):
    _providers_available()
    supplied=list(os.sys.argv[1:] if argv is None else argv)
    preflight=supplied[-1:]==["--preflight"]
    if preflight:supplied=supplied[:-1]
    if (len(supplied)!=6 or supplied[0]!="--fixed-config" or supplied[2]!="--expected-service-uid" or supplied[4]!="--release-digest"
            or any("=" in value for value in supplied)):
        raise RuntimeError("production_argv_invalid")
    parser=argparse.ArgumentParser(allow_abbrev=False);parser.add_argument("--fixed-config",required=True);parser.add_argument("--expected-service-uid",required=True,type=int);parser.add_argument("--release-digest",required=True);args=parser.parse_args(supplied)
    if args.expected_service_uid <= 0: raise RuntimeError("expected_service_uid_invalid")
    if re.fullmatch(r"[a-f0-9]{64}",args.release_digest) is None:raise RuntimeError("release_digest_invalid")
    # Syntax and provider capability checks above are side-effect free. Config validation and all
    # provider preflight complete before Authority construction inside compose().
    app,cfg,lifecycle=compose(args.fixed_config,expected_uid=args.expected_service_uid,release_digest=args.release_digest)
    try:
        if preflight:return 0
        if server_runner is None:
            import uvicorn
            server_runner=lambda app,host,port:uvicorn.run(app,host=host,port=port,proxy_headers=False,server_header=False)
        return server_runner(app,cfg["listen"]["host"],cfg["listen"]["port"])
    finally:
        for item in lifecycle:
            try:item.close()
            except Exception:pass


def cli_main():return run()
if __name__=="__main__":cli_main()
