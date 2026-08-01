"""GrowthMap payment ledger: SQLite transactions, not process locks, are authoritative."""
from __future__ import annotations
import base64, hashlib, hmac, json, os, re, secrets, sqlite3, tempfile, threading, time, uuid
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from typing import Any,Protocol
from urllib.parse import urlsplit
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
BASE_NETWORK="eip155:8453";BASE_USDC="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";EARLY_LIMIT=50
EARLY={"x402":10_000_000,"paypal":1000};REGULAR={"x402":29_000_000,"paypal":2900};SCHEMA_VERSION=9
MIGRATIONS={1:("001_payments_v1.sql","311bc81c68f1fc7f63ec27c309600b8ac852774ee7f535a5783bc2dc625ca28d"),2:("002_settlement_security.sql","2330d6397b12b2d5bd4ecd89dd98bb3a59cf05c2722a4a82d64640b0fc09b54c"),3:("003_evidence_identity.sql","28814bd1eac98f1e31310a823c4e2983928811ce1b3a05f80266703583f04106"),4:("004_terminal_evidence_trust.sql","f2400926eda875753a06c64c2bd045b0806b02fdc4bc23f1f05c177b3883d451"),5:("005_external_terminal_checkpoint.sql","85c2eb7ccaf6d57c916cd2fbbe594c32ad70436fb38605949e25602b345ce045"),6:("006_authenticated_issuance_closure.sql","842904b883fc5e529d25019b8deed41467429df239ec4db92df9dd2fa23e4c9e"),7:("007_signed_revocation_assertions.sql","32e37e78522e54330753b1843dc7b7fdaf98015442320221350629cdd85489c7"),8:("008_device_activation_entitlements.sql","2c72ffee4fbd739c84f85c9ae7d8cf267bdffb84bea88779198e50e78e6e71af"),9:("009_authority_revocation_outbox.sql","367b701a724639518e9854fd0159d24bb2ce78309242f58fe64206f9367989fc")}
TRANSITIONS={"reject":{"pending_payment","manual_review"},"refund":{"payment_confirmed","license_issued"},"revoke":{"license_issued"}}
_CHECKPOINT_LOCKS_GUARD=threading.Lock();_CHECKPOINT_LOCKS:dict[str,threading.RLock]={}
def _checkpoint_serialized(method):
 def serialized(self,*args,**kwargs):
  with self._checkpoint_lock:return method(self,*args,**kwargs)
 return serialized
class Reconciler(Protocol):
 def reconcile(self,intent:dict[str,Any])->dict[str,Any]:...
class Facilitator(Protocol):
 def verify(self,signature:str,requirements:dict[str,Any])->dict[str,Any]:...
 def settle(self,signature:str,requirements:dict[str,Any])->dict[str,Any]:...
@dataclass(frozen=True)
class Config:
 db_path:Path;recipient:str;admin_secret_hash:str;signing_key:Ed25519PrivateKey|None;allowed_admin_origin:str="";csrf_secret:str="";purchase_resource_base:str="";quote_seconds:int=300;intent_seconds:int=60;production:bool=False;rate_limit:int=30;isolated_test:bool=False;settlement_mac_key:bytes|None=None;settlement_checkpoint_path:Path|None=None;environment:str="test";merchant_id:str="growthmap";authority_id:str="growthmap-authority-primary"
 def validate(self):
  if not re.fullmatch(r"0x[0-9a-fA-F]{40}",self.recipient) or self.recipient.lower()=="0x"+"0"*40:raise RuntimeError("payment recipient missing/placeholder")
  if not isinstance(self.settlement_mac_key,bytes) or len(self.settlement_mac_key)<32:raise RuntimeError("external settlement MAC key missing/weak")
  if not isinstance(self.settlement_checkpoint_path,Path):raise RuntimeError("external settlement checkpoint path missing")
  if self.settlement_checkpoint_path.resolve()==self.db_path.resolve():raise RuntimeError("settlement checkpoint must be external to database")
  resource=urlsplit(self.purchase_resource_base)
  if resource.scheme!="https" or not resource.netloc or (not self.isolated_test and re.search(r"invalid|example|localhost|127\.0\.0\.1",resource.netloc,re.I)):raise RuntimeError("HTTPS purchase resource base missing/placeholder")
  if self.production:
   origin=urlsplit(self.allowed_admin_origin)
   if origin.scheme!="https" or not origin.netloc or origin.path not in("", "/") or re.search(r"invalid|example|localhost|127\.0\.0\.1",origin.netloc,re.I):raise RuntimeError("production admin origin missing/placeholder")
   if not self.admin_secret_hash.startswith("$argon2id$") or not self.csrf_secret or self.signing_key is None:raise RuntimeError("production Argon2id auth/CSRF/key provider missing")
class PaymentService:
 def __init__(self,config:Config,facilitator:Facilitator|None=None):
  config.validate();self.config=config;self.facilitator=facilitator;self._checkpoint_failed=False
  checkpoint_key=str(config.settlement_checkpoint_path.resolve())
  with _CHECKPOINT_LOCKS_GUARD:self._checkpoint_lock=_CHECKPOINT_LOCKS.setdefault(checkpoint_key,threading.RLock())
  self._init()
 def _db(self):
  db=sqlite3.connect(self.config.db_path,timeout=30,isolation_level=None,check_same_thread=False);db.row_factory=sqlite3.Row;db.execute("PRAGMA journal_mode=WAL");db.execute("PRAGMA foreign_keys=ON");db.execute("PRAGMA busy_timeout=30000");return db
 def _sql_statements(self,text):
  statement=""
  for line in text.splitlines(True):
   statement+=line
   if sqlite3.complete_statement(statement):
    yield statement;statement=""
  if statement.strip():raise RuntimeError("incomplete migration SQL")
 def _evidence_binding(self,intent,tx_hash,evidence_hash,source,finality_at,outcome="paid"):
  def optional(name):
   try:return intent[name]
   except (KeyError,IndexError):return None
  # settled and finalized_paid are one authenticated paid outcome, allowing the
  # trusted issuance transition without weakening any other immutable field.
  fields={"amount_minor":intent["amount_minor"],"created_at":intent["created_at"],"currency":intent["currency"],"evidence_hash":evidence_hash,"evidence_source":source,"finality_at":finality_at,"finality_basis":optional("finality_basis"),"intent_id":intent["intent_id"],"lease_expires_at":intent["lease_expires_at"],"nonce_hash":intent["nonce_hash"],"order_id":intent["order_id"],"proof_hash":intent["proof_hash"],"reconciled_by":intent["reconciled_by"],"reserved_ordinal":intent["reserved_ordinal"],"state":"paid" if outcome=="paid" else "cancelled_unpaid","tx_hash":tx_hash,"verified_payer":optional("verified_payer"),"settled_payer":optional("settled_payer")}
  if fields["finality_basis"] is None and fields["verified_payer"] is None and fields["settled_payer"] is None:
   for legacy_field in ("finality_basis","verified_payer","settled_payer"):fields.pop(legacy_field)
  payload=json.dumps(fields,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
  return hmac.new(self.config.settlement_mac_key,payload,hashlib.sha256).hexdigest()
 def _schema_snapshot(self,db):
  return [{"type":r[0],"name":r[1],"table":r[2],"sql":re.sub(r"\s+"," ",r[3].strip())} for r in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE type IN('table','index','trigger') AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY type,name")]
 def _issuance_snapshot(self,db):
  tables=("orders","payment_proofs","external_events","settlement_intents","audit_events","migration_ledger","terminal_checkpoint_state")+(("revocation_assertions",) if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='revocation_assertions'").fetchone() else ())+(("entitlement_outbox",) if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='entitlement_outbox'").fetchone() else ())+(("revocation_outbox",) if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='revocation_outbox'").fetchone() else ());closure={}
  for table in tables:
   cols=[r[1] for r in db.execute(f"PRAGMA table_info({table})")];order=",".join('"'+c+'"' for c in cols);closure[table]=[dict(r) for r in db.execute(f'SELECT * FROM "{table}" ORDER BY {order}')]
  schema=self._schema_snapshot(db);raw=json.dumps({"schema":schema,"rows":closure},sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
  return sum(map(len,closure.values())),hashlib.sha256(raw).hexdigest(),hashlib.sha256(json.dumps(schema,sort_keys=True,separators=(",",":")).encode()).hexdigest()
 def _checkpoint_document(self,db):
  seq=db.execute("SELECT sequence FROM terminal_checkpoint_state WHERE singleton=1").fetchone()[0];count,root,schema=self._issuance_snapshot(db);core={"count":count,"root":root,"schema":schema,"sequence":seq,"version":2};raw=json.dumps(core,sort_keys=True,separators=(",",":")).encode();core["mac"]=hmac.new(self.config.settlement_mac_key,b"growthmap-issuance-checkpoint-v2\0"+raw,hashlib.sha256).hexdigest();return core
 def _write_checkpoint_document(self,doc):
  p=self.config.settlement_checkpoint_path;p.parent.mkdir(parents=True,exist_ok=True);data=(json.dumps(doc,sort_keys=True,separators=(",",":"))+"\n").encode();fd,tmp=tempfile.mkstemp(prefix=p.name+".",dir=p.parent)
  try:
   with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
   os.replace(tmp,p)
   try:dfd=os.open(p.parent,os.O_RDONLY);os.fsync(dfd);os.close(dfd)
   except OSError:pass
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
 def _write_checkpoint(self):
  with self._checkpoint_lock:
   with self._db() as db:
    db.execute("BEGIN IMMEDIATE");self._write_checkpoint_document(self._checkpoint_document(db));db.commit()
 def _verify_legacy_v5_checkpoint(self,db):
  p=self.config.settlement_checkpoint_path;rows=[dict(r) for r in db.execute("SELECT * FROM settlement_intents WHERE state IN('settled','finalized_paid','cancelled_unpaid') ORDER BY intent_id")];root=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest();seq=db.execute("SELECT sequence FROM terminal_checkpoint_state WHERE singleton=1").fetchone()[0];expected={"count":len(rows),"root":root,"sequence":seq,"version":1}
  if not p.exists():
   if rows:raise RuntimeError("external settlement checkpoint missing with terminal rows")
   return
  try: doc=json.loads(p.read_text());mac=doc.pop("mac")
  except Exception as e:raise RuntimeError("external settlement checkpoint unreadable") from e
  valid=hmac.new(self.config.settlement_mac_key,b"growthmap-terminal-checkpoint-v1\0"+json.dumps(doc,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest()
  if set(doc)!={"version","sequence","count","root"} or not hmac.compare_digest(str(mac),valid) or doc!=expected:raise RuntimeError("external settlement checkpoint authentication failed")
 def _verify_or_initialize_checkpoint(self,db=None):
  with self._checkpoint_lock:
   owned=db is None
   if owned:
    db=self._db();db.execute("BEGIN IMMEDIATE")
   try:
    p=self.config.settlement_checkpoint_path;expected=self._checkpoint_document(db);text=p.read_text() if p.exists() else None
    if text is None:raise RuntimeError("external issuance checkpoint missing")
    try:doc=json.loads(text);mac=doc.pop("mac")
    except Exception as e:raise RuntimeError("external issuance checkpoint invalid") from e
    valid=hmac.new(self.config.settlement_mac_key,b"growthmap-issuance-checkpoint-v2\0"+json.dumps(doc,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest()
    if set(doc)!={"version","sequence","count","root","schema"} or not hmac.compare_digest(str(mac),valid):raise RuntimeError("external issuance checkpoint authentication failed")
    expected.pop("mac")
    if doc!=expected:raise RuntimeError("external issuance checkpoint/database mismatch")
   finally:
    if owned:db.rollback();db.close()
 def _commit_trusted(self,db):
  if SCHEMA_VERSION<6:db.commit();return
  with self._checkpoint_lock:
   db.execute("UPDATE terminal_checkpoint_state SET sequence=sequence+1 WHERE singleton=1")
   # Publish the checkpoint while this same BEGIN IMMEDIATE still excludes every
   # SQLite writer. Crash before DB commit leaves a detectable mismatch; never
   # reopen/snapshot after commit, which would bless an intervening attacker.
   try:
    doc=self._checkpoint_document(db);self._write_checkpoint_document(doc);db.commit()
   except Exception as e:
    if db.in_transaction:db.rollback()
    self._checkpoint_failed=True;raise RuntimeError("external issuance checkpoint update failed; service is fail-closed") from e
 def _commit_terminal(self,db):self._commit_trusted(db)
 def _apply_migration(self,db,target,text):
  filename,checksum=MIGRATIONS[target]
  db.execute("BEGIN IMMEDIATE")
  try:
   for statement in self._sql_statements(text):db.execute(statement)
   if target==2:
    for v in (1,2):
     name,digest=MIGRATIONS[v];db.execute("INSERT INTO migration_ledger VALUES(?,?,?,?)",(v,name,digest,self.now()))
   elif target>2:
    # Backfill evidence introduced by v3 inside the same migration transaction.
    if target==3:
     for row in db.execute("SELECT * FROM settlement_intents WHERE evidence_hash IS NOT NULL"):
      outcome="unpaid" if row["state"]=="cancelled_unpaid" else "paid"
      binding=self._evidence_binding(row,row["tx_hash"],row["evidence_hash"],row["evidence_source"],row["finality_at"],outcome)
      db.execute("UPDATE settlement_intents SET evidence_binding=? WHERE intent_id=?",(binding,row["intent_id"]))
    name,digest=MIGRATIONS[target];db.execute("INSERT INTO migration_ledger VALUES(?,?,?,?)",(target,name,digest,self.now()))
   db.execute(f"PRAGMA user_version={target}");db.commit()
  except Exception:
   if db.in_transaction:db.rollback()
   raise
 def _init(self):
  root=Path(__file__).parents[1]/"migrations"
  with self._db() as db:
   version=db.execute("PRAGMA user_version").fetchone()[0]
   if version>SCHEMA_VERSION:raise RuntimeError(f"unsupported payment schema {version}")
   if version==0 and db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]:raise RuntimeError("unversioned non-empty payment database")
   # Once the ledger exists it is authoritative. Never silently reconstruct it.
   if version>=2:
    try:rows={r[0]:(r[1],r[2]) for r in db.execute("SELECT version,filename,checksum FROM migration_ledger")}
    except sqlite3.DatabaseError as e:raise RuntimeError("migration ledger missing") from e
    if rows!={v:MIGRATIONS[v] for v in range(1,version+1)}:raise RuntimeError("migration ledger checksum mismatch")
   if version==5:self._verify_legacy_v5_checkpoint(db)
   migrated=version<SCHEMA_VERSION
   for target in range(version+1,SCHEMA_VERSION+1):
    filename,expected=MIGRATIONS[target];text=(root/filename).read_text();actual=hashlib.sha256(text.encode()).hexdigest()
    if actual!=expected:raise RuntimeError(f"migration checksum mismatch: {filename}")
    self._apply_migration(db,target,text)
   rows={r[0]:(r[1],r[2]) for r in db.execute("SELECT version,filename,checksum FROM migration_ledger")}
   supported_ledger={v:MIGRATIONS[v] for v in range(1,SCHEMA_VERSION+1)}
   if rows!=supported_ledger:raise RuntimeError("migration ledger checksum mismatch")
  # Historical schema targets are exercised by migration compatibility tests.
  # Runtime recovery requires the R6 issuance-closure checkpoint and must not
  # write or reconcile against an older schema.
  if SCHEMA_VERSION<6:return
  if migrated:self._write_checkpoint()
  self._verify_or_initialize_checkpoint()
  self._verify_terminal_evidence();self.recover_durable_settlements();self.reconcile_expired_intents()
 def _verify_terminal_evidence(self,db=None):
  """Authenticate every terminal row using the caller's locked transaction."""
  if self._checkpoint_failed:raise RuntimeError("payment service is fail-closed after checkpoint failure")
  owned=db is None
  if owned:db=self._db();db.execute("BEGIN IMMEDIATE")
  try:rows=db.execute("SELECT * FROM settlement_intents WHERE state IN('settled','finalized_paid','cancelled_unpaid')").fetchall()
  finally:
   if owned:db.rollback();db.close()
  for row in rows:
   outcome="unpaid" if row["state"]=="cancelled_unpaid" else "paid";expected=self._evidence_binding(row,row["tx_hash"],row["evidence_hash"],row["evidence_source"],row["finality_at"],outcome)
   if not hmac.compare_digest(row["evidence_binding"] or "",expected):raise RuntimeError("terminal settlement evidence authentication failed")
 def _assert_terminal_trust(self,db=None):
  if self._checkpoint_failed:raise RuntimeError("payment service is fail-closed after checkpoint failure")
  self._verify_or_initialize_checkpoint(db);self._verify_terminal_evidence(db)
 def recover_durable_settlements(self):
  """Finalize recorded trusted evidence; never call a provider or promote ambiguity."""
  with self._db() as db:ids=[r[0] for r in db.execute("SELECT intent_id FROM settlement_intents WHERE state='settled' ORDER BY created_at")]
  for intent_id in ids:self.finalize_x402_intent(intent_id)
 @_checkpoint_serialized
 def reconcile_expired_intents(self):
  """Startup recovery never retries settlement; expired prepared intents become review."""
  now=self.now()
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);rows=db.execute("SELECT intent_id,order_id FROM settlement_intents WHERE state='prepared' AND lease_expires_at<=?",(now,)).fetchall()
   for r in rows:
    db.execute("UPDATE settlement_intents SET state='ambiguous',updated_at=? WHERE intent_id=?",(now,r["intent_id"]));db.execute("UPDATE orders SET state='manual_review',updated_at=? WHERE id=?",(now,r["order_id"]));self._audit(db,"recovery","settlement_intent.lease_expired",r["order_id"],{"intent_id":r["intent_id"]})
   self._commit_trusted(db)
 @staticmethod
 def now():return datetime.now(timezone.utc).isoformat()
 @staticmethod
 def _hash(value:str):return hashlib.sha256(value.encode()).hexdigest()
 @staticmethod
 def normalize_email(value):
  value=value.strip().lower()
  if len(value)>254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",value):raise ValueError("invalid email")
  return value
 def _audit(self,db,actor,operation,obj,data):
  prior=db.execute("SELECT chain_hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone();prev=prior[0] if prior else "0"*64;stamp=self.now();dh=self._hash(json.dumps(data,sort_keys=True,separators=(",",":"),default=str));chain=self._hash("|".join((prev,stamp,actor,operation,obj,dh)));db.execute("INSERT INTO audit_events(event_id,at,actor,operation,object_id,data_hash,previous_hash,chain_hash) VALUES(?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),stamp,actor,operation,obj,dh,prev,chain))
 @_checkpoint_serialized
 def create_order(self,rail,email,license_name="Personal"):
  if rail not in EARLY:raise ValueError("rail")
  email=self.normalize_email(email);oid=str(uuid.uuid4());recovery=secrets.token_urlsafe(24);now=datetime.now(timezone.utc);expiry=(now+timedelta(seconds=self.config.quote_seconds)).isoformat()
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db)
   allocated=db.execute("SELECT count(*) FROM orders WHERE sale_ordinal IS NOT NULL").fetchone()[0]+db.execute("SELECT count(*) FROM settlement_intents WHERE state IN('prepared','settled','ambiguous')").fetchone()[0];early=allocated<EARLY_LIMIT;amount=(EARLY if early else REGULAR)[rail];currency="USDC" if rail=="x402" else "USD"
   db.execute("INSERT INTO orders(id,recovery_code_hash,rail,state,quoted_amount_minor,currency,tier,quote_expires_at,buyer_email,license_name,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(oid,self._hash(recovery),rail,"pending_payment",amount,currency,"early" if early else "regular",expiry,email,license_name.strip()[:100],now.isoformat(),now.isoformat()));self._audit(db,"buyer","order.created",oid,{"rail":rail,"amount_minor":amount,"currency":currency,"email_hash":self._hash(email)});self._commit_trusted(db)
  return {"order_id":oid,"recovery_code":recovery,"state":"pending_payment","amount_minor":amount,"currency":currency,"tier":"early" if early else "regular","quote_expires_at":expiry}
 @_checkpoint_serialized
 def challenge(self,oid):
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);r=db.execute("SELECT * FROM orders WHERE id=? AND rail='x402'",(oid,)).fetchone();db.rollback()
  if not r:raise KeyError("order")
  if r["state"]!="pending_payment" or datetime.fromisoformat(r["quote_expires_at"])<=datetime.now(timezone.utc):raise ValueError("expired or unavailable")
  resource={"url":f"{self.config.purchase_resource_base.rstrip('/')}/v1/orders/{oid}/purchase","description":"GrowthMap v1 perpetual personal license","mimeType":"application/json"}
  return {"x402Version":2,"resource":resource,"accepts":[{"scheme":"exact","network":BASE_NETWORK,"asset":BASE_USDC,"amount":str(r["quoted_amount_minor"]),"payTo":self.config.recipient,"maxTimeoutSeconds":self.config.quote_seconds,"extra":{"name":"USD Coin","version":"2","orderId":oid,"product":"growthmap","majorVersion":1}}]}
 @_checkpoint_serialized
 def prepare_x402_intent(self,oid,proof_id,nonce,amount,payer=None):
  now=datetime.now(timezone.utc)
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);r=db.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
   if not r or r["rail"]!="x402" or r["state"]!="pending_payment":raise ValueError("order unavailable")
   occupied={x[0] for x in db.execute("SELECT sale_ordinal FROM orders WHERE sale_ordinal IS NOT NULL")}|{x[0] for x in db.execute("SELECT reserved_ordinal FROM settlement_intents WHERE state IN('prepared','settled','ambiguous')")};ordinal=next(i for i in range(1,len(occupied)+2) if i not in occupied);expected=EARLY["x402"] if ordinal<=EARLY_LIMIT else REGULAR["x402"]
   if datetime.fromisoformat(r["quote_expires_at"])<=now or amount!=expected or r["quoted_amount_minor"]!=expected:
    db.execute("UPDATE orders SET state='manual_review',updated_at=? WHERE id=?",(now.isoformat(),oid));self._audit(db,"x402.verify","payment.manual_review",oid,{"provided":amount,"expected":expected});self._commit_trusted(db);raise ValueError("stale quote")
   intent=str(uuid.uuid4());lease=(now+timedelta(seconds=self.config.intent_seconds)).isoformat()
   if payer is not None and not re.fullmatch(r"0x[0-9a-fA-F]{40}",payer):raise ValueError("invalid verified payer")
   try:db.execute("INSERT INTO settlement_intents(intent_id,order_id,proof_hash,nonce_hash,amount_minor,currency,reserved_ordinal,lease_expires_at,state,tx_hash,evidence_hash,evidence_source,finality_at,reconciled_by,created_at,updated_at,evidence_binding,verified_payer,settled_payer,finality_basis) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(intent,oid,self._hash(proof_id),self._hash(nonce),amount,"USDC",ordinal,lease,"prepared",None,None,None,None,None,now.isoformat(),now.isoformat(),None,payer.lower() if payer else None,None,None))
   except sqlite3.IntegrityError as e:raise ValueError("duplicate authorization/order") from e
   self._audit(db,"x402.verify","settlement_intent.prepared",oid,{"intent_id":intent,"ordinal":ordinal,"proof_hash":self._hash(proof_id)});self._commit_trusted(db);return {"intent_id":intent,"ordinal":ordinal}
 @_checkpoint_serialized
 def record_settlement_result(self,intent_id,tx_hash,evidence_hash,evidence_source,finality_at,actor="facilitator",*,payer=None,finality_basis=None):
  if not tx_hash or not evidence_hash or not evidence_source or not finality_at or not finality_basis or datetime.fromisoformat(finality_at)>datetime.now(timezone.utc):raise ValueError("invalid settlement evidence")
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);i=db.execute("SELECT * FROM settlement_intents WHERE intent_id=?",(intent_id,)).fetchone()
   if not i:raise KeyError("intent")
   if not i["verified_payer"] or not payer or payer.lower()!=i["verified_payer"]:raise ValueError("settlement payer mismatch")
   authenticated=dict(i);authenticated.update(reconciled_by=actor,settled_payer=payer.lower(),finality_basis=finality_basis)
   binding=self._evidence_binding(authenticated,tx_hash,evidence_hash,evidence_source,finality_at)
   if i["state"] in {"settled","finalized_paid"}:
    if i["tx_hash"]!=tx_hash or i["evidence_hash"]!=evidence_hash or i["evidence_binding"]!=binding:raise ValueError("conflicting settlement evidence")
    return dict(i)
   if i["state"] not in {"prepared","ambiguous"}:raise ValueError("intent cannot become settled")
   now=self.now()
   try:db.execute("UPDATE settlement_intents SET state='settled',tx_hash=?,evidence_hash=?,evidence_source=?,finality_at=?,evidence_binding=?,reconciled_by=?,updated_at=?,settled_payer=?,finality_basis=? WHERE intent_id=?",(tx_hash,evidence_hash,evidence_source,finality_at,binding,actor,now,payer.lower(),finality_basis,intent_id))
   except sqlite3.IntegrityError as e:raise ValueError("settlement evidence already used") from e
   self._audit(db,actor,"settlement.evidence_recorded",i["order_id"],{"intent_id":intent_id,"tx_hash":self._hash(tx_hash),"evidence_hash":evidence_hash,"source":evidence_source,"binding":binding});self._commit_terminal(db);return dict(db.execute("SELECT * FROM settlement_intents WHERE intent_id=?",(intent_id,)).fetchone())
 @_checkpoint_serialized
 def finalize_x402_intent(self,intent_id):
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);i=db.execute("SELECT * FROM settlement_intents WHERE intent_id=?",(intent_id,)).fetchone()
   if not i:raise KeyError("intent")
   if i["state"] not in {"settled","finalized_paid"} or not i["tx_hash"] or not i["evidence_hash"]:raise ValueError("durable paid evidence required")
   expected=self._evidence_binding(i,i["tx_hash"],i["evidence_hash"],i["evidence_source"],i["finality_at"])
   if not hmac.compare_digest(i["evidence_binding"] or "",expected):raise ValueError("settlement evidence binding mismatch")
   if i["state"]=="finalized_paid":return dict(db.execute("SELECT * FROM orders WHERE id=?",(i["order_id"],)).fetchone())
   result=self._issue_reserved(db,i,i["tx_hash"],datetime.now(timezone.utc),"x402.finalize");self._commit_terminal(db);return result
 @_checkpoint_serialized
 def mark_intent_ambiguous(self,intent_id,reason):
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);i=db.execute("SELECT * FROM settlement_intents WHERE intent_id=?",(intent_id,)).fetchone()
   if i and i["state"]=="prepared":db.execute("UPDATE settlement_intents SET state='ambiguous',updated_at=? WHERE intent_id=?",(self.now(),intent_id));db.execute("UPDATE orders SET state='manual_review',updated_at=? WHERE id=?",(self.now(),i["order_id"]));self._audit(db,"x402.settle","settlement_intent.ambiguous",i["order_id"],{"intent_id":intent_id,"reason_hash":self._hash(reason)})
   self._commit_trusted(db)
 @_checkpoint_serialized
 def reconcile_intent(self,intent_id,reconciler:Reconciler,admin_actor):
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);i=db.execute("SELECT * FROM settlement_intents WHERE intent_id=?",(intent_id,)).fetchone();db.rollback()
  if not i or i["state"] not in {"prepared","ambiguous"}:raise ValueError("intent not reconcilable")
  evidence=reconciler.reconcile(dict(i))
  required={"outcome","evidence_hash","source","finality_at","finality_basis","payer","proof_hash","nonce_hash","order_id"}
  if not required.issubset(evidence) or evidence["proof_hash"]!=i["proof_hash"] or evidence["nonce_hash"]!=i["nonce_hash"] or evidence["order_id"]!=i["order_id"]:raise ValueError("reconciliation evidence binding")
  if evidence["outcome"]=="paid":
   self.record_settlement_result(intent_id,evidence.get("tx_hash"),evidence["evidence_hash"],evidence["source"],evidence["finality_at"],admin_actor,payer=evidence["payer"],finality_basis=evidence["finality_basis"]);return self.finalize_x402_intent(intent_id)
  if evidence["outcome"]!="unpaid" or evidence.get("tx_hash") is not None or datetime.fromisoformat(evidence["finality_at"])>datetime.now(timezone.utc):raise ValueError("final unpaid evidence required")
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);fresh=db.execute("SELECT * FROM settlement_intents WHERE intent_id=?",(intent_id,)).fetchone()
   if fresh["state"] not in {"prepared","ambiguous"}:raise ValueError("reconciliation race")
   now=self.now();authenticated=dict(fresh);authenticated["reconciled_by"]=admin_actor;binding=self._evidence_binding(authenticated,None,evidence["evidence_hash"],evidence["source"],evidence["finality_at"],"unpaid")
   try:db.execute("UPDATE settlement_intents SET state='cancelled_unpaid',evidence_hash=?,evidence_source=?,finality_at=?,evidence_binding=?,reconciled_by=?,updated_at=? WHERE intent_id=?",(evidence["evidence_hash"],evidence["source"],evidence["finality_at"],binding,admin_actor,now,intent_id))
   except sqlite3.IntegrityError as e:raise ValueError("settlement evidence already used") from e
   db.execute("UPDATE orders SET state='expired',updated_at=? WHERE id=?",(now,fresh["order_id"]));self._audit(db,admin_actor,"settlement.cancelled_unpaid",fresh["order_id"],{"intent_id":intent_id,"ordinal_released":fresh["reserved_ordinal"],"evidence_hash":evidence["evidence_hash"],"source":evidence["source"],"binding":binding});self._commit_terminal(db);return {"intent_id":intent_id,"state":"cancelled_unpaid","released_ordinal":fresh["reserved_ordinal"]}
 def _issue_reserved(self,db,intent,tx_hash,now,actor):
  """Atomically confirm payment and enqueue authority delivery; never sign a license."""
  oid=intent["order_id"];stamp=now.isoformat();source_context={"environment":self.config.environment,"merchant":self.config.merchant_id,"payee":self.config.recipient.lower(),"network":BASE_NETWORK,"asset":BASE_USDC.lower(),"product":"growthmap","major":1,"order":oid};source_id=hashlib.sha256(json.dumps(source_context).encode()).hexdigest();db.execute("INSERT INTO payment_proofs VALUES(?,?,?,?,?)",(intent["proof_hash"],"x402",oid,tx_hash,stamp));db.execute("UPDATE orders SET state='payment_confirmed',sale_ordinal=?,confirmed_at=?,updated_at=?,tx_hash=? WHERE id=?",(intent["reserved_ordinal"],stamp,stamp,tx_hash,oid));self._audit(db,actor,"payment.confirmed",oid,{"ordinal":intent["reserved_ordinal"]});db.execute("INSERT INTO entitlement_outbox(order_id,source,source_id,proof_hash,tx_hash,evidence_hash,payer,network,asset,amount_minor,product,major_version,state,created_at,next_attempt_at) VALUES(?,'x402',?,?,?,?,?,'eip155:8453',?,?, 'growthmap',1,'pending',?,?)",(oid,source_id,intent["proof_hash"],tx_hash,intent["evidence_hash"],intent["settled_payer"],BASE_USDC,intent["amount_minor"],stamp,stamp));db.execute("UPDATE settlement_intents SET state='finalized_paid',updated_at=? WHERE intent_id=?",(stamp,intent["intent_id"]));self._audit(db,"issuer","entitlement.enqueued",oid,{"source":"x402"});return dict(db.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone())
 def _outbox_payload_digest(self,row):
  return hashlib.sha256(json.dumps({k:row[k] for k in ("order_id","source","source_id","proof_hash","tx_hash","evidence_hash","payer","network","asset","amount_minor","product","major_version")}).encode()).hexdigest()
 def claim_outbox(self,worker_id,lease_seconds=30,order_id=None):
  now=datetime.now(timezone.utc);expires=(now+timedelta(seconds=lease_seconds)).isoformat()
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);sql="SELECT e.* FROM entitlement_outbox e JOIN orders o ON o.id=e.order_id WHERE o.state='payment_confirmed' AND ((e.state='pending' AND (e.next_attempt_at IS NULL OR e.next_attempt_at<=?)) OR (e.state='leased' AND e.lease_expires_at<=?))";params=[now.isoformat(),now.isoformat()]
   if order_id is not None:sql+=" AND order_id=?";params.append(order_id)
   row=db.execute(sql+" ORDER BY created_at LIMIT 1",params).fetchone()
   if not row:db.rollback();return None
   fence=row["fencing_version"]+1;db.execute("UPDATE entitlement_outbox SET state='leased',lease_owner=?,lease_expires_at=?,attempt_count=attempt_count+1,fencing_version=? WHERE order_id=? AND fencing_version=?",(worker_id,expires,fence,row["order_id"],row["fencing_version"]));self._commit_trusted(db);return dict(db.execute("SELECT * FROM entitlement_outbox WHERE order_id=?",(row["order_id"],)).fetchone())
 def deliver_claimed_outbox(self,row,authority,worker_id):
  # Revalidate the fence and local policy before crossing the database boundary:
  # a concurrent refund of a pending entitlement must never create a license.
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);fresh=db.execute("SELECT e.state,e.lease_owner,e.fencing_version,o.state AS order_state FROM entitlement_outbox e JOIN orders o ON o.id=e.order_id WHERE e.order_id=?",(row["order_id"],)).fetchone();db.rollback()
  if not fresh or fresh["state"]!="leased" or fresh["lease_owner"]!=worker_id or fresh["fencing_version"]!=row["fencing_version"] or fresh["order_state"]!="payment_confirmed":raise RuntimeError("outbox lease lost")
  if authority.handshake().get("authority_id")!=self.config.authority_id:raise ValueError("wrong_authority")
  digest=self._outbox_payload_digest(row);entitlement=authority.create_external_entitlement(source=row["source"],source_id=row["source_id"],payload_digest=digest,authority_id=self.config.authority_id,major_version=1,seat_limit=2)
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);fresh=db.execute("SELECT * FROM entitlement_outbox WHERE order_id=?",(row["order_id"],)).fetchone()
   if fresh["state"]!="leased" or fresh["lease_owner"]!=worker_id or fresh["fencing_version"]!=row["fencing_version"]:db.rollback();raise RuntimeError("outbox lease lost")
   now=self.now();order=db.execute("SELECT state FROM orders WHERE id=?",(row["order_id"],)).fetchone();db.execute("UPDATE entitlement_outbox SET state='delivered',license_id=?,delivered_at=?,delivery_receipt=?,lease_owner=NULL,lease_expires_at=NULL WHERE order_id=?",(entitlement["license_id"],now,entitlement["delivery_receipt"],row["order_id"]))
   if order["state"]=="payment_confirmed":db.execute("UPDATE orders SET state='license_issued',license_id=?,updated_at=? WHERE id=?",(entitlement["license_id"],now,row["order_id"]));self._audit(db,"issuer","entitlement.delivered",row["order_id"],{"license_id":entitlement["license_id"]})
   elif order["state"]=="refunded":self._enqueue_revocation(db,row,entitlement["license_id"],"refund","refund",now);self._audit(db,"issuer","entitlement.delivered_after_refund",row["order_id"],{"license_id":entitlement["license_id"]})
   else:db.rollback();raise RuntimeError("outbox lease lost")
   self._commit_trusted(db);return entitlement
 def fail_outbox(self,row,worker_id,error,max_attempts=8):
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);fresh=db.execute("SELECT state,lease_owner,fencing_version,attempt_count FROM entitlement_outbox WHERE order_id=?",(row["order_id"],)).fetchone()
   if not fresh or fresh["state"]!="leased" or fresh["lease_owner"]!=worker_id or fresh["fencing_version"]!=row["fencing_version"]:db.rollback();return
   state="quarantined" if fresh["attempt_count"]>=max_attempts else "pending";delay=min(3600,2**min(fresh["attempt_count"],10));db.execute("UPDATE entitlement_outbox SET state=?,lease_owner=NULL,lease_expires_at=NULL,next_attempt_at=?,last_error_hash=? WHERE order_id=?",(state,(datetime.now(timezone.utc)+timedelta(seconds=delay)).isoformat(),hashlib.sha256(str(error).encode()).hexdigest(),row["order_id"]));self._commit_trusted(db)
 def deliver_entitlement(self,order_id,authority):
  worker="inline-"+uuid.uuid4().hex
  row=self.claim_outbox(worker,order_id=order_id)
  if not row or row["order_id"]!=order_id:
   for _ in range(100):
    with self._db() as db:existing=db.execute("SELECT state,license_id,delivery_receipt FROM entitlement_outbox WHERE order_id=?",(order_id,)).fetchone()
    if existing and existing["state"]=="delivered":return {"license_id":existing["license_id"],"edition":"personal","major_version":1,"device_allowance":2,"delivery_receipt":existing["delivery_receipt"],"authority_id":self.config.authority_id}
    if not existing or existing["state"] not in {"leased","pending"}:break
    time.sleep(.01)
   raise ValueError("entitlement unavailable")
  try:return self.deliver_claimed_outbox(row,authority,worker)
  except Exception as error:self.fail_outbox(row,worker,error);raise
 def _confirm_payment_locked(self,db,oid,proof_id,amount,currency,payer_ref=None,tx_hash=None,actor="system"):
  r=db.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
  if not r:raise KeyError("order")
  if r["state"]=="license_issued":return dict(r)
  if r["state"]!="pending_payment":raise ValueError("invalid state")
  occupied={x[0] for x in db.execute("SELECT sale_ordinal FROM orders WHERE sale_ordinal IS NOT NULL")}|{x[0] for x in db.execute("SELECT reserved_ordinal FROM settlement_intents WHERE state IN('prepared','settled','ambiguous')")};ordinal=next(i for i in range(1,len(occupied)+2) if i not in occupied);expected=(EARLY if ordinal<=EARLY_LIMIT else REGULAR)[r["rail"]];valid=(r["rail"],currency) in {("x402","USDC"),("paypal","USD")};now=datetime.now(timezone.utc)
  if datetime.fromisoformat(r["quote_expires_at"])<=now or amount!=expected or r["quoted_amount_minor"]!=expected or not valid:
   db.execute("UPDATE orders SET state='manual_review',updated_at=? WHERE id=?",(now.isoformat(),oid));self._audit(db,actor,"payment.manual_review",oid,{"provided":amount,"expected":expected,"currency":currency});self._commit_trusted(db);return dict(db.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone())
  try:db.execute("INSERT INTO payment_proofs VALUES(?,?,?,?,?)",(self._hash(proof_id),r["rail"],oid,tx_hash,now.isoformat()))
  except sqlite3.IntegrityError as e:raise ValueError("duplicate payment proof") from e
  db.execute("UPDATE orders SET state='payment_confirmed',sale_ordinal=?,confirmed_at=?,updated_at=?,payer_ref=?,tx_hash=? WHERE id=?",(ordinal,now.isoformat(),now.isoformat(),payer_ref,tx_hash,oid));self._audit(db,actor,"payment.confirmed",oid,{"ordinal":ordinal});self._audit(db,"issuer","entitlement.not_configured",oid,{"rail":r["rail"]});self._commit_trusted(db);return dict(db.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone())
 @_checkpoint_serialized
 def confirm_payment_and_allocate_sale(self,oid,proof_id,amount,currency,payer_ref=None,tx_hash=None,actor="system"):
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db)
   return self._confirm_payment_locked(db,oid,proof_id,amount,currency,payer_ref,tx_hash,actor)
 @staticmethod
 def paypal_minor(value):
  if isinstance(value,(float,int)) or not isinstance(value,str) or re.search(r"[eE]",value):raise ValueError("PayPal amount must be a decimal string")
  try:d=Decimal(value)
  except InvalidOperation as e:raise ValueError("invalid PayPal amount") from e
  if not d.is_finite() or d<=0 or d.as_tuple().exponent < -2:raise ValueError("PayPal amount must have at most two decimal places")
  return int(d.quantize(Decimal("0.01"))*100)
 @_checkpoint_serialized
 def paypal_submit(self,oid,transaction_id):
  tx=transaction_id.strip()
  if not tx or len(tx)>120:raise ValueError("transaction id")
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);r=db.execute("SELECT rail,state FROM orders WHERE id=?",(oid,)).fetchone()
   if not r or r["rail"]!="paypal" or r["state"]!="pending_payment":raise ValueError("PayPal order unavailable")
   try:db.execute("INSERT INTO external_events VALUES(?,?,?,?)",(self._hash("paypal:"+tx),"paypal-claim",oid,self.now()))
   except sqlite3.IntegrityError as e:raise ValueError("duplicate transaction id") from e
   db.execute("UPDATE orders SET payer_ref=?,updated_at=? WHERE id=?",(tx,self.now(),oid));self._audit(db,"buyer","paypal.claim_submitted",oid,{"transaction_hash":self._hash(tx)});self._commit_trusted(db)
 @_checkpoint_serialized
 def paypal_confirm(self,oid,transaction_id,a,actor="admin"):
  if set(a)!={"amount","currency","status","payee_verified"} or a["status"]!="COMPLETED" or a["currency"]!="USD" or a["payee_verified"] is not True:raise ValueError("invalid PayPal attestation")
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);r=db.execute("SELECT payer_ref FROM orders WHERE id=? AND rail='paypal'",(oid,)).fetchone()
   if not r or r[0]!=transaction_id:raise ValueError("transaction does not match submitted claim")
   return self._confirm_payment_locked(db,oid,transaction_id,self.paypal_minor(a["amount"]),"USD",tx_hash=transaction_id,actor=actor)
 def _enqueue_revocation(self,db,entitlement,license_id,action,reason,created_at=None):
  created_at=created_at or self.now();digest=self._outbox_payload_digest(entitlement);identity={"authority_id":self.config.authority_id,"source":entitlement["source"],"source_id":entitlement["source_id"],"payload_digest":digest,"license_id":license_id,"order_id":entitlement["order_id"],"action":action};event_id="gmr_"+hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(",",":")).encode()).hexdigest()
  db.execute("INSERT OR IGNORE INTO revocation_outbox(event_id,order_id,authority_id,source,source_id,entitlement_payload_digest,license_id,action,reason,proof_hash,tx_hash,evidence_hash,created_at,state,next_attempt_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',?)",(event_id,entitlement["order_id"],self.config.authority_id,entitlement["source"],entitlement["source_id"],digest,license_id,action,reason,entitlement["proof_hash"],entitlement["tx_hash"],entitlement["evidence_hash"],created_at,created_at));return dict(db.execute("SELECT * FROM revocation_outbox WHERE order_id=?",(entitlement["order_id"],)).fetchone())
 def _revocation(self,license_id,revoked_at,sequence,reason_code):
  if self.config.signing_key is None:raise RuntimeError("signing key unavailable")
  if reason_code not in {None,"refund","chargeback","fraud","terms_violation","administrative"}:raise ValueError("invalid revocation reason")
  d={"schema_version":1,"assertion_type":"growthmap_license_revocation","product":"growthmap","major_version":1,"license_id":license_id,"revoked_at":revoked_at,"sequence":sequence,"reason_code":reason_code}
  payload=json.dumps(d,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode();d["signature"]=base64.b64encode(self.config.signing_key.sign(b"growthmap-revocation-v1\0"+payload)).decode();return d
 @_checkpoint_serialized
 def admin_transition(self,oid,action,reason_code=None):
  target={"reject":"rejected","refund":"refunded","revoke":"revoked"}.get(action)
  if not target:raise KeyError("action")
  if action!="revoke" and reason_code is not None:raise ValueError("reason is only valid for revocation")
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);r=db.execute("SELECT state,license_id FROM orders WHERE id=?",(oid,)).fetchone()
   if not r:raise KeyError("order")
   if r[0]==target:
    stored=db.execute("SELECT assertion_json FROM revocation_assertions WHERE order_id=?",(oid,)).fetchone() if action in {"refund","revoke"} else None
    event=db.execute("SELECT * FROM revocation_outbox WHERE order_id=?",(oid,)).fetchone() if action in {"refund","revoke"} else None
    self._audit(db,"admin",f"order.{action}.idempotent",oid,{"state":target});self._commit_trusted(db);return {"order_id":oid,"state":target,"idempotent":True,"revocation":json.loads(stored[0]) if stored else None,"revocation_event":dict(event) if event else None}
   if r[0] not in TRANSITIONS[action]:raise ValueError(f"illegal transition {r[0]} -> {target}")
   now=self.now();assertion=None;event=None;entitlement=db.execute("SELECT * FROM entitlement_outbox WHERE order_id=?",(oid,)).fetchone()
   delivered=entitlement and entitlement["state"]=="delivered" and entitlement["license_id"]
   if action in {"refund","revoke"} and delivered:
    reason="refund" if action=="refund" else (reason_code or "administrative");revoked_at=datetime.now(timezone.utc).isoformat().replace("+00:00","Z");assertion=self._revocation(entitlement["license_id"],revoked_at,1,reason);db.execute("INSERT INTO revocation_assertions VALUES(?,?,?,?,?,?,?)",(entitlement["license_id"],oid,1,revoked_at,assertion["reason_code"],json.dumps(assertion,separators=(",",":")),now));event=self._enqueue_revocation(db,entitlement,entitlement["license_id"],action,reason,now)
   elif action=="refund" and entitlement:
    # Cancellation is local-only because no authority license exists. Invalidating
    # an outstanding fence ensures a claimed worker cannot deliver afterward.
    db.execute("UPDATE entitlement_outbox SET state='quarantined',lease_owner=NULL,lease_expires_at=NULL,fencing_version=fencing_version+1,last_error_hash=? WHERE order_id=?",(self._hash("cancelled_by_refund_before_delivery"),oid))
   db.execute("UPDATE orders SET state=?,updated_at=? WHERE id=?",(target,now,oid));self._audit(db,"admin",f"order.{action}",oid,{"from":r[0],"to":target,"license_id":entitlement["license_id"] if delivered else None,"revocation_enqueued":bool(event)});self._commit_trusted(db);return {"order_id":oid,"state":target,"idempotent":False,"revocation":assertion,"revocation_event":event}
 def claim_revocation(self,worker_id,lease_seconds=30,order_id=None):
  now=datetime.now(timezone.utc);expires=(now+timedelta(seconds=lease_seconds)).isoformat()
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);sql="SELECT * FROM revocation_outbox WHERE ((state='pending' AND (next_attempt_at IS NULL OR next_attempt_at<=?)) OR (state='leased' AND lease_expires_at<=?))";params=[now.isoformat(),now.isoformat()]
   if order_id is not None:sql+=" AND order_id=?";params.append(order_id)
   row=db.execute(sql+" ORDER BY created_at LIMIT 1",params).fetchone()
   if not row:db.rollback();return None
   fence=row["fencing_version"]+1;db.execute("UPDATE revocation_outbox SET state='leased',lease_owner=?,lease_expires_at=?,attempt_count=attempt_count+1,fencing_version=? WHERE event_id=? AND fencing_version=?",(worker_id,expires,fence,row["event_id"],row["fencing_version"]));self._commit_trusted(db);return dict(db.execute("SELECT * FROM revocation_outbox WHERE event_id=?",(row["event_id"],)).fetchone())
 def deliver_claimed_revocation(self,row,authority,worker_id):
  if authority.handshake().get("authority_id")!=row["authority_id"] or row["authority_id"]!=self.config.authority_id:raise ValueError("wrong_authority")
  receipt=authority.revoke_external_entitlement(source=row["source"],source_id=row["source_id"],payload_digest=row["entitlement_payload_digest"],authority_id=row["authority_id"],license_id=row["license_id"],action=row["action"],reason=row["reason"],payment_proof=row["proof_hash"],tx_hash=row["tx_hash"],created_at=row["created_at"])
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);fresh=db.execute("SELECT * FROM revocation_outbox WHERE event_id=?",(row["event_id"],)).fetchone()
   if not fresh or fresh["state"]!="leased" or fresh["lease_owner"]!=worker_id or fresh["fencing_version"]!=row["fencing_version"]:db.rollback();raise RuntimeError("revocation lease lost")
   now=self.now();db.execute("UPDATE revocation_outbox SET state='delivered',delivered_at=?,authority_receipt=?,lease_owner=NULL,lease_expires_at=NULL WHERE event_id=?",(now,receipt["revocation_receipt"],row["event_id"]));self._audit(db,"issuer","revocation.delivered",row["order_id"],{"license_id":row["license_id"],"receipt":receipt["revocation_receipt"]});self._commit_trusted(db);return receipt
 def fail_revocation(self,row,worker_id,error,max_attempts=8):
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);fresh=db.execute("SELECT state,lease_owner,fencing_version,attempt_count FROM revocation_outbox WHERE event_id=?",(row["event_id"],)).fetchone()
   if not fresh or fresh["state"]!="leased" or fresh["lease_owner"]!=worker_id or fresh["fencing_version"]!=row["fencing_version"]:db.rollback();return
   state="quarantined" if fresh["attempt_count"]>=max_attempts else "pending";delay=min(3600,2**min(fresh["attempt_count"],10));db.execute("UPDATE revocation_outbox SET state=?,lease_owner=NULL,lease_expires_at=NULL,next_attempt_at=?,last_error_hash=? WHERE event_id=?",(state,(datetime.now(timezone.utc)+timedelta(seconds=delay)).isoformat(),self._hash(str(error)),row["event_id"]));self._commit_trusted(db)
 def deliver_revocation(self,order_id,authority):
  worker="revoke-inline-"+uuid.uuid4().hex;row=self.claim_revocation(worker,order_id=order_id)
  if not row:
   with self._db() as db:existing=db.execute("SELECT authority_receipt FROM revocation_outbox WHERE order_id=? AND state='delivered'",(order_id,)).fetchone()
   if existing:return {"revocation_receipt":existing["authority_receipt"]}
   raise ValueError("revocation unavailable")
  try:return self.deliver_claimed_revocation(row,authority,worker)
  except Exception as error:self.fail_revocation(row,worker,error);raise
 @_checkpoint_serialized
 def admin_list_orders(self):
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);rows=[dict(r) for r in db.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 200")];db.rollback();return rows
 def authenticated_entitlement(self,order_id,code):
  """Body-only recovery authentication; callers must return a generic failure."""
  if not isinstance(code,str) or len(code)>256:return None
  with self._checkpoint_lock:
   with self._db() as db:
    db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);r=db.execute("SELECT id,state,license_id FROM orders WHERE id=? AND recovery_code_hash=?",(order_id,self._hash(code))).fetchone();db.rollback()
  return dict(r) if r and r["state"]=="license_issued" and r["license_id"] else None
 def pending_outbox_orders(self):
  with self._db() as db:return [r[0] for r in db.execute("SELECT order_id FROM entitlement_outbox WHERE state='pending' ORDER BY created_at")]
 @_checkpoint_serialized
 @_checkpoint_serialized
 def verify_audit(self):
  prev="0"*64
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");self._assert_terminal_trust(db);rows=db.execute("SELECT * FROM audit_events ORDER BY seq").fetchall();db.rollback()
  for r in rows:
   expected=self._hash("|".join((prev,r["at"],r["actor"],r["operation"],r["object_id"],r["data_hash"])))
   if expected!=r["chain_hash"] or r["previous_hash"]!=prev:return False
   prev=r["chain_hash"]
  return True
