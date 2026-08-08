import json,sqlite3,threading,time
from dataclasses import replace
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pytest
from growthmap_payments.ops import MARKER,MARKER_VALUE,OpsRefusal,backup_pair,bundle_manifest_digest,monitoring_snapshot,reconciliation_report,restore_pair,validate_pair
from growthmap_payments.service import PaymentService
from test_payments import config

def fixture(tmp_path):
 root=tmp_path/'isolated-drill';root.mkdir(parents=True);(root/MARKER).write_bytes(MARKER_VALUE);cfg=config(root/'payments.sqlite3');svc=PaymentService(cfg);return root,cfg,svc

def refresh(svc):
 with svc._db() as db:db.execute('BEGIN IMMEDIATE');svc._write_checkpoint_document(svc._checkpoint_document(db));db.commit()

def seed_states(svc):
 svc.create_order('paypal','fixture-one@local.test')
 manual=svc.create_order('paypal','fixture-two@local.test')['order_id']
 with svc._db() as db:
  db.execute('BEGIN IMMEDIATE');db.execute("UPDATE orders SET state='manual_review' WHERE id=?",(manual,));svc._write_checkpoint_document(svc._checkpoint_document(db));db.commit()
 return manual

def test_backup_restore_pair_integrity_startup_and_counts(tmp_path):
 root,cfg,svc=fixture(tmp_path);seed_states(svc)
 before=monitoring_snapshot(root,cfg.db_path,cfg.settlement_checkpoint_path,cfg.settlement_mac_key)
 result=backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,root/'backup',cfg.settlement_mac_key)
 assert result['schema_version']==13 and result['checkpoint']=='authenticated'
 restored=restore_pair(root,root/'backup',root/'restored',cfg,bundle_manifest_digest(root,root/'backup',cfg.settlement_mac_key))
 assert restored['service_startup']=='ok' and restored['integrity']=='ok' and restored['foreign_keys']=='ok'
 after=validate_pair(root/'restored/payments.sqlite3',root/'restored/issuance.checkpoint',cfg.settlement_mac_key)
 assert before['metrics']['orders']['manual_review']==1 and after['schema_version']==13

def test_wal_online_backup_includes_committed_rows_and_not_wal_file_copy(tmp_path):
 root,cfg,svc=fixture(tmp_path)
 db=sqlite3.connect(cfg.db_path);db.execute('PRAGMA journal_mode=WAL');db.execute('BEGIN IMMEDIATE');db.execute("INSERT INTO external_events VALUES(?,?,?,?)",('a'*64,'fixture',None,'2026-08-08T00:00:00+00:00'));db.commit();db.close();refresh(svc)
 backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,root/'backup',cfg.settlement_mac_key)
 assert not (root/'backup/payments.sqlite3-wal').exists()
 with sqlite3.connect(f"file:{(root/'backup/payments.sqlite3').resolve()}?mode=ro&immutable=1",uri=True) as copy:assert copy.execute("SELECT count(*) FROM external_events").fetchone()[0]==1

def test_corrupt_mismatched_checkpoint_and_partial_pair_refused(tmp_path):
 root,cfg,svc=fixture(tmp_path);backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,root/'backup',cfg.settlement_mac_key)
 cp=root/'backup/issuance.checkpoint';original=cp.read_bytes();cp.write_text('{}')
 with pytest.raises((RuntimeError,OpsRefusal),match='manifest mismatch'):restore_pair(root,root/'backup',root/'bad-restore',cfg,'0'*64)
 cp.write_bytes(original);(root/'backup/manifest.json').unlink()
 with pytest.raises(Exception):restore_pair(root,root/'backup',root/'partial',cfg,'0'*64)
 stale=cfg.settlement_checkpoint_path.read_bytes();svc.create_order('paypal','later@local.test');cfg.settlement_checkpoint_path.write_bytes(stale)
 with pytest.raises(RuntimeError,match='mismatch'):validate_pair(cfg.db_path,cfg.settlement_checkpoint_path,cfg.settlement_mac_key)

def test_tampered_migration_ledger_and_schema_detected(tmp_path):
 root,cfg,svc=fixture(tmp_path)
 with sqlite3.connect(cfg.db_path) as db:db.execute("UPDATE migration_ledger SET checksum=? WHERE version=13",('0'*64,))
 with pytest.raises(RuntimeError,match='migration/schema'):validate_pair(cfg.db_path,cfg.settlement_checkpoint_path,cfg.settlement_mac_key)
 root2,cfg2,svc2=fixture(tmp_path/'other')
 with sqlite3.connect(cfg2.db_path) as db:db.execute('PRAGMA user_version=12')
 with pytest.raises(RuntimeError,match='migration/schema'):validate_pair(cfg2.db_path,cfg2.settlement_checkpoint_path,cfg2.settlement_mac_key)

def test_monitor_thresholds_exit_codes_and_secret_minimization(tmp_path):
 root,cfg,svc=fixture(tmp_path);assert monitoring_snapshot(root,cfg.db_path,cfg.settlement_checkpoint_path,cfg.settlement_mac_key)['exit_code']==0
 secret='recovery-SECRET@example.test';oid=svc.create_order('paypal',secret)['order_id']
 with svc._db() as db:
  db.execute('BEGIN IMMEDIATE');db.execute("UPDATE orders SET state='manual_review' WHERE id=?",(oid,));db.execute("INSERT INTO whop_webhook_inbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",('provider-secret-id','f'*64,'2026-08-08T00:00:00+00:00','refund',oid,'raw-provider-ref','signature-looking-ref','2026-08-08T00:00:00+00:00','quarantined',8,None,'2026-08-08T00:00:00+00:00','e'*64));svc._write_checkpoint_document(svc._checkpoint_document(db));db.commit()
 snap=monitoring_snapshot(root,cfg.db_path,cfg.settlement_checkpoint_path,cfg.settlement_mac_key,datetime(2026,8,8,1,tzinfo=timezone.utc));assert snap['severity']=='warning' and snap['exit_code']==1
 report=reconciliation_report(root,cfg.db_path,cfg.settlement_checkpoint_path,cfg.settlement_mac_key);encoded=json.dumps({'snapshot':snap,'report':report})
 for forbidden in (secret,'provider-secret-id','raw-provider-ref','signature-looking-ref','f'*64,'e'*64):assert forbidden not in encoded
 cfg.settlement_checkpoint_path.write_text('{}');critical=monitoring_snapshot(root,cfg.db_path,cfg.settlement_checkpoint_path,cfg.settlement_mac_key);assert critical['severity']=='critical' and critical['exit_code']==2

def test_reconciliation_is_read_only_bounded_and_actionable(tmp_path):
 root,cfg,svc=fixture(tmp_path);seed_states(svc)
 with svc._db() as db:before=tuple(db.execute("SELECT count(*),sum(state='manual_review') FROM orders").fetchone())
 report=reconciliation_report(root,cfg.db_path,cfg.settlement_checkpoint_path,cfg.settlement_mac_key,1)
 with svc._db() as db:after=tuple(db.execute("SELECT count(*),sum(state='manual_review') FROM orders").fetchone())
 assert before==after and report['read_only'] is True and report['count']<=1 and len(report['items'][0]['entity'])==34 and 'action' in report['items'][0]
 with pytest.raises(ValueError):reconciliation_report(root,cfg.db_path,cfg.settlement_checkpoint_path,cfg.settlement_mac_key,101)

def test_refuses_missing_marker_escape_and_live_looking_paths(tmp_path):
 root,cfg,svc=fixture(tmp_path)
 (root/MARKER).unlink()
 critical=monitoring_snapshot(root,cfg.db_path,cfg.settlement_checkpoint_path,cfg.settlement_mac_key);assert critical['exit_code']==2
 (root/MARKER).write_bytes(MARKER_VALUE)
 with pytest.raises(OpsRefusal,match='escapes'):backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,tmp_path/'outside',cfg.settlement_mac_key)
 live=root/'production-backup'
 with pytest.raises(OpsRefusal,match='live-looking'):backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,live,cfg.settlement_mac_key)

def test_marker_artifact_hardlinks_symlinks_and_manifest_names_refused(tmp_path):
 root,cfg,svc=fixture(tmp_path);marker=root/MARKER;real=root/'marker-real';marker.rename(real);marker.symlink_to(real)
 assert monitoring_snapshot(root,cfg.db_path,cfg.settlement_checkpoint_path,cfg.settlement_mac_key)['exit_code']==2
 marker.unlink();real.rename(marker);alias=root/'db-alias';__import__('os').link(cfg.db_path,alias)
 with pytest.raises(OpsRefusal,match='single-link'):backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,root/'backup',cfg.settlement_mac_key)
 alias.unlink();backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,root/'backup',cfg.settlement_mac_key)
 manifest=root/'backup/manifest.json';value=json.loads(manifest.read_text());value['database']='../payments.sqlite3';manifest.write_text(json.dumps(value))
 with pytest.raises(OpsRefusal,match='manifest'):restore_pair(root,root/'backup',root/'restore',cfg,'0'*64)

def test_atomic_no_clobber_exact_bundle_and_concurrent_publish(tmp_path):
 root,cfg,svc=fixture(tmp_path);destination=root/'backup';destination.mkdir()
 with pytest.raises(OpsRefusal,match='destination'):backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,destination,cfg.settlement_mac_key,1)
 destination.rmdir();errors=[]
 def run():
  try:backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,destination,cfg.settlement_mac_key,1)
  except Exception as e:errors.append(e)
 threads=[threading.Thread(target=run) for _ in range(2)];[t.start() for t in threads];[t.join() for t in threads]
 assert len(errors)==1 and set(p.name for p in destination.iterdir())=={'payments.sqlite3','issuance.checkpoint','manifest.json'}
 assert not any(p.name.endswith(('-wal','-shm','-journal')) for p in destination.iterdir())

def test_compound_unicode_nested_alias_and_report_scoped_ids(tmp_path):
 root,cfg,svc=fixture(tmp_path);seed_states(svc)
 for name in ('myProductionBackup','LİVE-backup','staging2'):
  with pytest.raises(OpsRefusal):backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,root/name,cfg.settlement_mac_key,1)
 with pytest.raises(OpsRefusal):backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,root/'nested'/'backup',cfg.settlement_mac_key,1)
 with pytest.raises(OpsRefusal):backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,cfg.db_path,cfg.settlement_mac_key,1)
 a=reconciliation_report(root,cfg.db_path,cfg.settlement_checkpoint_path,cfg.settlement_mac_key);b=reconciliation_report(root,cfg.db_path,cfg.settlement_checkpoint_path,cfg.settlement_mac_key)
 assert a['items'][0]['entity']!=b['items'][0]['entity']

def test_expected_digest_required_and_mismatch_refused(tmp_path):
 root,cfg,svc=fixture(tmp_path);backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,root/'backup',cfg.settlement_mac_key);digest=bundle_manifest_digest(root,root/'backup',cfg.settlement_mac_key)
 with pytest.raises(OpsRefusal,match='required'):restore_pair(root,root/'backup',root/'a',cfg,'')
 with pytest.raises(OpsRefusal,match='mismatch'):restore_pair(root,root/'backup',root/'b',cfg,'0'*64)
 assert not (root/'b').exists();assert restore_pair(root,root/'backup',root/'ok',cfg,digest)['service_startup']=='ok'

def test_backup_publication_boundary_byte_flip_never_succeeds(tmp_path,monkeypatch):
 import growthmap_payments.ops as ops
 root,cfg,svc=fixture(tmp_path)
 def hook(stage,post):
  if not post:
   p=stage/'payments.sqlite3';b=p.read_bytes();p.write_bytes(b[:-1]+bytes([b[-1]^1]))
 monkeypatch.setattr(ops,'_PUBLICATION_HOOK',hook)
 with pytest.raises(OpsRefusal,match='changed'):backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,root/'backup',cfg.settlement_mac_key,1)
 assert not (root/'backup').exists()

def test_restore_publication_boundary_replacement_never_succeeds(tmp_path,monkeypatch):
 import growthmap_payments.ops as ops
 root,cfg,svc=fixture(tmp_path);backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,root/'backup',cfg.settlement_mac_key);digest=bundle_manifest_digest(root,root/'backup',cfg.settlement_mac_key)
 def hook(stage,post):
  if not post:
   p=stage/'manifest.json';p.unlink();p.write_text('{}')
 monkeypatch.setattr(ops,'_PUBLICATION_HOOK',hook)
 with pytest.raises(OpsRefusal):restore_pair(root,root/'backup',root/'restored',cfg,digest)
 assert not (root/'restored').exists()

def test_sparse_oversize_preflight_and_monitor_critical_without_temp_growth(tmp_path,monkeypatch):
 import growthmap_payments.ops as ops
 root,cfg,svc=fixture(tmp_path);before=set(root.iterdir())
 monkeypatch.setattr(ops,'MAX_DB_BYTES',1)
 with pytest.raises(OpsRefusal,match='byte bound'):backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,root/'backup',cfg.settlement_mac_key,1)
 assert monitoring_snapshot(root,cfg.db_path,cfg.settlement_checkpoint_path,cfg.settlement_mac_key)['exit_code']==2
 assert not any(p.name.startswith('.ops-stage-') or p.name.startswith('.ops-readonly-') for p in root.iterdir())

def test_backup_deadline_progress_abort_is_bounded(tmp_path,monkeypatch):
 import growthmap_payments.ops as ops
 root,cfg,svc=fixture(tmp_path);monkeypatch.setattr(ops,'BACKUP_DEADLINE_SECONDS',-1)
 with pytest.raises(OpsRefusal,match='resource bound'):backup_pair(root,cfg.db_path,cfg.settlement_checkpoint_path,root/'backup',cfg.settlement_mac_key,1)
 assert not (root/'backup').exists()
