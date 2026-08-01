"""Payment-independent GrowthMap license issuance and activation authority.

This module is deliberately not wired to a public deployment. Authentication, TLS, HSM/KMS
and a rollback-resistant database are production deployment gates. The signing key is injected
as a file and is never generated or stored by product code.
"""
from __future__ import annotations
import base64, hashlib, hmac, json, re, secrets, sqlite3, threading, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from .signer_ceremony import DOMAIN as CEREMONY_DOMAIN, PURPOSE as CEREMONY_PURPOSE, OfflineFixtureMonotonicAnchor, validate_anchor_claim, validate as validate_ceremony
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

LICENSE_ID_RE=re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
DEVICE_KEY_DOMAIN=b"growthmap-activation-request-v1\0"
CERT_DOMAIN=b"growthmap-activation-certificate-v2\0"
# SQLite WAL bootstrap can report BUSY before its connection timeout applies to
# PRAGMA journal_mode. Serialize schema bootstrap within one service process;
# SQLite's own busy timeout remains the cross-process boundary.
_SCHEMA_BOOTSTRAP_LOCK=threading.RLock()

def canonical(value: dict[str,Any]) -> bytes:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()

def utc(value: datetime|None=None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def device_identifier(public_key_b64: str) -> str:
    raw=base64.b64decode(public_key_b64,validate=True)
    if len(raw)!=32: raise ValueError("invalid_device_public_key")
    Ed25519PublicKey.from_public_bytes(raw)
    return "gmdev_"+hashlib.sha256(raw).hexdigest()

def activation_challenge(license_id: str, public_key_b64: str, nonce: str) -> bytes:
    return DEVICE_KEY_DOMAIN+canonical({"license_id":license_id,"device_public_key":public_key_b64,"nonce":nonce})

class LicenseAuthority:
    """SQLite seat ledger with transactional unique constraints and idempotent certificates."""
    def __init__(self, database: Path, private_key_file: Path|None, *, now=lambda: datetime.now(timezone.utc), authority_id="growthmap-authority-primary"):
        """Explicit legacy isolated-file candidate seam; production uses from_external_signer."""
        if private_key_file is None:raise RuntimeError("license_signing_key_required")
        try:key=serialization.load_pem_private_key(Path(private_key_file).read_bytes(),password=None)
        except Exception as error:raise RuntimeError("license_signing_key_unavailable") from error
        if not isinstance(key,Ed25519PrivateKey):raise RuntimeError("license_signing_key_must_be_ed25519")
        public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        descriptor={"schema_version":1,"purpose":CEREMONY_PURPOSE,"domain":CEREMONY_DOMAIN,"algorithm":"Ed25519","authority_id":authority_id,"key_id":"isolated-fixture-key","generation":1,"activated_at":"1970-01-01T00:00:00Z","predecessor_generation":None,"public_key_sha256":hashlib.sha256(public).hexdigest(),"provider_attestation_id":"offline-fixture"}
        self._construct(database,key,descriptor,public,OfflineFixtureMonotonicAnchor(),now)

    @classmethod
    def from_file_key_for_isolated_tests(cls,database:Path,private_key_file:Path,**kwargs):return cls(database,private_key_file,**kwargs)

    @classmethod
    def from_external_signer(cls,database:Path,*,signer,ceremony_descriptor,reviewed_public_key:bytes,generation_anchor,now=lambda:datetime.now(timezone.utc)):
        instance=cls.__new__(cls);instance._construct(database,signer,ceremony_descriptor,reviewed_public_key,generation_anchor,now);return instance

    def _construct(self,database,signer,descriptor,reviewed_public_key,anchor,now):
        if not callable(getattr(signer,"sign",None)) or not callable(getattr(anchor,"read",None)) or not callable(getattr(anchor,"compare_and_advance",None)):raise RuntimeError("signer_configuration_invalid")
        try:ceremony,public,descriptor_bytes=validate_ceremony(descriptor,reviewed_public_key,now())
        except RuntimeError:raise
        except Exception:raise RuntimeError("signer_ceremony_invalid") from None
        self.signer,self.public_key,self.ceremony,self._ceremony_bytes,self.anchor=signer,public,ceremony,descriptor_bytes,anchor
        self.database,self.now,self.authority_id=Path(database),now,ceremony["authority_id"];self._lock=threading.RLock()
        self.database.parent.mkdir(parents=True,exist_ok=True)
        with _SCHEMA_BOOTSTRAP_LOCK,self._connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS signer_ceremonies(
              generation INTEGER PRIMARY KEY CHECK(generation>0), key_id TEXT NOT NULL,
              descriptor_json TEXT NOT NULL UNIQUE, public_key_sha256 TEXT NOT NULL,
              provider_attestation_id TEXT NOT NULL, pinned_at TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS signer_ceremony_no_update BEFORE UPDATE ON signer_ceremonies BEGIN SELECT RAISE(ABORT,'signer ceremony is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS signer_ceremony_no_delete BEFORE DELETE ON signer_ceremonies BEGIN SELECT RAISE(ABORT,'signer ceremony is immutable'); END;
            CREATE TABLE IF NOT EXISTS licenses(
              license_id TEXT PRIMARY KEY, edition TEXT NOT NULL, major_version INTEGER NOT NULL,
              seat_limit INTEGER NOT NULL CHECK(seat_limit BETWEEN 1 AND 2), issued_at TEXT NOT NULL,
              expires_at TEXT, revoked_at TEXT, check_in_days INTEGER NOT NULL CHECK(check_in_days BETWEEN 1 AND 365));
            CREATE TABLE IF NOT EXISTS external_entitlements(
              source TEXT NOT NULL, source_id TEXT NOT NULL, license_id TEXT NOT NULL UNIQUE REFERENCES licenses(license_id),
              created_at TEXT NOT NULL, payload_digest TEXT, authority_id TEXT,
              PRIMARY KEY(source,source_id));
            CREATE TRIGGER IF NOT EXISTS external_entitlement_no_update BEFORE UPDATE ON external_entitlements
              BEGIN SELECT RAISE(ABORT,'external entitlement is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS external_entitlement_no_delete BEFORE DELETE ON external_entitlements
              BEGIN SELECT RAISE(ABORT,'external entitlement is immutable'); END;
            CREATE TABLE IF NOT EXISTS external_revocations(
              source TEXT NOT NULL, source_id TEXT NOT NULL, authority_id TEXT NOT NULL,
              payload_digest TEXT NOT NULL, license_id TEXT NOT NULL REFERENCES licenses(license_id),
              action TEXT NOT NULL, reason TEXT NOT NULL, payment_proof TEXT NOT NULL, tx_hash TEXT NOT NULL,
              event_created_at TEXT NOT NULL, revoked_at TEXT NOT NULL, request_digest TEXT NOT NULL,
              receipt TEXT NOT NULL UNIQUE, PRIMARY KEY(source,source_id));
            CREATE TRIGGER IF NOT EXISTS external_revocation_no_update BEFORE UPDATE ON external_revocations
              BEGIN SELECT RAISE(ABORT,'external revocation is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS external_revocation_no_delete BEFORE DELETE ON external_revocations
              BEGIN SELECT RAISE(ABORT,'external revocation is immutable'); END;
            CREATE TABLE IF NOT EXISTS activation_challenges(
              challenge_id TEXT PRIMARY KEY, license_id TEXT NOT NULL REFERENCES licenses(license_id),
              device_id TEXT NOT NULL, device_public_key TEXT NOT NULL, nonce TEXT NOT NULL UNIQUE,
              issued_at TEXT NOT NULL, expires_at TEXT NOT NULL, consumed_at TEXT,
              request_digest TEXT, certificate_json TEXT);
            CREATE TABLE IF NOT EXISTS activations(
              activation_id TEXT PRIMARY KEY, license_id TEXT NOT NULL REFERENCES licenses(license_id),
              device_id TEXT NOT NULL, device_public_key TEXT NOT NULL, activated_at TEXT NOT NULL,
              deactivated_at TEXT, certificate_json TEXT NOT NULL, activation_nonce_digest TEXT NOT NULL,
              UNIQUE(license_id,device_id));
            CREATE UNIQUE INDEX IF NOT EXISTS active_device_once ON activations(license_id,device_id) WHERE deactivated_at IS NULL;
            CREATE TABLE IF NOT EXISTS activation_requests(
              request_digest TEXT PRIMARY KEY, license_id TEXT NOT NULL REFERENCES licenses(license_id),
              device_id TEXT NOT NULL, nonce_digest TEXT NOT NULL, proof_digest TEXT NOT NULL,
              first_seen_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','consumed')),
              activation_id TEXT, certificate_json TEXT);
            CREATE TABLE IF NOT EXISTS audit_log(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, event TEXT NOT NULL,
              license_id TEXT NOT NULL, device_id TEXT, detail TEXT NOT NULL);
            """)
            # Reject locally impossible/stale rotations before touching the external
            # monotonic source. The later pin is still a separate-system operation.
            self._check_ceremony_transition(db)
        generation=ceremony["generation"];digest=hashlib.sha256(descriptor_bytes).hexdigest();anchor_failed=False
        previous_digest=None
        if generation>1:
            with self._connect() as db:
                previous=db.execute("SELECT descriptor_json FROM signer_ceremonies WHERE generation=?",(generation-1,)).fetchone()
            if not previous:raise RuntimeError("signer_predecessor_invalid")
            previous_digest=hashlib.sha256(previous["descriptor_json"].encode()).hexdigest()
        expected={"generation":generation-1,"ceremony_sha256":previous_digest};claimed={"generation":generation,"ceremony_sha256":digest}
        try:anchored=validate_anchor_claim(anchor.compare_and_advance(expected,claimed),allow_zero=False)
        except Exception:anchor_failed=True;anchored=None
        if anchor_failed or anchored!=claimed:raise RuntimeError("signer_generation_anchor_unavailable_or_conflicting") from None
        with self._connect() as db:self._pin_ceremony(db)
        self._assert_signer_state()
    def _check_ceremony_transition(self,db):
        latest=db.execute("SELECT generation,descriptor_json FROM signer_ceremonies ORDER BY generation DESC LIMIT 1").fetchone();g=self.ceremony["generation"];encoded=self._ceremony_bytes.decode()
        if latest:
            if g<latest["generation"] or g>latest["generation"]+1:raise RuntimeError("signer_generation_invalid")
            if g==latest["generation"]:
                if not hmac.compare_digest(latest["descriptor_json"],encoded):raise RuntimeError("signer_ceremony_conflict")
                return False
            if self.ceremony["predecessor_generation"]!=latest["generation"]:raise RuntimeError("signer_predecessor_invalid")
        elif g!=1:raise RuntimeError("signer_initial_generation_invalid")
        return True
    def _pin_ceremony(self,db):
        db.execute("BEGIN IMMEDIATE")
        try:
            should_insert=self._check_ceremony_transition(db)
            if should_insert:
                c=self.ceremony;db.execute("INSERT INTO signer_ceremonies VALUES(?,?,?,?,?,?)",(c["generation"],c["key_id"],self._ceremony_bytes.decode(),c["public_key_sha256"],c["provider_attestation_id"],utc(self.now())))
            db.commit()
        except Exception:db.rollback();raise
    def _assert_signer_state(self):
        anchor_failed=False
        try:anchored=validate_anchor_claim(self.anchor.read(),allow_zero=False)
        except Exception:anchor_failed=True;anchored=None
        if anchor_failed:raise RuntimeError("signer_state_unavailable") from None
        expected={"generation":self.ceremony["generation"],"ceremony_sha256":hashlib.sha256(self._ceremony_bytes).hexdigest()}
        if anchored!=expected:raise RuntimeError("signer_state_conflict")
        with self._connect() as db:latest=db.execute("SELECT generation,descriptor_json FROM signer_ceremonies ORDER BY generation DESC LIMIT 1").fetchone()
        if not latest or latest["generation"]!=self.ceremony["generation"] or not hmac.compare_digest(latest["descriptor_json"],self._ceremony_bytes.decode()):raise RuntimeError("signer_state_conflict")
    def _sign_verified(self,message:bytes)->bytes:
        self._assert_signer_state();provider_failed=False
        try:signature=self.signer.sign(message)
        except Exception:provider_failed=True;signature=None
        if provider_failed:raise RuntimeError("license_signing_unavailable") from None
        if not isinstance(signature,bytes) or len(signature)!=64:raise RuntimeError("license_signing_failed")
        try:self.public_key.verify(signature,message)
        except Exception:raise RuntimeError("license_signing_failed") from None
        return signature
    def _connect(self):
        db=sqlite3.connect(self.database,timeout=30,isolation_level=None);db.row_factory=sqlite3.Row;db.execute("PRAGMA foreign_keys=ON");return db
    def _audit(self,db,event,license_id,device_id=None,detail="{}"):
        db.execute("INSERT INTO audit_log(at,event,license_id,device_id,detail) VALUES(?,?,?,?,?)",(utc(self.now()),event,license_id,device_id,detail))
    def create_license(self, *, license_id: str|None=None, edition="personal", major_version=1, seat_limit=2, expires_at=None, check_in_days=30):
        license_id=license_id or "gm_"+uuid.uuid4().hex
        if not LICENSE_ID_RE.fullmatch(license_id) or edition not in {"personal","pro","studio"} or isinstance(major_version,bool) or major_version<1 or seat_limit not in {1,2}: raise ValueError("invalid_license")
        issued=self.now(); values=(license_id,edition,major_version,seat_limit,utc(issued),expires_at,None,check_in_days)
        with self._connect() as db:
            try: db.execute("INSERT INTO licenses VALUES(?,?,?,?,?,?,?,?)",values)
            except sqlite3.IntegrityError as error: raise ValueError("license_exists") from error
            self._audit(db,"license_created",license_id,detail=json.dumps({"seat_limit":seat_limit}))
        return {"license_id":license_id,"edition":edition,"major_version":major_version,"device_allowance":seat_limit}
    def handshake(self) -> dict[str,Any]:
        self._assert_signer_state()
        return {"authority_id":self.authority_id,"key_id":self.ceremony["key_id"],"generation":self.ceremony["generation"],"public_key_sha256":self.ceremony["public_key_sha256"],"attestation":self.ceremony["provider_attestation_id"]}
    def create_external_entitlement(self, *, source: str, source_id: str, payload_digest: str, authority_id: str, edition="personal", major_version=1, seat_limit=2) -> dict[str,Any]:
        """Idempotent inbox for a durable external payment source.

        Payment and authority databases are deliberately separate: callers persist an
        outbox first, then retry this operation.  The source reference, not a caller
        supplied license id, is the exactly-once identity boundary.
        """
        if authority_id!=self.authority_id:raise ValueError("wrong_authority")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}",source) or not re.fullmatch(r"[a-f0-9]{64}",source_id) or not re.fullmatch(r"[a-f0-9]{64}",payload_digest): raise ValueError("invalid_external_source")
        if edition not in {"personal","pro","studio"} or major_version != 1 or seat_limit not in {1,2}: raise ValueError("invalid_license")
        with self._lock,self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior=db.execute("SELECT l.*,e.payload_digest,e.authority_id FROM external_entitlements e JOIN licenses l USING(license_id) WHERE e.source=? AND e.source_id=?",(source,source_id)).fetchone()
            if prior:
                if prior["payload_digest"]!=payload_digest or prior["authority_id"]!=authority_id:db.rollback();raise ValueError("external_entitlement_contradiction")
                receipt=hashlib.sha256(canonical({"authority_id":authority_id,"source":source,"source_id":source_id,"payload_digest":payload_digest,"license_id":prior["license_id"]})).hexdigest();db.commit();return {"license_id":prior["license_id"],"edition":prior["edition"],"major_version":prior["major_version"],"device_allowance":prior["seat_limit"],"delivery_receipt":receipt,"authority_id":authority_id}
            license_id="gm_"+uuid.uuid4().hex;issued=utc(self.now())
            db.execute("INSERT INTO licenses VALUES(?,?,?,?,?,?,?,?)",(license_id,edition,major_version,seat_limit,issued,None,None,30))
            db.execute("INSERT INTO external_entitlements VALUES(?,?,?,?,?,?)",(source,source_id,license_id,issued,payload_digest,authority_id))
            receipt=hashlib.sha256(canonical({"authority_id":authority_id,"source":source,"source_id":source_id,"payload_digest":payload_digest,"license_id":license_id})).hexdigest()
            self._audit(db,"external_entitlement_created",license_id,detail=json.dumps({"source":source,"source_id":source_id,"payload_digest":payload_digest}));db.commit()
            return {"license_id":license_id,"edition":edition,"major_version":major_version,"device_allowance":seat_limit,"delivery_receipt":receipt,"authority_id":authority_id}
    def issue_activation_challenge(self, *, license_id: str, device_public_key: str, ttl_seconds=300) -> dict[str,str]:
        device_id=device_identifier(device_public_key);now=self.now();nonce=secrets.token_urlsafe(24);challenge_id="gmc_"+uuid.uuid4().hex
        with self._lock,self._connect() as db:
            db.execute("BEGIN IMMEDIATE");lic=db.execute("SELECT revoked_at FROM licenses WHERE license_id=?",(license_id,)).fetchone()
            if not lic or lic["revoked_at"]:db.rollback();raise ValueError("license_unavailable")
            db.execute("UPDATE activation_challenges SET consumed_at=? WHERE license_id=? AND device_id=? AND consumed_at IS NULL",(utc(now),license_id,device_id))
            db.execute("INSERT INTO activation_challenges VALUES(?,?,?,?,?,?,?,?,?,?)",(challenge_id,license_id,device_id,device_public_key,nonce,utc(now),utc(now+timedelta(seconds=ttl_seconds)),None,None,None));db.commit()
        return {"challenge_id":challenge_id,"nonce":nonce,"license_id":license_id,"device_public_key":device_public_key}
    def _activate_in_transaction(self, db, license_id: str, device_public_key: str, nonce: str, proof: str, now: datetime) -> dict[str,Any]:
        """Activate using the caller's writer transaction; never commit or roll back here."""
        device_id=device_identifier(device_public_key)
        if not isinstance(nonce,str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}",nonce):raise ValueError("invalid_nonce")
        try:
            raw=base64.b64decode(device_public_key,validate=True);sig=base64.b64decode(proof,validate=True)
            Ed25519PublicKey.from_public_bytes(raw).verify(sig,activation_challenge(license_id,device_public_key,nonce))
        except Exception as error:raise ValueError("device_proof_invalid") from error
        lic=db.execute("SELECT * FROM licenses WHERE license_id=?",(license_id,)).fetchone()
        if not lic:raise ValueError("license_not_found")
        if lic["revoked_at"]:raise ValueError("license_revoked")
        if lic["expires_at"] and datetime.fromisoformat(lic["expires_at"].replace("Z","+00:00"))<=now:raise ValueError("license_expired")
        nonce_hash=hashlib.sha256(nonce.encode()).hexdigest();proof_hash=hashlib.sha256(proof.encode()).hexdigest()
        request_digest=hashlib.sha256((license_id+"\0"+device_id+"\0"+nonce_hash+"\0"+proof_hash).encode()).hexdigest()
        request=db.execute("SELECT status,certificate_json FROM activation_requests WHERE request_digest=?",(request_digest,)).fetchone()
        if request:
            if request["status"]=="active" and request["certificate_json"]:
                self._audit(db,"activation_retrieved",license_id,device_id);return json.loads(request["certificate_json"])
            raise ValueError("activation_nonce_consumed")
        old=db.execute("SELECT deactivated_at FROM activations WHERE license_id=? AND device_id=?",(license_id,device_id)).fetchone()
        count=db.execute("SELECT count(*) FROM activations WHERE license_id=? AND deactivated_at IS NULL",(license_id,)).fetchone()[0]
        if (not old or old["deactivated_at"] is not None) and count>=lic["seat_limit"]:raise ValueError("seat_limit_reached")
        activated=utc(now);activation_id="gma_"+uuid.uuid4().hex
        cert={"schema_version":2,"certificate_type":"growthmap_device_activation","product":"growthmap","edition":lic["edition"],"license_id":license_id,"activation_id":activation_id,"major_version":lic["major_version"],"device_allowance":lic["seat_limit"],"device_id":device_id,"device_public_key":device_public_key,"issued_at":activated,"expires_at":lic["expires_at"],"revoked_at":None,"max_active_projects":None,"next_check_in_at":utc(now+timedelta(days=lic["check_in_days"]))}
        cert["signature"]=base64.b64encode(self._sign_verified(CERT_DOMAIN+canonical(cert))).decode();cert_json=json.dumps(cert,separators=(",",":"))
        try:db.execute("INSERT INTO activation_requests VALUES(?,?,?,?,?,?,?,?,?)",(request_digest,license_id,device_id,nonce_hash,proof_hash,activated,"active",activation_id,cert_json))
        except sqlite3.IntegrityError as error:raise ValueError("activation_nonce_consumed") from error
        if old:db.execute("UPDATE activations SET activation_id=?,device_public_key=?,activated_at=?,deactivated_at=NULL,certificate_json=?,activation_nonce_digest=? WHERE license_id=? AND device_id=?",(activation_id,device_public_key,activated,cert_json,request_digest,license_id,device_id))
        else:db.execute("INSERT INTO activations VALUES(?,?,?,?,?,?,?,?)",(activation_id,license_id,device_id,device_public_key,activated,None,cert_json,request_digest))
        self._audit(db,"device_activated",license_id,device_id);return cert

    def activate_challenge(self, *, challenge_id: str, proof: str) -> dict[str,Any]:
        with self._lock,self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row=db.execute("SELECT * FROM activation_challenges WHERE challenge_id=?",(challenge_id,)).fetchone()
                if not row:raise ValueError("challenge_unavailable")
                lic=db.execute("SELECT revoked_at FROM licenses WHERE license_id=?",(row["license_id"],)).fetchone()
                if not lic or lic["revoked_at"]:raise ValueError("license_revoked")
                if row["consumed_at"]:
                    proof_digest=hashlib.sha256(proof.encode()).hexdigest()
                    if row["certificate_json"] and hmac.compare_digest(row["request_digest"] or "",proof_digest):
                        cert=json.loads(row["certificate_json"]);db.commit();return cert
                    raise ValueError("challenge_consumed")
                now=self.now()
                if datetime.fromisoformat(row["expires_at"].replace("Z","+00:00"))<=now:raise ValueError("challenge_expired")
                cert=self._activate_in_transaction(db,row["license_id"],row["device_public_key"],row["nonce"],proof,now)
                db.execute("UPDATE activation_challenges SET consumed_at=?,request_digest=?,certificate_json=? WHERE challenge_id=?",(utc(now),hashlib.sha256(proof.encode()).hexdigest(),json.dumps(cert,separators=(",",":")),challenge_id))
                db.commit();return cert
            except Exception:
                db.rollback();raise

    def activate(self, *, license_id: str, device_public_key: str, nonce: str, proof: str) -> dict[str,Any]:
        with self._lock,self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:cert=self._activate_in_transaction(db,license_id,device_public_key,nonce,proof,self.now());db.commit();return cert
            except Exception:db.rollback();raise
    def revoke_external_entitlement(self, *, source: str, source_id: str, payload_digest: str, authority_id: str, license_id: str|None=None, action="revoke", reason="administrative", payment_proof="legacy", tx_hash="legacy", created_at="legacy") -> dict[str,str]:
        if authority_id!=self.authority_id:raise ValueError("wrong_authority")
        if action not in {"refund","revoke"}:raise ValueError("invalid_revocation_action")
        if reason not in {"refund","chargeback","fraud","terms_violation","administrative"} or len(reason)>32:raise ValueError("invalid_revocation_reason")
        if (not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}",source or "") or not re.fullmatch(r"[a-f0-9]{64}",source_id or "") or not re.fullmatch(r"[a-f0-9]{64}",payload_digest or "") or not isinstance(license_id,str) or not LICENSE_ID_RE.fullmatch(license_id) or not re.fullmatch(r"[a-f0-9]{64}",payment_proof or "") or not re.fullmatch(r"0x[a-fA-F0-9]{64}",tx_hash or "")):raise ValueError("invalid_revocation_evidence")
        request={"authority_id":authority_id,"source":source,"source_id":source_id,"payload_digest":payload_digest,"license_id":license_id,"action":action,"reason":reason,"payment_proof":payment_proof,"tx_hash":tx_hash,"created_at":created_at};request_digest=hashlib.sha256(canonical(request)).hexdigest()
        with self._lock,self._connect() as db:
            db.execute("BEGIN IMMEDIATE");row=db.execute("SELECT license_id,payload_digest FROM external_entitlements WHERE source=? AND source_id=?",(source,source_id)).fetchone()
            if not row or row["payload_digest"]!=payload_digest or row["license_id"]!=license_id:db.rollback();raise ValueError("external_entitlement_unavailable")
            # Replay lookup deliberately precedes freshness: durable outbox retries after
            # an Authority commit/payment acknowledgement crash return the same receipt.
            prior=db.execute("SELECT request_digest,receipt,revoked_at,license_id FROM external_revocations WHERE source=? AND source_id=?",(source,source_id)).fetchone()
            if prior:
                if prior["request_digest"]!=request_digest:db.rollback();raise ValueError("external_revocation_contradiction")
                db.commit();return {"license_id":prior["license_id"],"revoked_at":prior["revoked_at"],"revocation_receipt":prior["receipt"],"authority_id":authority_id}
            try:
                event_time=datetime.fromisoformat(created_at.replace("Z","+00:00"))
                if event_time.tzinfo is None:raise ValueError
                event_time=event_time.astimezone(timezone.utc);clock=self.now()
                if not isinstance(clock,datetime) or clock.tzinfo is None:raise RuntimeError("invalid_authority_clock")
                now=clock.astimezone(timezone.utc)
                if event_time<now-timedelta(hours=24) or event_time>now+timedelta(minutes=5):raise ValueError
            except RuntimeError:
                db.rollback();raise
            except (AttributeError,TypeError,ValueError) as error:db.rollback();raise ValueError("invalid_revocation_created_at") from error
            revoked_at=utc(now);receipt=hashlib.sha256(canonical({"authority_id":authority_id,"request_digest":request_digest,"license_id":row["license_id"],"revoked_at":revoked_at})).hexdigest()
            db.execute("UPDATE licenses SET revoked_at=COALESCE(revoked_at,?) WHERE license_id=?",(revoked_at,row["license_id"]));db.execute("UPDATE activations SET deactivated_at=COALESCE(deactivated_at,?) WHERE license_id=?",(revoked_at,row["license_id"]));db.execute("UPDATE activation_requests SET status='consumed' WHERE license_id=?",(row["license_id"],));db.execute("UPDATE activation_challenges SET consumed_at=COALESCE(consumed_at,?) WHERE license_id=?",(revoked_at,row["license_id"]));db.execute("INSERT INTO external_revocations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(source,source_id,authority_id,payload_digest,row["license_id"],action,reason,payment_proof,tx_hash,created_at,revoked_at,request_digest,receipt));self._audit(db,"external_entitlement_revoked",row["license_id"],detail=json.dumps({"action":action,"reason":reason,"receipt":receipt}));db.commit();return {"license_id":row["license_id"],"revoked_at":revoked_at,"revocation_receipt":receipt,"authority_id":authority_id}
    def deactivate(self, *, license_id: str, device_id: str, reason="user_recovery") -> bool:
        """Authority-authenticated caller boundary: deployment must authenticate license owner/admin."""
        with self._lock,self._connect() as db:
            db.execute("BEGIN IMMEDIATE");row=db.execute("SELECT deactivated_at FROM activations WHERE license_id=? AND device_id=?",(license_id,device_id)).fetchone()
            if not row or row["deactivated_at"] is not None: db.commit();return False
            db.execute("UPDATE activations SET deactivated_at=? WHERE license_id=? AND device_id=?",(utc(self.now()),license_id,device_id));db.execute("UPDATE activation_requests SET status='consumed' WHERE license_id=? AND device_id=? AND status='active'",(license_id,device_id));self._audit(db,"device_deactivated",license_id,device_id,json.dumps({"reason":reason}));db.commit();return True
