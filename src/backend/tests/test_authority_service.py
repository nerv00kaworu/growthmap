import hashlib,json,os,sqlite3,stat,threading,time
from pathlib import Path
import pytest
from licensing.authority import LicenseAuthority,activation_challenge
from licensing.authority_service import LocalV1PersistentAnchor,ProductionSQLiteBroker,TrustedDatabaseGuard,_loads,_read_fixed,build_production_authority,cli_main,load_production_config,main
from licensing.signer_ceremony import OfflineFixtureMonotonicAnchor

def root_config(tmp_path):
 p=tmp_path/"authority-production.json";cfg={"schema_version":1,"authority_id":"growthmap-authority-primary","expected_uid":os.getuid(),"approved_directory_uids":[0,os.getuid()],"private_key_path":str(tmp_path/"key"),"database_path":str(tmp_path/"db"),"reviewed_public_key_path":str(tmp_path/"public"),"reviewed_public_key_sha256":"1"*64,"descriptor_path":str(tmp_path/"descriptor"),"ceremony_record_path":str(tmp_path/"record"),"authorized_reviewers":{},"release_sha256":"2"*64,"deployment_config_sha256":"3"*64,"anchor":{"provider":"local-v1","path":str(tmp_path/"anchor"),"expected_uid":os.getuid()},"listen":{"host":"127.0.0.1","port":8443}};p.write_text(json.dumps(cfg));p.chmod(0o400);return p,cfg

def test_fixed_config_closed_absolute(monkeypatch,tmp_path):
 p,cfg=root_config(tmp_path);monkeypatch.setattr("licensing.authority_service._read_fixed",lambda path,**kw:p.read_bytes());assert load_production_config(p,expected_uid=os.getuid())==cfg
 cfg["extra"]=1;p.chmod(0o600);p.write_text(json.dumps(cfg));p.chmod(0o400)
 with pytest.raises(RuntimeError):load_production_config(p,expected_uid=os.getuid())

def test_duplicate_json_rejected_recursively():
 for raw in (b'{"a":1,"a":2}',b'{"a":{"b":1,"b":2}}',b'{"record":{"witness":{"digest":"a","digest":"b"}}}',b'{"authorized_reviewers":{"r":{"role":"a","role":"b"}}}',b'{"acknowledgements":[{"reviewer_id":"a","reviewer_id":"b"}]}'):
  with pytest.raises(RuntimeError):_loads(raw,"bad")

def test_production_rejects_fixture_before_db(monkeypatch):
 cfg={"anchor":{},"expected_uid":os.getuid(),"approved_directory_uids":[0,os.getuid()],"reviewed_public_key_path":"/p","reviewed_public_key_sha256":hashlib.sha256(b"p").hexdigest(),"descriptor_path":"/d","ceremony_record_path":"/r","release_sha256":"1"*64,"deployment_config_sha256":"2"*64}
 monkeypatch.setattr("licensing.authority_service.load_production_config",lambda _,**kw:cfg);monkeypatch.setattr("licensing.authority_service._read_fixed",lambda p,**kw:b"p" if str(p)=="/p" else json.dumps({"release_sha256":cfg["release_sha256"],"deployment_config_sha256":cfg["deployment_config_sha256"]}).encode())
 with pytest.raises(RuntimeError,match="unsafe"):build_production_authority("/config",expected_uid=os.getuid(),anchor_factory=lambda _:OfflineFixtureMonotonicAnchor())

def test_production_requires_valid_broker_before_signer_or_anchor(monkeypatch):
 cfg={"anchor":{},"expected_uid":os.getuid(),"approved_directory_uids":[0,os.getuid()],"database_path":"/private/authority.sqlite3","reviewed_public_key_path":"/p","reviewed_public_key_sha256":hashlib.sha256(b"p").hexdigest(),"descriptor_path":"/d","ceremony_record_path":"/r","release_sha256":"1"*64,"deployment_config_sha256":"2"*64}
 monkeypatch.setattr("licensing.authority_service.load_production_config",lambda _,**kw:cfg);monkeypatch.setattr("licensing.authority_service._read_fixed",lambda p,**kw:b"p" if str(p)=="/p" else json.dumps({"release_sha256":cfg["release_sha256"],"deployment_config_sha256":cfg["deployment_config_sha256"]}).encode())
 class Anchor:
  production_safe=True;fixture=False;process_local=False
  def compare_and_advance(self,*a):raise AssertionError("anchor advanced")
  def read(self):raise AssertionError("anchor read")
 class FailBroker:
  def __init__(self,*a):raise RuntimeError("broker custody")
 with pytest.raises(RuntimeError,match="broker custody"):build_production_authority("/config",expected_uid=os.getuid(),anchor_factory=lambda _:Anchor(),broker_factory=FailBroker)

def test_main_rejects_every_alternate_factory_before_parse_build_or_server(monkeypatch):
 import functools
 from licensing.authority_api import create_authority_app
 events=[]
 monkeypatch.setattr("licensing.authority_composition.run",lambda *a,**k:events.append("run"))
 monkeypatch.setattr("licensing.authority_service.build_production_authority",lambda *a:events.append("build"))
 factories=(lambda *a:object(),functools.partial(create_authority_app,production=True),
  create_authority_app,object(),False,"create_authority_app")
 for factory in factories:
  with pytest.raises(RuntimeError,match="alternate_app_factory_forbidden"):
   main(["--fixed-config","/fixed","--route-policy","all"],app_factory=factory,
    server_runner=lambda *a:events.append("server"))
 assert events==[]

def test_programmatic_main_and_cli_delegate_only_closed_composition(monkeypatch):
 events=[]
 monkeypatch.setattr("licensing.authority_composition.run",lambda argv=None,server_runner=None:events.append(("run",argv,server_runner)) or 7)
 runner=object()
 assert main(["--fixed-config","/fixed"],server_runner=runner)==7
 monkeypatch.setattr("licensing.authority_composition.cli_main",lambda:events.append(("cli",)))
 cli_main()
 assert events==[("run",["--fixed-config","/fixed"],runner),("cli",)]

def predb(tmp_path):
 p=tmp_path/"authority.db";p.touch(0o600);p.chmod(0o600);return p

def test_fixed_loader_walk_and_swap_detection(tmp_path):
 p=tmp_path/"config";p.write_text("fixed");p.chmod(0o400)
 assert _read_fixed(p,expected_uid=os.getuid(),approved_directory_uids={0,os.getuid()})==b"fixed"
 replacement=tmp_path/"replacement";replacement.write_text("fixed");replacement.chmod(0o400)
 def swap(parent,name,fd):os.replace(replacement,p)
 with pytest.raises(RuntimeError,match="changed"):_read_fixed(p,expected_uid=os.getuid(),approved_directory_uids={0,os.getuid()},mutation_hook=swap)

@pytest.mark.parametrize("boundary",["parent_fstat","db_open","db_fstat"])
def test_database_guard_total_cleanup_on_primitive_failure(boundary,tmp_path,monkeypatch):
 p=predb(tmp_path);before=len(os.listdir("/proc/self/fd"));real_fstat=os.fstat;real_open=os.open;calls={"fstat":0}
 if boundary=="parent_fstat":
  def bad_fstat(fd):calls["fstat"]+=1;raise OSError("injected") if calls["fstat"]==1 else None
  monkeypatch.setattr(os,"fstat",bad_fstat)
 elif boundary=="db_open":
  def bad_open(path,*a,**k):
   if path==p.name:raise OSError("injected")
   return real_open(path,*a,**k)
  monkeypatch.setattr(os,"open",bad_open)
 else:
  def bad_fstat(fd):
   try:target=os.readlink(f"/proc/self/fd/{fd}")
   except OSError:target=""
   if target==str(p):raise OSError("injected")
   return real_fstat(fd)
  monkeypatch.setattr(os,"fstat",bad_fstat)
 guard=TrustedDatabaseGuard(p,os.getuid(),frozenset({0,os.getuid()}))
 with pytest.raises(Exception):guard.__enter__()
 assert guard.parent_fd==guard.db_fd==-1 and len(os.listdir("/proc/self/fd"))==before

def test_database_guard_closes_fds_after_repeated_validation_failure(tmp_path):
 p=predb(tmp_path);side=tmp_path/"authority.db-wal";side.touch(0o644);side.chmod(0o644);before=len(os.listdir("/proc/self/fd"))
 for _ in range(30):
  with pytest.raises(RuntimeError):
   with TrustedDatabaseGuard(p,os.getuid(),frozenset({0,os.getuid()})):pass
 assert len(os.listdir("/proc/self/fd"))==before

def test_database_guard_valid_bootstrap_restart_and_sidecars(tmp_path):
 p=predb(tmp_path)
 for _ in range(2):
  with TrustedDatabaseGuard(p,os.getuid(),frozenset({0,os.getuid()})) as guard:
   guard.validate("before");db=sqlite3.connect(p);db.execute("pragma journal_mode=WAL");db.execute("create table if not exists x(a)");db.commit();db.close();guard.validate("after")

@pytest.mark.parametrize("case",["symlink","hardlink","mode","fifo","directory","sidecar_symlink","sidecar_mode"])
def test_database_guard_rejects_final_and_sidecars(case,tmp_path):
 p=predb(tmp_path)
 if case=="symlink":p.unlink();p.symlink_to(tmp_path/"missing")
 elif case=="hardlink":os.link(p,tmp_path/"h")
 elif case=="mode":p.chmod(0o644)
 elif case=="fifo":p.unlink();os.mkfifo(p,0o600)
 elif case=="directory":p.unlink();p.mkdir()
 elif case=="sidecar_symlink":(tmp_path/"authority.db-wal").symlink_to(p)
 else:(tmp_path/"authority.db-wal").touch(0o644);(tmp_path/"authority.db-wal").chmod(0o644)
 with pytest.raises(RuntimeError):
  with TrustedDatabaseGuard(p,os.getuid(),frozenset({0,os.getuid()})):pass
 if case=="hardlink":os.unlink(tmp_path/"h")

def test_database_guard_rejects_writable_parent(tmp_path):
 p=predb(tmp_path);tmp_path.chmod(0o777)
 with pytest.raises(RuntimeError):
  with TrustedDatabaseGuard(p,os.getuid(),frozenset({0,os.getuid()})):pass

def test_database_guard_path_swap_detected(tmp_path):
 p=predb(tmp_path);other=tmp_path/"other";other.touch(0o600);other.chmod(0o600)
 with TrustedDatabaseGuard(p,os.getuid(),frozenset({0,os.getuid()})) as guard:
  os.replace(other,p)
  with pytest.raises(RuntimeError,match="changed"):guard.validate("after")

def broker_files(tmp_path):
 root=tmp_path/"custody";root.mkdir(0o700);root.chmod(0o700);db=root/"authority.sqlite3";db.touch(0o600);db.chmod(0o600);lock=root/ProductionSQLiteBroker.LOCK_NAME;lock.touch(0o600);lock.chmod(0o600);return root,db,lock

def test_production_broker_commit_rollback_and_no_direct_reconnect(tmp_path,monkeypatch):
 root,path,_=broker_files(tmp_path);broker=ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()});real=sqlite3.connect;calls=[]
 # Broker has already captured the module function; patching Authority's sqlite symbol cannot
 # create a fallback because Authority retains only the broker capability.
 monkeypatch.setattr("licensing.authority.sqlite3.connect",lambda *a,**k:(_ for _ in ()).throw(AssertionError("direct connect")))
 with broker.connect() as db:db.execute("CREATE TABLE x(v)");db.execute("INSERT INTO x VALUES(1)")
 with pytest.raises(ValueError):
  with broker.connect() as db:db.execute("BEGIN IMMEDIATE");db.execute("INSERT INTO x VALUES(2)");raise ValueError("rollback")
 with broker.connect() as db:assert db.execute("SELECT group_concat(v) FROM x").fetchone()[0]=="1"
 broker.close()

def test_production_broker_rejects_extra_stale_and_identity_swap(tmp_path):
 root,path,lock=broker_files(tmp_path);extra=root/"evil";extra.touch(0o600)
 with pytest.raises(RuntimeError,match="unapproved"):ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()})
 extra.unlink();journal=root/(path.name+"-journal");journal.touch(0o600)
 with pytest.raises(RuntimeError,match="unapproved"):ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()})
 journal.unlink();broker=ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()});replacement=root/"replacement";replacement.touch(0o600);replacement.chmod(0o600);os.replace(replacement,path)
 with pytest.raises(RuntimeError,match="identity_changed"):
  with broker.connect():pass
 broker.close()

def test_production_broker_rejects_lock_and_directory_entry_changes(tmp_path):
 root,path,lock=broker_files(tmp_path);broker=ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()});replacement=root/"replacement";replacement.touch(0o600);replacement.chmod(0o600);os.replace(replacement,lock)
 with pytest.raises(RuntimeError,match="identity_changed"):
  with broker.connect():pass
 broker.close()

@pytest.mark.parametrize("name",[
 "%2e%2e%2ftarget.sqlite","%2F.sqlite","authority.sqlite3?mode=ro","authority.sqlite3#fragment",
 "%3fauthority.sqlite3","authority%25.sqlite3","authority\n.sqlite3","資料庫.sqlite3",".","..",
 ProductionSQLiteBroker.LOCK_NAME,"authority.sqlite3-journal",
])
def test_production_broker_fixed_basename_rejects_uri_and_lock_collisions_before_connect(tmp_path,monkeypatch,name):
 root=tmp_path/"custody";root.mkdir(0o700);root.chmod(0o700);sentinel=tmp_path/"target.sqlite";sentinel.write_bytes(b"sentinel");calls=[]
 monkeypatch.setattr("licensing.authority_service._SQLITE_CONNECT",lambda *a,**k:calls.append(a))
 with pytest.raises(RuntimeError,match="basename_invalid"):ProductionSQLiteBroker(root/name,os.getuid(),{0,os.getuid()})
 assert calls==[] and sentinel.read_bytes()==b"sentinel"

def test_production_broker_exposes_no_general_script_and_forbidden_followup_cannot_commit(tmp_path):
 _,path,_=broker_files(tmp_path);broker=ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()})
 with broker.connect() as db:
  db.execute("CREATE TABLE partial(v)")
  assert not hasattr(db,"executescript")
  db.execute("BEGIN IMMEDIATE");db.execute("INSERT INTO partial VALUES(1)")
  with pytest.raises(sqlite3.DatabaseError):db.execute("PRAGMA synchronous=OFF")
  db.rollback()
 with broker.connect() as db:assert db.execute("SELECT count(*) FROM partial").fetchone()[0]==0
 broker.close()

def test_production_broker_cursor_facade_temp_memory_and_no_raw_connection(tmp_path):
 _,path,_=broker_files(tmp_path);broker=ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()})
 with broker.connect() as db:
  cursor=db.execute("SELECT 1 UNION ALL SELECT 2")
  assert cursor.fetchone()[0]==1 and [r[0] for r in cursor]==[2]
  assert not hasattr(cursor,"connection") and not hasattr(cursor,"backup")
  assert db.execute("PRAGMA temp_store").fetchone()[0]==2
 broker.close()

@pytest.mark.parametrize("stage",["open","sql","postflight"])
def test_production_broker_rebinds_configured_directory_entry(stage,tmp_path):
 root,path,_=broker_files(tmp_path);broker=ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()});renamed=tmp_path/"renamed";replacement=tmp_path/"custody-new"
 if stage=="open":
  root.rename(renamed);replacement.mkdir(0o700);replacement.chmod(0o700);replacement.rename(root)
  with pytest.raises(RuntimeError,match="identity_changed"):
   with broker.connect():pass
 else:
  with pytest.raises(RuntimeError,match="identity_changed|target_invalid"):
   with broker.connect() as db:
    if stage=="sql":
     root.rename(renamed);replacement.mkdir(0o700);replacement.chmod(0o700);replacement.rename(root);db.execute("SELECT 1")
    else:
     db.execute("SELECT 1");root.rename(renamed);replacement.mkdir(0o700);replacement.chmod(0o700);replacement.rename(root)
 try:broker.close()
 except RuntimeError:pass

def test_production_broker_serializes_full_connection_lifetime(tmp_path):
 _,path,_=broker_files(tmp_path);broker=ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()});writer_ready=threading.Event();release=threading.Event();reader_done=threading.Event();result=[]
 def writer():
  with broker.connect() as db:db.execute("CREATE TABLE x(v)");db.execute("BEGIN IMMEDIATE");db.execute("INSERT INTO x VALUES(1)");writer_ready.set();release.wait(5)
 def reader():
  writer_ready.wait(5)
  with broker.connect() as db:result.append(db.execute("SELECT count(*) FROM x").fetchone()[0])
  reader_done.set()
 wt=threading.Thread(target=writer);rt=threading.Thread(target=reader);wt.start();rt.start();assert writer_ready.wait(5);time.sleep(.05);assert not reader_done.is_set();release.set();wt.join(5);rt.join(5);assert result==[1] and not (path.parent/(path.name+"-journal")).exists();broker.close()

def test_production_broker_same_thread_nested_connection_rejected(tmp_path):
 _,path,_=broker_files(tmp_path);broker=ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()})
 with broker.connect() as db:
  outer=broker._active_connection;db.execute("BEGIN IMMEDIATE");db.execute("CREATE TABLE x(v)")
  for _ in range(3):
   with pytest.raises(RuntimeError,match="nested_connection_prohibited"):
    with broker.connect():pass
   assert broker._active_connection is outer
  with pytest.raises(RuntimeError,match="connection_active"):broker.close()
  db.execute("INSERT INTO x VALUES(7)")
 with broker.connect() as db:assert db.execute("SELECT v FROM x").fetchone()[0]==7
 broker.close()

def _broker_invariants(db):
 return {name:db.execute(f"PRAGMA {name}").fetchone()[0] for name in ("journal_mode","synchronous","temp_store","foreign_keys","trusted_schema","locking_mode","query_only","secure_delete","busy_timeout")}

def test_production_broker_authorizer_default_denies_pragma_writes_and_preserves_state(tmp_path):
 root,path,_=broker_files(tmp_path);outside=tmp_path/"outside.sqlite";outside.write_bytes(b"sentinel")
 broker=ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()})
 controls=[
  "PRAGMA journal_mode=WAL","PRAGMA temp_store=FILE","PRAGMA foreign_keys=OFF","PRAGMA query_only=ON",
  "PRAGMA trusted_schema=ON","PRAGMA writable_schema=ON","PRAGMA synchronous=OFF","PRAGMA secure_delete=OFF",
  "PRAGMA locking_mode=EXCLUSIVE","PRAGMA mmap_size=268435456","PRAGMA busy_timeout=9","PRAGMA cache_size=-9",
  "PRAGMA page_size=8192","PRAGMA auto_vacuum=FULL","PRAGMA wal_checkpoint(TRUNCATE)",
  "PRAGMA legacy_file_format=ON","PRAGMA load_extension=ON","PRAGMA future_control=ON",
  "PRAGMA main.\"sYnChRoNoUs\"(OFF)"," /* form */ PrAgMa \"secure_delete\" = OFF",
 ]
 with broker.connect() as db:
  baseline=_broker_invariants(db)
  assert baseline=={"journal_mode":"delete","synchronous":2,"temp_store":2,"foreign_keys":1,"trusted_schema":0,"locking_mode":"normal","query_only":0,"secure_delete":1,"busy_timeout":30000}
  for sql in controls:
   with pytest.raises(sqlite3.DatabaseError):db.execute(sql)
   assert _broker_invariants(db)==baseline and db.execute("SELECT 1").fetchone()[0]==1
  for sql in (f"ATTACH DATABASE '{outside}' AS escaped",f"/*x*/ aTtAcH DATABASE '{outside}' AS 'escaped'","ATTACH DATABASE ':memory:' AS escaped","DETACH DATABASE main","SELECT load_extension('x')"):
   with pytest.raises(sqlite3.DatabaseError):db.execute(sql)
  assert [r[1] for r in db.execute("PRAGMA database_list")]==["main"]
 with broker.connect() as db:assert _broker_invariants(db)==baseline and db.execute("SELECT 2").fetchone()[0]==2
 assert outside.read_bytes()==b"sentinel";broker.close()

def test_production_broker_vacuum_and_vacuum_into_denied_without_files(tmp_path,monkeypatch):
 _,path,_=broker_files(tmp_path);broker=ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()});monkeypatch.chdir(tmp_path)
 targets=[tmp_path/"absolute.sqlite",tmp_path/"relative.sqlite",tmp_path/"uri.sqlite"]
 statements=["VACUUM",f"VACUUM INTO '{targets[0]}'"," -- lead\n VaCuUm /*x*/ INTO 'relative.sqlite'",f"VACUUM INTO 'file:{targets[2]}?mode=rwc'"]
 with broker.connect() as db:
  baseline=_broker_invariants(db)
  for sql in statements:
   with pytest.raises(sqlite3.DatabaseError):db.execute(sql)
   assert _broker_invariants(db)==baseline
 assert not any(target.exists() for target in targets);broker.close()

def test_sqlite_pragma_authorizer_semantic_forms_are_runtime_grounded():
 db=sqlite3.connect(":memory:");seen=[]
 def authorizer(action,arg1,arg2,database,trigger):
  if action==sqlite3.SQLITE_PRAGMA:seen.append((arg1,arg2,database))
  return sqlite3.SQLITE_OK
 db.set_authorizer(authorizer)
 for sql in ("PRAGMA main.\"sYnChRoNoUs\"(OFF)","PRAGMA 'secure_delete'=ON","PRAGMA busy_timeout(7)","PRAGMA foreign_keys"):
  db.execute(sql).fetchall()
 assert seen==[("sYnChRoNoUs","OFF","main"),("secure_delete","ON",None),("busy_timeout","7",None),("foreign_keys",None,None)]
 db.close()

def test_production_broker_busy_timeout_and_recovery(tmp_path,monkeypatch):
 _,path,_=broker_files(tmp_path);broker=ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()});ready=threading.Event();release=threading.Event();errors=[]
 monkeypatch.setattr("licensing.authority_service._LOCK_TIMEOUT_SECONDS",.05)
 def holder():
  with broker.connect():ready.set();release.wait(2)
 def waiter():
  ready.wait(2)
  try:
   with broker.connect():pass
  except Exception as e:errors.append(str(e))
 t=threading.Thread(target=holder);w=threading.Thread(target=waiter);t.start();w.start();w.join(1);assert errors==["database_broker_busy"];release.set();t.join(2)
 with broker.connect() as db:assert db.execute("SELECT 1").fetchone()[0]==1
 broker.close()

def test_production_broker_authority_signed_entitlement_reuses_outer_connection(tmp_path,monkeypatch):
 from datetime import datetime,timezone
 from cryptography.hazmat.primitives import serialization
 from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
 from licensing.signer_ceremony import OfflineFixtureMonotonicAnchor
 root,path,_=broker_files(tmp_path);broker=ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()});key=Ed25519PrivateKey.generate();public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo);descriptor={"schema_version":1,"purpose":"growthmap-license-authority-signing","domain":"growthmap-activation-certificate-v2","algorithm":"Ed25519","authority_id":"growthmap-authority-primary","key_id":"test-key","generation":1,"activated_at":"2026-08-08T00:00:00Z","predecessor_generation":None,"public_key_sha256":hashlib.sha256(public).hexdigest(),"provider_attestation_id":"test-attestation"};anchor=OfflineFixtureMonotonicAnchor();authority=LicenseAuthority.__new__(LicenseAuthority);authority._construct(broker,key,descriptor,public,anchor,lambda:datetime(2026,8,8,tzinfo=timezone.utc));identity=authority.handshake();calls=0;real=broker.connect
 def counted():
  nonlocal calls
  calls+=1;return real()
 monkeypatch.setattr(broker,"connect",counted);result=authority.create_external_entitlement(source="payment",source_id="1"*64,payload_digest="2"*64,authority_id=authority.authority_id,signer_identity=identity);assert result["ack_signature"] and calls==2
 device=Ed25519PrivateKey.generate();device_public=__import__('base64').b64encode(device.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode();challenge=authority.issue_activation_challenge(license_id=result["license_id"],device_public_key=device_public);proof=__import__('base64').b64encode(device.sign(activation_challenge(result["license_id"],device_public,challenge["nonce"]))).decode();certificate=authority.activate_challenge(challenge_id=challenge["challenge_id"],proof=proof,expected_flow_kind="payment");assert certificate["signature"]
 revoked=authority.revoke_external_entitlement(source="payment",source_id="1"*64,payload_digest="2"*64,authority_id=authority.authority_id,signer_identity=identity,license_id=result["license_id"],payment_proof="5"*64,tx_hash="0x"+"6"*64,created_at="2026-08-08T00:00:00Z");assert revoked["ack_signature"]
 anchor._claim={"generation":1,"ceremony_sha256":"0"*64}
 with pytest.raises(RuntimeError,match="signer_state_conflict"):authority.create_external_entitlement(source="payment",source_id="3"*64,payload_digest="4"*64,authority_id=authority.authority_id,signer_identity=identity)
 authority.close()

def test_production_broker_second_process_lock_contention(tmp_path):
 import subprocess,sys
 root,path,_=broker_files(tmp_path);broker=ProductionSQLiteBroker(path,os.getuid(),{0,os.getuid()});code="from licensing.authority_service import ProductionSQLiteBroker;import os,sys;ProductionSQLiteBroker(__import__('pathlib').Path(sys.argv[1]),os.getuid(),{0,os.getuid()})"
 env={**os.environ,"PYTHONPATH":str(Path(__file__).parents[1])};run=subprocess.run([sys.executable,"-c",code,str(path)],env=env,capture_output=True,text=True)
 assert run.returncode!=0 and "database_custody_lock_contended" in run.stderr
 broker.close()

def anchor_files(tmp_path):
 a=tmp_path/"anchor";l=tmp_path/"anchor.lock";a.write_text('{"generation":0,"ceremony_sha256":null}');a.chmod(0o400);l.touch(0o600);l.chmod(0o600);return a,l

def test_anchor_idempotent_cas_rechecks_replaced_lock(tmp_path,monkeypatch):
 a,l=anchor_files(tmp_path);anchor=LocalV1PersistentAnchor(a,os.getuid());new={"generation":1,"ceremony_sha256":"a"*64};anchor.compare_and_advance({"generation":0,"ceremony_sha256":None},new);original=anchor._read_locked
 def replace_after_read(*args):
  result=original(*args);replacement=tmp_path/"replacement";replacement.touch(0o600);replacement.chmod(0o600);os.replace(replacement,l);return result
 monkeypatch.setattr(anchor,"_read_locked",replace_after_read)
 with pytest.raises(RuntimeError,match="lock_changed"):anchor.compare_and_advance(new,new)

def test_local_anchor_cas_restart_and_stale_temp(tmp_path):
 a,_=anchor_files(tmp_path);(tmp_path/".anchor.new.stale").write_text("attacker")
 anchor=LocalV1PersistentAnchor(a,os.getuid());new={"generation":1,"ceremony_sha256":"a"*64};assert anchor.compare_and_advance({"generation":0,"ceremony_sha256":None},new)==new;assert LocalV1PersistentAnchor(a,os.getuid()).read()==new;assert (tmp_path/".anchor.new.stale").exists()

def test_anchor_lock_replacement_detected(tmp_path,monkeypatch):
 a,l=anchor_files(tmp_path);anchor=LocalV1PersistentAnchor(a,os.getuid());original=anchor._open_lock
 def swapped(dfd,name,parent):
  fd=original(dfd,name,parent);replacement=tmp_path/"replacement";replacement.touch(0o600);replacement.chmod(0o600);os.replace(replacement,l);return fd
 monkeypatch.setattr(anchor,"_open_lock",swapped)
 with pytest.raises(RuntimeError,match="lock_changed"):anchor.read()

@pytest.mark.parametrize('mode',[0o440,0o444,0o600])
def test_service_owned_config_requires_exact_0400(mode,tmp_path):
 p,cfg=root_config(tmp_path);p.chmod(mode)
 with pytest.raises(RuntimeError,match='policy_invalid'):load_production_config(p,expected_uid=os.getuid())

def test_production_config_requires_explicit_matching_uid_and_basename(tmp_path):
 p,cfg=root_config(tmp_path)
 with pytest.raises(TypeError):load_production_config(p)
 with pytest.raises(RuntimeError):load_production_config(p,expected_uid=os.getuid()+1)
 alias=tmp_path/'other.json';alias.write_bytes(p.read_bytes());alias.chmod(0o400)
 with pytest.raises(RuntimeError,match='path_invalid'):load_production_config(alias,expected_uid=os.getuid())
