"""GrowthMap payments v1 candidate core.

Separate SQLite ledger/issuer. No desktop DB access and no production facilitator contract.
"""
from __future__ import annotations
import base64, hashlib, json, re, secrets, sqlite3, threading, uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BASE_NETWORK="eip155:8453"
BASE_USDC="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
EARLY_LIMIT=50
EARLY_MICRO=10_000_000
REGULAR_MICRO=29_000_000
STATES={"pending_payment","payment_confirmed","license_issued","manual_review","rejected","expired","refunded","revoked"}

class Facilitator(Protocol):
    def verify(self, signature: str, requirements: dict[str, Any]) -> dict[str, Any]: ...
    def settle(self, signature: str, requirements: dict[str, Any]) -> dict[str, Any]: ...

@dataclass(frozen=True)
class Config:
    db_path: Path
    recipient: str
    admin_secret_hash: str
    signing_key: Ed25519PrivateKey | None
    quote_seconds: int=300
    production: bool=False
    def validate(self) -> None:
        if self.production and (not self.admin_secret_hash or self.signing_key is None): raise RuntimeError("production auth/key provider missing")
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}",self.recipient) or self.recipient.lower()=="0x"+"0"*40: raise RuntimeError("payment recipient missing/placeholder")

class PaymentService:
    def __init__(self, config: Config, facilitator: Facilitator | None=None):
        config.validate(); self.config=config; self.facilitator=facilitator; self._lock=threading.RLock(); self._init()
    def _db(self):
        db=sqlite3.connect(self.config.db_path,timeout=30,isolation_level=None,check_same_thread=False);db.row_factory=sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL");db.execute("PRAGMA foreign_keys=ON");db.execute("PRAGMA busy_timeout=30000");return db
    def _init(self):
        schema=Path(__file__).parents[1]/"migrations/001_payments_v1.sql"
        with self._db() as db: db.executescript(schema.read_text())
    @staticmethod
    def now(): return datetime.now(timezone.utc).isoformat()
    @staticmethod
    def normalize_email(value: str) -> str:
        value=value.strip().lower()
        if len(value)>254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",value): raise ValueError("invalid email")
        return value
    @staticmethod
    def _hash(value: str) -> str: return hashlib.sha256(value.encode()).hexdigest()
    def _audit(self,db,actor,operation,obj,data):
        prior=db.execute("SELECT chain_hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone();prev=prior[0] if prior else "0"*64
        stamp=self.now();data_hash=self._hash(json.dumps(data,sort_keys=True,separators=(",",":"),default=str));chain=self._hash("|".join((prev,stamp,actor,operation,obj,data_hash)))
        db.execute("INSERT INTO audit_events(event_id,at,actor,operation,object_id,data_hash,previous_hash,chain_hash) VALUES(?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),stamp,actor,operation,obj,data_hash,prev,chain))
    def create_order(self,rail: str, email: str, license_name: str="Personal") -> dict[str,Any]:
        if rail not in {"x402","paypal"}: raise ValueError("rail")
        email=self.normalize_email(email);oid=str(uuid.uuid4());recovery=secrets.token_urlsafe(18);now=datetime.now(timezone.utc);expiry=(now+timedelta(seconds=self.config.quote_seconds)).isoformat()
        with self._lock,self._db() as db:
            confirmed=db.execute("SELECT count(*) FROM orders WHERE confirmed_at IS NOT NULL").fetchone()[0];early=confirmed<EARLY_LIMIT;amount=EARLY_MICRO if early else REGULAR_MICRO;currency="USDC" if rail=="x402" else "USD"
            db.execute("BEGIN IMMEDIATE");db.execute("INSERT INTO orders(id,recovery_code_hash,rail,state,quoted_amount,currency,tier,quote_expires_at,buyer_email,license_name,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(oid,self._hash(recovery),rail,"pending_payment",amount,currency,"early" if early else "regular",expiry,email,license_name.strip()[:100],now.isoformat(),now.isoformat()));self._audit(db,"buyer","order.created",oid,{"rail":rail,"amount":amount,"currency":currency,"email_hash":self._hash(email)});db.commit()
        return {"order_id":oid,"recovery_code":recovery,"state":"pending_payment","amount":amount,"currency":currency,"tier":"early" if early else "regular","quote_expires_at":expiry}
    def challenge(self,order_id: str) -> dict[str,Any]:
        with self._db() as db: row=db.execute("SELECT * FROM orders WHERE id=? AND rail='x402'",(order_id,)).fetchone()
        if not row: raise KeyError("order")
        if row["state"]!="pending_payment" or datetime.fromisoformat(row["quote_expires_at"])<=datetime.now(timezone.utc): raise ValueError("expired or unavailable")
        return {"x402Version":2,"accepts":[{"scheme":"exact","network":BASE_NETWORK,"asset":BASE_USDC,"amount":str(row["quoted_amount"]),"payTo":self.config.recipient,"maxTimeoutSeconds":self.config.quote_seconds,"extra":{"name":"USD Coin","version":"2","orderId":row["id"],"product":"growthmap","majorVersion":1}}]}
    def confirm_payment_and_allocate_sale(self,order_id: str,proof_id: str,amount: int,currency: str,payer_ref: str|None=None,tx_hash: str|None=None,actor="system") -> dict[str,Any]:
        """Single cross-rail serialization point. Price mismatch is manual review, never issuance."""
        with self._lock,self._db() as db:
            db.execute("BEGIN IMMEDIATE");row=db.execute("SELECT * FROM orders WHERE id=?",(order_id,)).fetchone()
            if not row: db.rollback();raise KeyError("order")
            if row["state"]=="license_issued": db.commit();return dict(row)
            if row["state"]!="pending_payment": db.rollback();raise ValueError("invalid state")
            now=datetime.now(timezone.utc);confirmed=db.execute("SELECT count(*) FROM orders WHERE confirmed_at IS NOT NULL").fetchone()[0];expected=EARLY_MICRO if confirmed<EARLY_LIMIT else REGULAR_MICRO
            valid_currency=(row["rail"]=="x402" and currency=="USDC") or (row["rail"]=="paypal" and currency=="USD")
            if datetime.fromisoformat(row["quote_expires_at"])<=now or amount!=expected or amount!=row["quoted_amount"] or not valid_currency:
                db.execute("UPDATE orders SET state='manual_review',updated_at=? WHERE id=?",(now.isoformat(),order_id));self._audit(db,actor,"payment.price_mismatch",order_id,{"provided":amount,"expected":expected,"currency":currency});db.commit();return dict(db.execute("SELECT * FROM orders WHERE id=?",(order_id,)).fetchone())
            ordinal=confirmed+1;license_id=f"gm-v1-{uuid.uuid4()}";doc=self._license(license_id,now)
            try: db.execute("INSERT INTO payment_proofs(proof_hash,rail,order_id,tx_hash,created_at) VALUES(?,?,?,?,?)",(self._hash(proof_id),row["rail"],order_id,tx_hash,now.isoformat()))
            except sqlite3.IntegrityError: db.rollback();raise ValueError("duplicate payment proof")
            db.execute("UPDATE orders SET state='license_issued',sale_ordinal=?,confirmed_at=?,updated_at=?,payer_ref=?,tx_hash=?,license_id=?,license_json=? WHERE id=?",(ordinal,now.isoformat(),now.isoformat(),payer_ref,tx_hash,license_id,json.dumps(doc,separators=(",",":")),order_id));self._audit(db,actor,"payment.confirmed_and_license_issued",order_id,{"ordinal":ordinal,"license_id":license_id,"proof_hash":self._hash(proof_id)});db.commit();return dict(db.execute("SELECT * FROM orders WHERE id=?",(order_id,)).fetchone())
    def _license(self,license_id,now):
        if self.config.signing_key is None: raise RuntimeError("signing key unavailable")
        doc={"schema_version":1,"edition":"personal","license_id":license_id,"major_version":1,"device_allowance":2,"device_binding":None,"issued_at":now.isoformat(),"expires_at":None,"revoked_at":None,"max_active_projects":None}
        payload=json.dumps(doc,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode();doc["signature"]=base64.b64encode(self.config.signing_key.sign(payload)).decode();return doc
    def paypal_confirm(self,order_id,transaction_id,attestation,actor="admin"):
        required={"amount","currency","status","payee_verified"}
        if set(attestation)!=required or attestation["status"]!="COMPLETED" or attestation["currency"]!="USD" or attestation["payee_verified"] is not True: raise ValueError("invalid PayPal attestation")
        return self.confirm_payment_and_allocate_sale(order_id,transaction_id,int(attestation["amount"]*1_000_000),attestation["currency"],actor=actor)
    def verify_audit(self) -> bool:
        prev="0"*64
        with self._db() as db: rows=db.execute("SELECT * FROM audit_events ORDER BY seq").fetchall()
        for r in rows:
            expected=self._hash("|".join((prev,r["at"],r["actor"],r["operation"],r["object_id"],r["data_hash"])))
            if expected!=r["chain_hash"] or r["previous_hash"]!=prev:return False
            prev=r["chain_hash"]
        return True
