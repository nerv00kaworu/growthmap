"""Fail-closed Linux PEM custody loader and authorized two-person ceremony validation.

The local file and manual external witness controls reduce accidental rollback; they are not
cryptographic rollback proof. Production deployment must drill the exact filesystem, including
ACL, mount, overlay/FUSE/network-filesystem and atomic-rename semantics.
"""
from __future__ import annotations
import hashlib, hmac, json, os, re, stat, sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

MAX_PEM_BYTES=16*1024
PEM_RE=re.compile(br"-----BEGIN PRIVATE KEY-----\r?\n(?:[A-Za-z0-9+/]{1,64}\r?\n)*[A-Za-z0-9+/]{1,64}={0,2}\r?\n-----END PRIVATE KEY-----\r?\n?\Z")
HEX_RE=re.compile(r"[a-f0-9]{64}")
ID_RE=re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")
AUTH_RE=re.compile(r"[a-z0-9][a-z0-9_-]{2,63}")
TIME_RE=re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?Z")
DESCRIPTOR_FIELDS={"schema_version","authority_id","key_id","generation","predecessor_generation","predecessor_ceremony_sha256","public_pem_sha256","public_spki_der_sha256","private_pem_sha256","ceremony_record_sha256","ceremony_at","activated_at","release_sha256","deployment_config_sha256","witness","change_id","status"}
RECORD_FIELDS={"schema_version","record","acknowledgements"}
RECORD_BODY_FIELDS=DESCRIPTOR_FIELDS-{"schema_version","ceremony_record_sha256"}
ACK_FIELDS={"reviewer_id","signature"}
ROSTER_ENTRY_FIELDS={"role","public_key_pem","public_spki_der_sha256"}
WITNESS_FIELDS={"reference","version","digest"}

def canonical(value:Any)->bytes:return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def _hex(v):return type(v) is str and HEX_RE.fullmatch(v) is not None
def _stable(a,b):return (a.st_dev,a.st_ino,a.st_mode,a.st_uid,a.st_gid,a.st_nlink,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_dev,b.st_ino,b.st_mode,b.st_uid,b.st_gid,b.st_nlink,b.st_size,b.st_mtime_ns,b.st_ctime_ns)
def _utc(v):
    if type(v) is not str or not TIME_RE.fullmatch(v):return None
    try:d=datetime.fromisoformat(v[:-1]+"+00:00")
    except ValueError:return None
    if d.tzinfo is None or d.utcoffset()!=timezone.utc.utcoffset(d) or d.isoformat(timespec="microseconds" if d.microsecond else "seconds").replace("+00:00","Z")!=v:return None
    return d

def require_linux_loader_primitives():
    if not sys.platform.startswith("linux") or os.name!="posix":raise RuntimeError("signer_loader_requires_linux")
    for name in ("O_NOFOLLOW","O_DIRECTORY","O_CLOEXEC","O_NONBLOCK"):
        if not isinstance(getattr(os,name,None),int):raise RuntimeError("signer_loader_primitive_unavailable")
    if os.open not in os.supports_dir_fd or os.stat not in os.supports_dir_fd or os.stat not in os.supports_follow_symlinks:raise RuntimeError("signer_loader_primitive_unavailable")

def _dir_ok(st,allowed,*,ancestor):
    if not stat.S_ISDIR(st.st_mode) or st.st_uid not in allowed:return False
    writable=st.st_mode&0o022
    # Root-owned sticky temporary ancestors are tolerated, never the final parent.
    return not writable or (ancestor and st.st_uid==0 and st.st_mode&stat.S_ISVTX and st.st_mode&0o002)

def _open_parent(path:Path,allowed:set[int]):
    if not path.is_absolute() or path.name in {"",".",".."}:raise RuntimeError("signer_path_must_be_absolute")
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC|os.O_NOFOLLOW
    fd=os.open("/",flags); opened=[]
    try:
        parts=path.parent.parts[1:]
        if not _dir_ok(os.fstat(fd),allowed,ancestor=bool(parts)):raise RuntimeError("signer_ancestor_permissions_invalid")
        for i,c in enumerate(parts):
            if c in {"",".",".."}:raise RuntimeError("signer_path_invalid")
            nxt=os.open(c,flags,dir_fd=fd);opened.append((os.fstat(fd),c));os.close(fd);fd=nxt
            if not _dir_ok(os.fstat(fd),allowed,ancestor=i<len(parts)-1):raise RuntimeError("signer_parent_permissions_invalid" if i==len(parts)-1 else "signer_ancestor_permissions_invalid")
        return fd,path.name
    except Exception:os.close(fd);raise

@dataclass(frozen=True)
class LoadedPemSigner:
    key:Ed25519PrivateKey; pem_sha256:str; public_pem:bytes
    def sign(self,m:bytes)->bytes:return self.key.sign(m)

def load_ed25519_private_key(path:Path|str,*,expected_uid:int|None=None,approved_directory_uids:frozenset[int]|None=None,max_bytes:int=MAX_PEM_BYTES,mutation_hook:Callable[[str,int,int],None]|None=None)->LoadedPemSigner:
    require_linux_loader_primitives()
    if type(expected_uid) is not int or expected_uid<0:raise RuntimeError("signer_expected_uid_required")
    allowed=set(approved_directory_uids or frozenset({0,expected_uid}))
    if not allowed or any(type(x) is not int or x<0 for x in allowed) or expected_uid not in allowed:raise RuntimeError("signer_directory_owner_policy_invalid")
    parent_fd,name=_open_parent(Path(path),allowed);file_fd=-1;mutable=bytearray()
    try:
        parent_before=os.fstat(parent_fd);file_fd=os.open(name,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent_fd);before=os.fstat(file_fd)
        if mutation_hook:mutation_hook("opened",parent_fd,file_fd)
        if not stat.S_ISREG(before.st_mode):raise RuntimeError("signer_file_not_regular")
        if stat.S_IMODE(before.st_mode)!=0o400:raise RuntimeError("signer_file_permissions_invalid")
        if before.st_uid!=expected_uid:raise RuntimeError("signer_file_owner_invalid")
        if before.st_nlink!=1:raise RuntimeError("signer_file_link_count_invalid")
        if before.st_size<=0 or before.st_size>max_bytes:raise RuntimeError("signer_file_size_invalid")
        while len(mutable)<=max_bytes:
            chunk=os.read(file_fd,min(4096,max_bytes+1-len(mutable)))
            if not chunk:break
            mutable.extend(chunk)
        if len(mutable)!=before.st_size:raise RuntimeError("signer_file_changed_during_read")
        first=bytes(mutable)
        if mutation_hook:mutation_hook("read",parent_fd,file_fd)
        os.lseek(file_fd,0,os.SEEK_SET);second=bytearray()
        while len(second)<=max_bytes:
            chunk=os.read(file_fd,min(4096,max_bytes+1-len(second)))
            if not chunk:break
            second.extend(chunk)
        after=os.fstat(file_fd);parent_after=os.fstat(parent_fd);current=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
        if bytes(second)!=first or len(second)!=before.st_size or not _stable(before,after) or not _stable(after,current) or not _stable(parent_before,parent_after):raise RuntimeError("signer_file_changed_during_read")
        if not PEM_RE.fullmatch(first) or b"PLACEHOLDER" in first.upper() or b"EXAMPLE" in first.upper():raise RuntimeError("signer_pem_not_exact_pkcs8")
        digest=hashlib.sha256(first).hexdigest()
        try:key=serialization.load_pem_private_key(first,password=None)
        except (TypeError,ValueError) as e:raise RuntimeError("signer_pem_unencrypted_pkcs8_required") from e
        if not isinstance(key,Ed25519PrivateKey):raise RuntimeError("signer_key_must_be_ed25519")
        public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        return LoadedPemSigner(key,digest,public)
    except OSError as e:raise RuntimeError("signer_file_open_failed") from e
    finally:
        for i in range(len(mutable)):mutable[i]=0
        if file_fd>=0:os.close(file_fd)
        os.close(parent_fd)

def _authorized_roster(roster:Any):
    if type(roster) is not dict or len(roster)<2 or len(roster)>32:raise RuntimeError("ceremony_reviewer_roster_invalid")
    out={};digests=set()
    for rid,entry in roster.items():
        if type(rid) is not str or not ID_RE.fullmatch(rid) or type(entry) is not dict or set(entry)!=ROSTER_ENTRY_FIELDS or not ID_RE.fullmatch(entry.get("role","")) or not _hex(entry.get("public_spki_der_sha256")):raise RuntimeError("ceremony_reviewer_roster_invalid")
        try:
            pem=entry["public_key_pem"].encode("ascii");key=serialization.load_pem_public_key(pem)
            if not isinstance(key,Ed25519PublicKey):raise ValueError
            canonical_pem=key.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
            der=key.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo);digest=hashlib.sha256(der).hexdigest()
            if pem!=canonical_pem or not hmac.compare_digest(digest,entry["public_spki_der_sha256"]) or digest in digests:raise ValueError
        except Exception as e:raise RuntimeError("ceremony_reviewer_roster_invalid") from e
        digests.add(digest);out[rid]=(key,digest)
    return out

def _validate_body(body):
    if type(body) is not dict or set(body)!=RECORD_BODY_FIELDS:return False
    g,p=body.get("generation"),body.get("predecessor_generation")
    if type(g) is not int or not 1<=g<=2**31-1 or (g==1 and (p is not None or body.get("predecessor_ceremony_sha256") is not None)) or (g>1 and (p!=g-1 or not _hex(body.get("predecessor_ceremony_sha256")))):return False
    if not AUTH_RE.fullmatch(body.get("authority_id","")) or not ID_RE.fullmatch(body.get("key_id","")) or body.get("status")!="active":return False
    if not all(_hex(body.get(x)) for x in ("public_pem_sha256","public_spki_der_sha256","private_pem_sha256","release_sha256","deployment_config_sha256")):return False
    ceremony_at,activated_at=_utc(body.get("ceremony_at")),_utc(body.get("activated_at"))
    if ceremony_at is None or activated_at is None or activated_at<ceremony_at or not ID_RE.fullmatch(body.get("change_id","")):return False
    w=body.get("witness")
    return type(w) is dict and set(w)==WITNESS_FIELDS and ID_RE.fullmatch(w.get("reference","")) is not None and ID_RE.fullmatch(w.get("version","")) is not None and _hex(w.get("digest"))

def validate_ceremony_record(record:Any,authorized_reviewers:Mapping[str,Any])->tuple[dict[str,Any],str]:
    roster=_authorized_roster(authorized_reviewers)
    if type(record) is not dict or set(record)!=RECORD_FIELDS or record.get("schema_version")!=1:raise RuntimeError("ceremony_record_invalid")
    body,acks=record.get("record"),record.get("acknowledgements")
    if not _validate_body(body) or type(acks) is not list or len(acks)!=2:raise RuntimeError("ceremony_record_invalid")
    message=b"growthmap-pem-ceremony-v2\0"+canonical(body);seen=set();keys=set()
    for ack in acks:
        if type(ack) is not dict or set(ack)!=ACK_FIELDS or ack.get("reviewer_id") not in roster:raise RuntimeError("ceremony_ack_invalid")
        rid=ack["reviewer_id"];key,digest=roster[rid]
        if rid in seen or digest in keys:raise RuntimeError("ceremony_ack_reviewers_not_distinct")
        try:
            if type(ack["signature"]) is not str or not re.fullmatch(r"[a-f0-9]{128}",ack["signature"]):raise ValueError
            key.verify(bytes.fromhex(ack["signature"]),message)
        except Exception as e:raise RuntimeError("ceremony_ack_invalid") from e
        seen.add(rid);keys.add(digest)
    return dict(body),hashlib.sha256(canonical(record)).hexdigest()

def validate_descriptor(descriptor,ceremony_record,loaded,reviewed_public_pem:bytes,*,authority_id:str,authorized_reviewers):
    if type(descriptor) is not dict or set(descriptor)!=DESCRIPTOR_FIELDS or descriptor.get("schema_version")!=2:raise RuntimeError("signer_descriptor_invalid")
    body,record_digest=validate_ceremony_record(ceremony_record,authorized_reviewers)
    if not _validate_body({k:v for k,v in descriptor.items() if k not in {"schema_version","ceremony_record_sha256"}}):raise RuntimeError("signer_descriptor_invalid")
    if descriptor["authority_id"]!=authority_id or any(body.get(k)!=descriptor.get(k) for k in RECORD_BODY_FIELDS):raise RuntimeError("signer_ceremony_descriptor_mismatch")
    if not hmac.compare_digest(record_digest,descriptor["ceremony_record_sha256"]):raise RuntimeError("signer_ceremony_digest_mismatch")
    try:
        reviewed=serialization.load_pem_public_key(reviewed_public_pem)
        if not isinstance(reviewed,Ed25519PublicKey):raise ValueError
        canonical_pem=reviewed.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo);der=reviewed.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    except Exception as e:raise RuntimeError("signer_public_key_invalid") from e
    if reviewed_public_pem!=canonical_pem or loaded.public_pem!=reviewed_public_pem or not hmac.compare_digest(hashlib.sha256(reviewed_public_pem).hexdigest(),descriptor["public_pem_sha256"]) or not hmac.compare_digest(hashlib.sha256(der).hexdigest(),descriptor["public_spki_der_sha256"]) or not hmac.compare_digest(loaded.pem_sha256,descriptor["private_pem_sha256"]):raise RuntimeError("signer_key_descriptor_mismatch")
    probe=b"growthmap-pem-signer-self-test-v1"
    try:reviewed.verify(loaded.sign(probe),probe)
    except Exception as e:raise RuntimeError("signer_private_public_mismatch") from e
    return dict(descriptor)
