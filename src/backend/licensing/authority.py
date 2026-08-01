"""Payment-independent GrowthMap license issuance and activation authority.

This module is deliberately not wired to a public deployment. Authentication, TLS, HSM/KMS
and a rollback-resistant database are production deployment gates. The signing key is injected
as a file and is never generated or stored by product code.
"""
from __future__ import annotations
import base64, hashlib, hmac, json, re, sqlite3, threading, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

LICENSE_ID_RE=re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
DEVICE_KEY_DOMAIN=b"growthmap-activation-request-v1\0"
CERT_DOMAIN=b"growthmap-activation-certificate-v2\0"

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
    def __init__(self, database: Path, private_key_file: Path|None, *, now=lambda: datetime.now(timezone.utc)):
        if private_key_file is None: raise RuntimeError("license_signing_key_required")
        try: key=serialization.load_pem_private_key(Path(private_key_file).read_bytes(),password=None)
        except Exception as error: raise RuntimeError("license_signing_key_unavailable") from error
        if not isinstance(key,Ed25519PrivateKey): raise RuntimeError("license_signing_key_must_be_ed25519")
        self.key,self.database,self.now=key,Path(database),now;self._lock=threading.RLock()
        self.database.parent.mkdir(parents=True,exist_ok=True)
        with self._connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS licenses(
              license_id TEXT PRIMARY KEY, edition TEXT NOT NULL, major_version INTEGER NOT NULL,
              seat_limit INTEGER NOT NULL CHECK(seat_limit BETWEEN 1 AND 2), issued_at TEXT NOT NULL,
              expires_at TEXT, revoked_at TEXT, check_in_days INTEGER NOT NULL CHECK(check_in_days BETWEEN 1 AND 365));
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
    def activate(self, *, license_id: str, device_public_key: str, nonce: str, proof: str) -> dict[str,Any]:
        device_id=device_identifier(device_public_key);raw=base64.b64decode(device_public_key);sig=base64.b64decode(proof,validate=True)
        if not isinstance(nonce,str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}",nonce): raise ValueError("invalid_nonce")
        try: Ed25519PublicKey.from_public_bytes(raw).verify(sig,activation_challenge(license_id,device_public_key,nonce))
        except Exception as error: raise ValueError("device_proof_invalid") from error
        with self._lock,self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            lic=db.execute("SELECT * FROM licenses WHERE license_id=?",(license_id,)).fetchone()
            if not lic: db.rollback();raise ValueError("license_not_found")
            instant=self.now();
            if lic["revoked_at"]: db.rollback();raise ValueError("license_revoked")
            if lic["expires_at"] and datetime.fromisoformat(lic["expires_at"].replace("Z","+00:00"))<=instant: db.rollback();raise ValueError("license_expired")
            nonce_hash=hashlib.sha256(nonce.encode()).hexdigest();proof_hash=hashlib.sha256(proof.encode()).hexdigest()
            nonce_digest=hashlib.sha256((license_id+"\0"+device_id+"\0"+nonce_hash+"\0"+proof_hash).encode()).hexdigest()
            request=db.execute("SELECT status,certificate_json FROM activation_requests WHERE request_digest=?",(nonce_digest,)).fetchone()
            if request:
                if request["status"]=="active" and request["certificate_json"]:
                    self._audit(db,"activation_retrieved",license_id,device_id);db.commit();return json.loads(request["certificate_json"])
                db.rollback();raise ValueError("activation_nonce_consumed")
            old=db.execute("SELECT certificate_json,deactivated_at,activation_nonce_digest FROM activations WHERE license_id=? AND device_id=?",(license_id,device_id)).fetchone()
            count=db.execute("SELECT count(*) FROM activations WHERE license_id=? AND deactivated_at IS NULL",(license_id,)).fetchone()[0]
            if (not old or old["deactivated_at"] is not None) and count>=lic["seat_limit"]: self._audit(db,"activation_denied_seat_limit",license_id,device_id);db.commit();raise ValueError("seat_limit_reached")
            activated=utc(self.now());activation_id="gma_"+uuid.uuid4().hex
            cert={"schema_version":2,"certificate_type":"growthmap_device_activation","product":"growthmap","edition":lic["edition"],"license_id":license_id,"activation_id":activation_id,"major_version":lic["major_version"],"device_allowance":lic["seat_limit"],"device_id":device_id,"device_public_key":device_public_key,"issued_at":activated,"expires_at":lic["expires_at"],"revoked_at":None,"max_active_projects":None,"next_check_in_at":utc(instant+timedelta(days=lic["check_in_days"]))}
            cert["signature"]=base64.b64encode(self.key.sign(CERT_DOMAIN+canonical(cert))).decode()
            cert_json=json.dumps(cert,separators=(",",":"))
            db.execute("INSERT INTO activation_requests VALUES(?,?,?,?,?,?,?,?,?)",(nonce_digest,license_id,device_id,nonce_hash,proof_hash,activated,"active",activation_id,cert_json))
            if old: db.execute("UPDATE activations SET activation_id=?,device_public_key=?,activated_at=?,deactivated_at=NULL,certificate_json=?,activation_nonce_digest=? WHERE license_id=? AND device_id=?",(activation_id,device_public_key,activated,cert_json,nonce_digest,license_id,device_id))
            else: db.execute("INSERT INTO activations VALUES(?,?,?,?,?,?,?,?)",(activation_id,license_id,device_id,device_public_key,activated,None,cert_json,nonce_digest))
            self._audit(db,"device_activated",license_id,device_id);db.commit();return cert
    def deactivate(self, *, license_id: str, device_id: str, reason="user_recovery") -> bool:
        """Authority-authenticated caller boundary: deployment must authenticate license owner/admin."""
        with self._lock,self._connect() as db:
            db.execute("BEGIN IMMEDIATE");row=db.execute("SELECT deactivated_at FROM activations WHERE license_id=? AND device_id=?",(license_id,device_id)).fetchone()
            if not row or row["deactivated_at"] is not None: db.commit();return False
            db.execute("UPDATE activations SET deactivated_at=? WHERE license_id=? AND device_id=?",(utc(self.now()),license_id,device_id));db.execute("UPDATE activation_requests SET status='consumed' WHERE license_id=? AND device_id=? AND status='active'",(license_id,device_id));self._audit(db,"device_deactivated",license_id,device_id,json.dumps({"reason":reason}));db.commit();return True
