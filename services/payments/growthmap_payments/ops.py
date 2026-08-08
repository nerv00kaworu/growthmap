"""Defensive, local-only operational evidence for an isolated payment fixture."""
from __future__ import annotations
import ctypes, errno, hashlib, hmac, json, os, re, secrets, shutil, sqlite3, stat, tempfile, time, unicodedata
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .service import Config, MIGRATIONS, PaymentService, SCHEMA_VERSION

MARKER=".growthmap-isolated-test"; MARKER_VALUE=b"growthmap isolated local drill v1\n"
DB_NAME="payments.sqlite3"; CHECKPOINT_NAME="issuance.checkpoint"; MANIFEST_NAME="manifest.json"
ARTIFACTS={DB_NAME,CHECKPOINT_NAME,MANIFEST_NAME}; MAX_ITEMS=100; MAX_DB_BYTES=128*1024*1024; MAX_DB_PAGES=32768; MAX_ROWS=100000
BACKUP_DEADLINE_SECONDS=15.0; SQL_DEADLINE_SECONDS=5.0; SQL_PROGRESS_STEPS=1000
_PUBLICATION_HOOK=None  # test-only exact-boundary fault injection
LIVE=re.compile(r"prod|production|live|staging",re.I); SAFE=re.compile(r"[A-Za-z0-9._-]{1,120}\Z")
MANIFEST_DOMAIN=b"growthmap-local-backup-manifest-v1\0"; REPORT_DOMAIN=b"growthmap-local-reconciliation-report-v1\0"
class OpsRefusal(RuntimeError):pass

def _safe_name(name:str)->str:
 if not SAFE.fullmatch(name) or unicodedata.normalize("NFKC",name)!=name or LIVE.search(name):raise OpsRefusal("unsafe or live-looking path refused")
 return name

def _root_fd(root:Path)->tuple[Path,int]:
 root=Path(os.path.abspath(os.fspath(root))); st=os.lstat(root)
 if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):raise OpsRefusal("isolated root must be a real directory")
 fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC); fs=os.fstat(fd)
 if (st.st_dev,st.st_ino)!=(fs.st_dev,fs.st_ino):os.close(fd);raise OpsRefusal("isolated root changed")
 try:
  mfd=os.open(MARKER,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd); ms=os.fstat(mfd)
  try:data=os.read(mfd,len(MARKER_VALUE)+1)
  finally:os.close(mfd)
 except OSError as e:os.close(fd);raise OpsRefusal("isolated-test marker missing or unsafe") from e
 if not stat.S_ISREG(ms.st_mode) or ms.st_nlink!=1 or data!=MARKER_VALUE:os.close(fd);raise OpsRefusal("isolated-test marker invalid or unsafe")
 return root,fd

def _direct(root:Path,path:Path)->str:
 path=Path(os.path.abspath(os.fspath(path)))
 if path.parent!=root:raise OpsRefusal("path escapes isolated-test root or is nested")
 return _safe_name(path.name)

def read_key_fixture(isolated_root:Path,key_path:Path)->bytes:
 root,rfd=_root_fd(isolated_root)
 try:
  name=_direct(root,key_path);fd,st=_open_regular(rfd,name)
  try:return _read_stable(fd,st,4096)
  finally:os.close(fd)
 finally:os.close(rfd)

def _open_regular(rootfd:int,name:str,flags:int=os.O_RDONLY)->tuple[int,os.stat_result]:
 try:fd=os.open(name,flags|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=rootfd)
 except OSError as e:raise OpsRefusal("artifact missing or unsafe") from e
 st=os.fstat(fd)
 if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:os.close(fd);raise OpsRefusal("artifact must be a single-link regular file")
 return fd,st

def _read_stable(fd:int,st:os.stat_result,max_bytes:int)->bytes:
 if st.st_size>max_bytes:raise OpsRefusal("artifact too large")
 os.lseek(fd,0,os.SEEK_SET); chunks=[]; total=0
 while True:
  chunk=os.read(fd,min(65536,max_bytes+1-total))
  if not chunk:break
  total+=len(chunk)
  if total>max_bytes:raise OpsRefusal("artifact too large")
  chunks.append(chunk)
 after=os.fstat(fd)
 if (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise OpsRefusal("artifact changed while read")
 return b"".join(chunks)

def _assert_identity(rootfd:int,name:str,st:os.stat_result):
 now=os.stat(name,dir_fd=rootfd,follow_symlinks=False)
 if not stat.S_ISREG(now.st_mode) or now.st_nlink!=1 or (now.st_dev,now.st_ino)!=(st.st_dev,st.st_ino):raise OpsRefusal("artifact changed or aliased")

def _cleanup_sidecars(directory:Path,db_name:str=DB_NAME):
 for suffix in ("-wal","-shm","-journal"):
  p=directory/(db_name+suffix)
  try:p.unlink()
  except FileNotFoundError:pass

def _exact(directory:Path):
 names={p.name for p in directory.iterdir()}
 if names!=ARTIFACTS:raise OpsRefusal("bundle artifact set is not exact")
 for n in ARTIFACTS:
  st=os.lstat(directory/n)
  if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_nlink!=1:raise OpsRefusal("bundle artifact unsafe")

def _renameat2_noreplace(parentfd:int,source_name:str,destination_name:str):
 libc=ctypes.CDLL(None,use_errno=True);fn=getattr(libc,"renameat2",None)
 if fn is None:raise OpsRefusal("atomic no-clobber publication unsupported")
 rc=fn(parentfd,os.fsencode(source_name),parentfd,os.fsencode(destination_name),1)
 if rc:
  e=ctypes.get_errno()
  if e in (errno.EEXIST,errno.ENOTEMPTY):raise OpsRefusal("destination already exists")
  raise OSError(e,os.strerror(e))

def _dir_artifacts(dirfd:int,key:bytes):
 if set(os.listdir(dirfd))!=ARTIFACTS:raise OpsRefusal("bundle artifact set is not exact")
 opened={}
 try:
  for name,limit in ((DB_NAME,MAX_DB_BYTES),(CHECKPOINT_NAME,1024*1024),(MANIFEST_NAME,1024*1024)):
   fd,st=_open_regular(dirfd,name);data=_read_stable(fd,st,limit);opened[name]=(fd,st,data)
  manifest=_parse_manifest(opened[MANIFEST_NAME][2],key)
  if hashlib.sha256(opened[DB_NAME][2]).hexdigest()!=manifest["database_sha256"] or hashlib.sha256(opened[CHECKPOINT_NAME][2]).hexdigest()!=manifest["checkpoint_sha256"]:raise OpsRefusal("backup pair manifest mismatch")
  return opened,manifest
 except Exception:
  for fd,_,_ in opened.values():os.close(fd)
  raise

def _reverify_dir(dirfd:int,opened:dict,key:bytes):
 if set(os.listdir(dirfd))!=ARTIFACTS:raise OpsRefusal("publication artifact set changed")
 current={}
 for name,(fd,original,data) in opened.items():
  now=os.fstat(fd);_assert_identity(dirfd,name,original)
  if not stat.S_ISREG(now.st_mode) or now.st_nlink!=1 or now.st_uid!=os.getuid() or (now.st_dev,now.st_ino,now.st_size,now.st_mtime_ns)!=(original.st_dev,original.st_ino,original.st_size,original.st_mtime_ns):raise OpsRefusal("publication artifact identity changed")
  current[name]=_read_stable(fd,now,MAX_DB_BYTES if name==DB_NAME else 1024*1024)
  if not hmac.compare_digest(current[name],data):raise OpsRefusal("publication artifact content changed")
 manifest=_parse_manifest(current[MANIFEST_NAME],key)
 if hashlib.sha256(current[DB_NAME]).hexdigest()!=manifest["database_sha256"] or hashlib.sha256(current[CHECKPOINT_NAME]).hexdigest()!=manifest["checkpoint_sha256"]:raise OpsRefusal("publication manifest mismatch")
 return manifest

def _publish_stage(rootfd:int,root_st:os.stat_result,stage:Path,dest_name:str,key:bytes):
 os.chmod(stage,0o700);stagefd=os.open(stage.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=rootfd)
 opened={};published=False
 try:
  stg=os.fstat(stagefd)
  if stg.st_uid!=os.getuid():raise OpsRefusal("stage owner invalid")
  for name in ARTIFACTS:os.chmod(name,0o600,dir_fd=stagefd,follow_symlinks=False)
  opened,manifest=_dir_artifacts(stagefd,key);_reverify_dir(stagefd,opened,key)
  if _PUBLICATION_HOOK:_PUBLICATION_HOOK(stage,False)
  _reverify_dir(stagefd,opened,key)
  nowroot=os.fstat(rootfd)
  if (nowroot.st_dev,nowroot.st_ino)!=(root_st.st_dev,root_st.st_ino):raise OpsRefusal("isolated root changed before publication")
  _renameat2_noreplace(rootfd,stage.name,dest_name);published=True
  destfd=os.open(dest_name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=rootfd)
  try:
   if _PUBLICATION_HOOK:_PUBLICATION_HOOK(Path(f"/proc/self/fd/{destfd}"),True)
   post,post_manifest=_dir_artifacts(destfd,key)
   try:
    if set(post)!=set(opened):raise OpsRefusal("post-publication artifact mismatch")
    for name in ARTIFACTS:
     a=opened[name][1];b=post[name][1]
     if (a.st_dev,a.st_ino)!=(b.st_dev,b.st_ino) or not hmac.compare_digest(opened[name][2],post[name][2]):raise OpsRefusal("post-publication substitution detected")
    if post_manifest!=manifest:raise OpsRefusal("post-publication manifest changed")
   finally:
    for fd,_,_ in post.values():os.close(fd)
  except Exception:
   quarantine=".ops-quarantine-"+secrets.token_hex(8)
   try:_renameat2_noreplace(rootfd,dest_name,quarantine)
   except Exception:pass
   raise
  finally:os.close(destfd)
 finally:
  for fd,_,_ in opened.values():os.close(fd)
  os.close(stagefd)
  if not published:shutil.rmtree(stage,ignore_errors=True)

def bundle_manifest_digest(isolated_root:Path,bundle:Path,mac_key:bytes)->str:
 root,rfd=_root_fd(isolated_root)
 try:
  name=_direct(root,bundle);bfd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=rfd)
  try:
   opened,_=_dir_artifacts(bfd,mac_key)
   try:return hashlib.sha256(opened[MANIFEST_NAME][2]).hexdigest()
   finally:
    for fd,_,_ in opened.values():os.close(fd)
  finally:os.close(bfd)
 finally:os.close(rfd)

def _connect_immutable(path:Path):
 db=sqlite3.connect(f"file:{path}?mode=ro&immutable=1",uri=True,timeout=5);db.row_factory=sqlite3.Row;db.execute("PRAGMA foreign_keys=ON");db.execute("PRAGMA query_only=ON")
 deadline=time.monotonic()+SQL_DEADLINE_SECONDS
 db.set_progress_handler(lambda: 1 if time.monotonic()>deadline else 0,SQL_PROGRESS_STEPS)
 return db

def _preflight_source(fd:int):
 st=os.fstat(fd)
 if st.st_size>MAX_DB_BYTES:raise OpsRefusal("source database exceeds byte bound")
 db=sqlite3.connect(f"file:/proc/self/fd/{fd}?mode=ro",uri=True,timeout=2)
 try:
  pages=db.execute("PRAGMA page_count").fetchone()[0];page_size=db.execute("PRAGMA page_size").fetchone()[0]
  if pages>MAX_DB_PAGES or pages*page_size>MAX_DB_BYTES:raise OpsRefusal("source database exceeds page bound")
  return pages,page_size
 finally:db.close()

def _online_backup(source:sqlite3.Connection,target:sqlite3.Connection,deadline:float):
 def progress(status,remaining,total):
  if total>MAX_DB_PAGES or total*4096>MAX_DB_BYTES or time.monotonic()>deadline:raise OpsRefusal("online backup resource bound exceeded")
 source.backup(target,pages=128,progress=progress,sleep=0.01);target.commit()


def _bounded(db):
 pages=db.execute("PRAGMA page_count").fetchone()[0]; size=pages*db.execute("PRAGMA page_size").fetchone()[0]
 if pages>MAX_DB_PAGES or size>MAX_DB_BYTES:raise OpsRefusal("database exceeds local drill bounds")
 total=sum(db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in TABLES if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone())
 if total>MAX_ROWS:raise OpsRefusal("database row bound exceeded")
 return total
TABLES=("orders","payment_proofs","external_events","settlement_intents","audit_events","migration_ledger","terminal_checkpoint_state","revocation_assertions","entitlement_outbox","revocation_outbox","settlement_candidates","whop_webhook_inbox")
def _schema(db):return [{"type":r[0],"name":r[1],"table":r[2],"sql":re.sub(r"\s+"," ",r[3].strip())} for r in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE type IN('table','index','trigger') AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY type,name")]
def _closure(db):
 _bounded(db); closure={}
 for table in TABLES:
  if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():continue
  cols=[r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]; order=",".join('"'+c+'"' for c in cols)
  closure[table]=[dict(r) for r in db.execute(f'SELECT * FROM "{table}" ORDER BY {order}')]
 schema=_schema(db); raw=json.dumps({"schema":schema,"rows":closure},sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
 return sum(map(len,closure.values())),hashlib.sha256(raw).hexdigest(),hashlib.sha256(json.dumps(schema,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _validate(db_path:Path,checkpoint:bytes,mac_key:bytes):
 if len(mac_key)<32:raise OpsRefusal("checkpoint key weak")
 with _connect_immutable(db_path) as db:
  integrity=db.execute("PRAGMA integrity_check").fetchone()[0]; foreign=list(db.execute("PRAGMA foreign_key_check")); version=db.execute("PRAGMA user_version").fetchone()[0]
  ledger={r[0]:(r[1],r[2]) for r in db.execute("SELECT version,filename,checksum FROM migration_ledger")};count,root,schema=_closure(db);seq=db.execute("SELECT sequence FROM terminal_checkpoint_state WHERE singleton=1").fetchone()[0]
 if integrity!="ok" or foreign:raise RuntimeError("database integrity/foreign-key failure")
 if version!=SCHEMA_VERSION or ledger!={v:MIGRATIONS[v] for v in range(1,SCHEMA_VERSION+1)}:raise RuntimeError("migration/schema mismatch")
 try:doc=json.loads(checkpoint);mac=doc.pop("mac")
 except Exception as e:raise RuntimeError("checkpoint invalid") from e
 valid=hmac.new(mac_key,b"growthmap-issuance-checkpoint-v2\0"+json.dumps(doc,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest();expected={"count":count,"root":root,"schema":schema,"sequence":seq,"version":2}
 if set(doc)!=set(expected) or not hmac.compare_digest(str(mac),valid):raise RuntimeError("checkpoint authentication failed")
 if doc!=expected:raise RuntimeError("checkpoint/database mismatch")
 return {"checkpoint":"authenticated","foreign_keys":"ok","integrity":"ok","rows_in_closure":count,"schema_version":version,"migration_count":len(ledger)}
def validate_pair(db_path:Path,checkpoint_path:Path,mac_key:bytes):
 """Validate a possibly active local fixture through an online snapshot."""
 with tempfile.TemporaryDirectory(prefix="growthmap-validate-") as td:
  copy=Path(td)/DB_NAME;source=sqlite3.connect(db_path,timeout=5);target=sqlite3.connect(copy)
  try:source.backup(target);target.commit();target.execute("PRAGMA journal_mode=DELETE")
  finally:target.close();source.close()
  return _validate(copy,checkpoint_path.read_bytes(),mac_key)

def _manifest(db:bytes,cp:bytes,key:bytes):
 core={"format":1,"database":DB_NAME,"checkpoint":CHECKPOINT_NAME,"database_sha256":hashlib.sha256(db).hexdigest(),"checkpoint_sha256":hashlib.sha256(cp).hexdigest(),"schema_version":SCHEMA_VERSION}
 core["mac"]=hmac.new(key,MANIFEST_DOMAIN+json.dumps(core,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest();return core
def _parse_manifest(raw:bytes,key:bytes):
 try:m=json.loads(raw);mac=m.pop("mac")
 except Exception as e:raise OpsRefusal("manifest invalid") from e
 exact={"format","database","checkpoint","database_sha256","checkpoint_sha256","schema_version"}
 if set(m)!=exact or m["format"]!=1 or m["database"]!=DB_NAME or m["checkpoint"]!=CHECKPOINT_NAME or m["schema_version"]!=SCHEMA_VERSION:raise OpsRefusal("manifest names/schema invalid")
 valid=hmac.new(key,MANIFEST_DOMAIN+json.dumps(m,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest()
 if not hmac.compare_digest(str(mac),valid):raise OpsRefusal("manifest authentication failed")
 return m

def backup_pair(isolated_root:Path,db_path:Path,checkpoint_path:Path,destination:Path,mac_key:bytes,retries:int=3):
 root,rfd=_root_fd(isolated_root);root_st=os.fstat(rfd)
 try:
  dbn=_direct(root,db_path);cpn=_direct(root,checkpoint_path);destn=_direct(root,destination)
  if dbn==cpn or destn in {dbn,cpn,MARKER}:raise OpsRefusal("source/destination alias refused")
  for attempt in range(1,retries+1):
   dfd,ds=_open_regular(rfd,dbn);cfd,cs=_open_regular(rfd,cpn)
   _preflight_source(dfd);stage=Path(tempfile.mkdtemp(prefix=".ops-stage-",dir=root));os.chmod(stage,0o700)
   try:
    before=_read_stable(cfd,cs,1024*1024);source=sqlite3.connect(f"file:/proc/self/fd/{dfd}?mode=ro",uri=True,timeout=30);target=sqlite3.connect(stage/DB_NAME)
    try:_online_backup(source,target,time.monotonic()+BACKUP_DEADLINE_SECONDS);target.execute("PRAGMA wal_checkpoint(TRUNCATE)");target.execute("PRAGMA journal_mode=DELETE")
    finally:target.close();source.close()
    _cleanup_sidecars(stage);after=_read_stable(cfd,cs,1024*1024);_assert_identity(rfd,dbn,ds);_assert_identity(rfd,cpn,cs)
    if before!=after:raise RuntimeError("checkpoint changed during online backup")
    (stage/CHECKPOINT_NAME).write_bytes(before)
    result=_validate(stage/DB_NAME,before,mac_key);dbbytes=(stage/DB_NAME).read_bytes();manifest=_manifest(dbbytes,before,mac_key)
    (stage/MANIFEST_NAME).write_text(json.dumps(manifest,sort_keys=True,separators=(",",":"))+"\n");_cleanup_sidecars(stage);_exact(stage);_publish_stage(rfd,root_st,stage,destn,mac_key)
    return {"attempts":attempt,"destination":str(root/destn),**result}
   except Exception:
    shutil.rmtree(stage,ignore_errors=True)
    if attempt==retries:raise
   finally:os.close(dfd);os.close(cfd)
 finally:os.close(rfd)

def _bundle_fds(root:Path,rfd:int,bundle_name:str,key:bytes):
 bfd=os.open(bundle_name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=rfd)
 try:
  names=set(os.listdir(bfd))
  if names!=ARTIFACTS:raise OpsRefusal("bundle artifact set is not exact")
  opened={}
  for n,maxb in ((DB_NAME,MAX_DB_BYTES),(CHECKPOINT_NAME,1024*1024),(MANIFEST_NAME,1024*1024)):
   fd,st=_open_regular(bfd,n);opened[n]=(fd,st,_read_stable(fd,st,maxb))
  m=_parse_manifest(opened[MANIFEST_NAME][2],key)
  if hashlib.sha256(opened[DB_NAME][2]).hexdigest()!=m["database_sha256"] or hashlib.sha256(opened[CHECKPOINT_NAME][2]).hexdigest()!=m["checkpoint_sha256"]:raise OpsRefusal("backup pair manifest mismatch")
  return bfd,opened,m
 except Exception:os.close(bfd);raise

def restore_pair(isolated_root:Path,bundle:Path,destination:Path,config:Config,expected_bundle_digest:str):
 if not re.fullmatch(r"[a-f0-9]{64}",expected_bundle_digest or ""):raise OpsRefusal("expected bundle digest required")
 root,rfd=_root_fd(isolated_root);root_st=os.fstat(rfd)
 try:
  bn=_direct(root,bundle);dn=_direct(root,destination)
  if bn==dn or dn in {MARKER,_direct(root,config.db_path),_direct(root,config.settlement_checkpoint_path)}:raise OpsRefusal("source/destination alias refused")
  bfd,opened,m=_bundle_fds(root,rfd,bn,config.settlement_mac_key)
  if not hmac.compare_digest(hashlib.sha256(opened[MANIFEST_NAME][2]).hexdigest(),expected_bundle_digest):
   for fd,_,_ in opened.values():os.close(fd)
   os.close(bfd);raise OpsRefusal("expected bundle digest mismatch")
  stage=Path(tempfile.mkdtemp(prefix=".ops-stage-",dir=root))
  try:
   for n in (DB_NAME,CHECKPOINT_NAME,MANIFEST_NAME):
    fd,st,data=opened[n];(stage/n).write_bytes(data);_assert_identity(bfd,n,st)
   result=_validate(stage/DB_NAME,opened[CHECKPOINT_NAME][2],config.settlement_mac_key);_exact(stage)
   # Constructor validation happens only on a disposable clone because it enables WAL.
   clone=Path(tempfile.mkdtemp(prefix=".ops-startup-clone-",dir=root))
   try:
    shutil.copy2(stage/DB_NAME,clone/DB_NAME);shutil.copy2(stage/CHECKPOINT_NAME,clone/CHECKPOINT_NAME)
    PaymentService(replace(config,db_path=clone/DB_NAME,settlement_checkpoint_path=clone/CHECKPOINT_NAME));_cleanup_sidecars(clone)
   finally:shutil.rmtree(clone,ignore_errors=True)
   _cleanup_sidecars(stage);_exact(stage);_publish_stage(rfd,root_st,stage,dn,config.settlement_mac_key);return {"destination":str(root/dn),"service_startup":"ok","published_copy_mutated":False,**result}
  except Exception:shutil.rmtree(stage,ignore_errors=True);raise
  finally:
   for fd,_,_ in opened.values():os.close(fd)
   os.close(bfd)
 finally:os.close(rfd)

def _snapshot(root:Path,rfd:int,dbn:str,cpn:str,key:bytes):
 stage=Path(tempfile.mkdtemp(prefix=".ops-readonly-",dir=root));dfd,ds=_open_regular(rfd,dbn);cfd,cs=_open_regular(rfd,cpn)
 try:
  _preflight_source(dfd);cp=_read_stable(cfd,cs,1024*1024);source=sqlite3.connect(f"file:/proc/self/fd/{dfd}?mode=ro",uri=True,timeout=5);target=sqlite3.connect(stage/DB_NAME)
  try:_online_backup(source,target,time.monotonic()+BACKUP_DEADLINE_SECONDS);target.execute("PRAGMA journal_mode=DELETE")
  finally:target.close();source.close()
  _cleanup_sidecars(stage);cp2=_read_stable(cfd,cs,1024*1024);_assert_identity(rfd,dbn,ds);_assert_identity(rfd,cpn,cs)
  if cp!=cp2:raise RuntimeError("checkpoint changed during snapshot")
  _validate(stage/DB_NAME,cp,key);return stage
 except Exception:shutil.rmtree(stage,ignore_errors=True);raise
 finally:os.close(dfd);os.close(cfd)
def _age(v,now):
 try:return max(0,int((now-datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(timezone.utc)).total_seconds())) if v else None
 except Exception:return None
def monitoring_snapshot(isolated_root:Path,db_path:Path,checkpoint_path:Path,mac_key:bytes,now=None):
 base={"schema":"growthmap-local-ops-v1","severity":"critical","exit_code":2,"metrics":{"checkpoint":{"checkpoint":"error","integrity":"error","foreign_keys":"error","migration":"error"}}}
 try:
  root,rfd=_root_fd(isolated_root)
  try:dbn=_direct(root,db_path);cpn=_direct(root,checkpoint_path);stage=_snapshot(root,rfd,dbn,cpn,mac_key)
  finally:os.close(rfd)
  try:
   now=now or datetime.now(timezone.utc);m={"inbox":{},"entitlement_outbox":{},"revocation_outbox":{},"orders":{},"checkpoint":{"checkpoint":"authenticated","integrity":"ok","foreign_keys":"ok","migration":"ok","schema_version":SCHEMA_VERSION}}
   with _connect_immutable(stage/DB_NAME) as db:
    m["inbox"]={r[0]:r[1] for r in db.execute("SELECT state,count(*) FROM whop_webhook_inbox GROUP BY state")}
    for table in ("entitlement_outbox","revocation_outbox"):
     states={s:0 for s in ("pending","leased","delivered","quarantined")};states.update({r[0]:r[1] for r in db.execute(f"SELECT state,count(*) FROM {table} GROUP BY state")})
     rows=db.execute(f"SELECT max(attempt_count),min(CASE WHEN state!='delivered' THEN created_at END) FROM {table}").fetchone();m[table]={"states":states,"max_attempts":rows[0] or 0,"max_age_seconds":_age(rows[1],now) or 0}
    m["orders"]={"manual_review":db.execute("SELECT count(*) FROM orders WHERE state='manual_review'").fetchone()[0],"ambiguous_intents":db.execute("SELECT count(*) FROM settlement_intents WHERE state='ambiguous'").fetchone()[0]}
   warning=m["inbox"].get("quarantined",0)>0 or any(m[t]["states"]["quarantined"] or m[t]["max_attempts"]>=5 for t in ("entitlement_outbox","revocation_outbox")) or m["orders"]["manual_review"] or m["orders"]["ambiguous_intents"] or m["entitlement_outbox"]["max_age_seconds"]>=900 or m["revocation_outbox"]["max_age_seconds"]>=300
   sev="warning" if warning else "ok";return {"schema":"growthmap-local-ops-v1","severity":sev,"exit_code":1 if warning else 0,"metrics":m}
  finally:shutil.rmtree(stage,ignore_errors=True)
 except Exception:return base

def reconciliation_report(isolated_root:Path,db_path:Path,checkpoint_path:Path,mac_key:bytes,limit=MAX_ITEMS):
 if not 1<=limit<=MAX_ITEMS:raise ValueError("limit out of bounds")
 root,rfd=_root_fd(isolated_root)
 try:stage=_snapshot(root,rfd,_direct(root,db_path),_direct(root,checkpoint_path),mac_key)
 finally:os.close(rfd)
 key=secrets.token_bytes(32)
 def hid(v):return "h:"+hmac.new(key,REPORT_DOMAIN+v.encode(),hashlib.sha256).hexdigest()[:32]
 try:
  items=[]
  with _connect_immutable(stage/DB_NAME) as db:
   queries=[("SELECT event_id,order_id,state,attempts FROM whop_webhook_inbox WHERE state!='applied' ORDER BY received_at LIMIT ?",lambda r:{"class":"webhook_quarantine" if r["state"]=="quarantined" else "webhook_pending","entity":hid(r["event_id"]),"order":hid(r["order_id"]),"attempts":r["attempts"],"action":"verify authenticated provider event and local order binding; do not replay automatically"}),("SELECT order_id,state,attempt_count,reconciliation_phase FROM entitlement_outbox WHERE state IN('pending','leased','quarantined') ORDER BY created_at LIMIT ?",lambda r:{"class":"entitlement_manual_readback" if r["reconciliation_phase"]!="none" else "entitlement_stuck","entity":hid(r["order_id"]),"state":r["state"],"attempts":r["attempt_count"],"action":"perform Authority identity-pinned readback before any operator replay"}),("SELECT event_id,state,attempt_count FROM revocation_outbox WHERE state IN('pending','leased','quarantined') ORDER BY created_at LIMIT ?",lambda r:{"class":"revocation_stuck","entity":hid(r["event_id"]),"state":r["state"],"attempts":r["attempt_count"],"action":"confirm signed Authority revocation readback; do not replay automatically"}),("SELECT id,state FROM orders WHERE state='manual_review' ORDER BY created_at LIMIT ?",lambda r:{"class":"payment_manual_review","entity":hid(r["id"]),"action":"obtain final authenticated payment evidence and use reviewed reconciliation procedure"})]
   for q,project in queries:
    left=limit-len(items)
    if left:items.extend(project(r) for r in db.execute(q,(left,)))
   total=sum(db.execute(q.replace("SELECT event_id,order_id,state,attempts","SELECT count(*)").replace("SELECT order_id,state,attempt_count,reconciliation_phase","SELECT count(*)").replace("SELECT event_id,state,attempt_count","SELECT count(*)").replace("SELECT id,state","SELECT count(*)").rsplit(" ORDER BY",1)[0]).fetchone()[0] for q,_ in queries)
  return {"schema":"growthmap-local-reconciliation-v1","read_only":True,"truncated":total>len(items),"count":len(items),"total":total,"items":items}
 finally:shutil.rmtree(stage,ignore_errors=True)
