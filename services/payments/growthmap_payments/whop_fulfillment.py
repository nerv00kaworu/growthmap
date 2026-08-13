"""Production Whop verified-inbox fulfillment worker.

The ingress process owns signature verification.  This worker accepts only rows already
marked ``verified_pending`` and never interprets unselected/unknown event types.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .authority_http import SignedAuthorityHTTPAdapter

COMPANY_ID = "biz_RVr0w7JHwRZgIq"
PRODUCTS = {
    ("prod_PvObOc5wfatCY", "plan_rjuSiGxXCweMF"): ("early", Decimal("10")),
    ("prod_Lrwhtxe2bDQDD", "plan_BIaeEIZ2e6OP3"): ("standard", Decimal("29")),
}
EARLY_LIMIT = 50
SUPPORTED = {"payment.succeeded", "refund.created", "dispute.created"}
MAX_PAYLOAD = 64 * 1024
MAX_ATTEMPTS = 8


class FulfillmentError(RuntimeError):
    pass


class PermanentFulfillmentError(FulfillmentError):
    pass


@dataclass(frozen=True)
class Event:
    webhook_id: str
    event_type: str
    payment_id: str
    company_id: str
    product_id: str
    plan_id: str
    currency: str
    amount: Decimal
    status: str
    occurred_at: str
    payload_sha256: str


def _strict_json(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_PAYLOAD:
        raise PermanentFulfillmentError("invalid verified event")
    def pairs(items):
        result = {}; seen = set()
        for key, value in items:
            if type(key) is not str or key.casefold() in seen:
                raise PermanentFulfillmentError("invalid verified event")
            seen.add(key.casefold()); result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_float=Decimal, parse_int=Decimal)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise PermanentFulfillmentError("invalid verified event") from None
    if type(value) is not dict:
        raise PermanentFulfillmentError("invalid verified event")
    return value


def _identifier(value: Any) -> str:
    if type(value) is dict:
        value = value.get("id")
    if type(value) is not str or not value or len(value) > 192:
        raise PermanentFulfillmentError("invalid verified event")
    return value


def _required(container: dict, *names: str):
    found = [container[name] for name in names if name in container]
    if len(found) != 1:
        raise PermanentFulfillmentError("invalid verified event")
    return found[0]


def _timestamp(value: Any) -> str:
    if type(value) is not str:
        raise PermanentFulfillmentError("invalid verified event")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PermanentFulfillmentError("invalid verified event") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise PermanentFulfillmentError("invalid verified event")
    return parsed.astimezone(timezone.utc).isoformat()


def parse_event(webhook_id: str, event_type: str, raw: bytes, stored_digest: str) -> Event:
    if hashlib.sha256(raw).hexdigest() != stored_digest:
        raise PermanentFulfillmentError("verified payload digest mismatch")
    envelope = _strict_json(raw)
    if envelope.get("id") != webhook_id or envelope.get("type") != event_type:
        raise PermanentFulfillmentError("verified envelope mismatch")
    if event_type not in SUPPORTED:
        raise PermanentFulfillmentError("unsupported event")
    company_id = _identifier(_required(envelope, "company_id"))
    data = envelope.get("data")
    if type(data) is not dict:
        raise PermanentFulfillmentError("invalid verified event")
    payment = data.get("payment") if event_type != "payment.succeeded" else data
    if type(payment) is str:
        payment = {"id": payment}
    if type(payment) is not dict:
        raise PermanentFulfillmentError("invalid verified event")
    payment_id = _identifier(_required(payment, "id", "payment_id"))
    # Reversal objects may carry commercial binding either on the linked payment or
    # on their own data object.  Ambiguous double representations are rejected.
    semantic = payment if all(key in payment for key in ("currency", "status")) else data
    product_id = _identifier(_required(semantic, "product", "product_id"))
    plan_id = _identifier(_required(semantic, "plan", "plan_id"))
    currency = _required(semantic, "currency")
    status = _required(semantic, "status")
    amount_value = _required(semantic, "total", "amount")
    if type(currency) is not str or type(status) is not str or isinstance(amount_value, bool):
        raise PermanentFulfillmentError("invalid verified event")
    try:
        amount = Decimal(amount_value)
    except (InvalidOperation, TypeError, ValueError):
        raise PermanentFulfillmentError("invalid verified event") from None
    if not amount.is_finite():
        raise PermanentFulfillmentError("invalid verified event")
    occurred_at = _timestamp(_required(envelope, "timestamp", "created_at"))
    return Event(webhook_id, event_type, payment_id, company_id, product_id, plan_id,
                 currency, amount, status, occurred_at, stored_digest)


def _validate_semantics(event: Event) -> tuple[str, Decimal]:
    if event.company_id != COMPANY_ID or (event.product_id, event.plan_id) not in PRODUCTS:
        raise PermanentFulfillmentError("commercial binding mismatch")
    tier, expected = PRODUCTS[(event.product_id, event.plan_id)]
    if event.currency.lower() != "usd" or event.amount != expected:
        raise PermanentFulfillmentError("commercial binding mismatch")
    expected_status = {"payment.succeeded": "succeeded", "refund.created": "refunded",
                       "dispute.created": "open"}[event.event_type]
    allowed = {"open", "created"} if event.event_type == "dispute.created" else {expected_status}
    if event.status.lower() not in allowed:
        raise PermanentFulfillmentError("commercial binding mismatch")
    return tier, expected


def _canonical_event_digest(event: Event) -> str:
    value = [event.event_type, event.payment_id, event.company_id, event.product_id,
             event.plan_id, event.currency.lower(), str(event.amount), event.status.lower()]
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS whop_fulfillments(
 payment_id TEXT PRIMARY KEY,
 commercial_digest TEXT NOT NULL,
 product_id TEXT NOT NULL,
 plan_id TEXT NOT NULL,
 tier TEXT NOT NULL CHECK(tier IN('early','standard')),
 source_id TEXT NOT NULL UNIQUE,
 payload_digest TEXT NOT NULL,
 license_id TEXT UNIQUE,
 state TEXT NOT NULL CHECK(state IN('granting','granted','revoked')),
 grant_webhook_id TEXT NOT NULL UNIQUE,
 granted_at TEXT,
 revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS whop_fulfillment_attempts(
 webhook_id TEXT PRIMARY KEY,
 payload_sha256 TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt_at TEXT,
 last_error_digest TEXT
);
CREATE INDEX IF NOT EXISTS whop_fulfillments_tier_state ON whop_fulfillments(tier,state);
"""


class Worker:
    def __init__(self, db_path: Path, authority: SignedAuthorityHTTPAdapter,
                 *, max_attempts: int = MAX_ATTEMPTS, clock=lambda: datetime.now(timezone.utc)):
        self.db_path = Path(db_path); self.authority = authority; self.max_attempts = max_attempts; self.clock = clock
        self._run_lock = threading.Lock()
        if not 1 <= max_attempts <= 32:
            raise FulfillmentError("worker configuration invalid")

    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row; db.execute("PRAGMA foreign_keys=ON"); db.execute("PRAGMA busy_timeout=30000")
        return db

    def initialize(self):
        with self._db() as db:
            db.executescript(SCHEMA)
            columns = {row[1] for row in db.execute("PRAGMA table_info(inbox)")}
            required = {"webhook_id", "event_type", "payload_sha256", "payload", "status"}
            if not required <= columns:
                raise FulfillmentError("verified inbox schema unavailable")

    def run_once(self, limit: int = 25) -> dict[str, int]:
        # One worker object never overlaps batches. SQLite BEGIN IMMEDIATE below remains the
        # cross-process authority for the Early allocation itself.
        with self._run_lock:
            return self._run_once_locked(limit)

    def _run_once_locked(self, limit: int) -> dict[str, int]:
        if not 1 <= limit <= 100:
            raise FulfillmentError("worker configuration invalid")
        counts = {"processed": 0, "granted": 0, "revoked": 0, "ignored": 0, "retry": 0, "failed": 0}
        with self._db() as db:
            rows = list(db.execute("""SELECT i.webhook_id,i.event_type,i.payload_sha256,i.payload,i.status,
                COALESCE(a.attempts,0) attempts,a.next_attempt_at
                FROM inbox i LEFT JOIN whop_fulfillment_attempts a USING(webhook_id)
                WHERE i.status='verified_pending'
                  AND (a.next_attempt_at IS NULL OR a.next_attempt_at<=?)
                ORDER BY i.rowid LIMIT ?""", (self.clock().isoformat(), limit)))
        for row in rows:
            counts["processed"] += 1
            if row["event_type"] not in SUPPORTED:
                self._finish(row, "processed"); counts["ignored"] += 1; continue
            try:
                event = parse_event(row["webhook_id"], row["event_type"], bytes(row["payload"]), row["payload_sha256"])
                outcome = self._process(event)
                counts[outcome] += 1
                self._finish(row, "processed")
            except PermanentFulfillmentError as error:
                self._fail(row, error, permanent=True); counts["failed"] += 1
            except Exception as error:
                terminal = row["attempts"] + 1 >= self.max_attempts
                self._fail(row, error, permanent=terminal); counts["failed" if terminal else "retry"] += 1
        return counts

    def _process(self, event: Event) -> str:
        tier, _ = _validate_semantics(event)
        if event.event_type == "payment.succeeded":
            return self._grant(event, tier)
        return self._revoke(event)

    def _grant(self, event: Event, tier: str) -> str:
        source_id = hashlib.sha256(("whop-payment\0" + event.payment_id).encode()).hexdigest()
        digest = _canonical_event_digest(event)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM whop_fulfillments WHERE payment_id=?", (event.payment_id,)).fetchone()
            if existing:
                if existing["commercial_digest"] != digest:
                    db.rollback(); raise PermanentFulfillmentError("conflicting provider payment id")
                if existing["state"] in {"granted", "revoked"}:
                    db.rollback(); return "granted"
            else:
                if tier == "early" and db.execute("SELECT count(*) FROM whop_fulfillments WHERE tier='early' AND state IN('granting','granted','revoked')").fetchone()[0] >= EARLY_LIMIT:
                    db.rollback(); raise PermanentFulfillmentError("early allocation exhausted")
                db.execute("INSERT INTO whop_fulfillments(payment_id,commercial_digest,product_id,plan_id,tier,source_id,payload_digest,state,grant_webhook_id) VALUES(?,?,?,?,?,?,?,'granting',?)",
                           (event.payment_id, digest, event.product_id, event.plan_id, tier, source_id, event.payload_sha256, event.webhook_id))
            identity = self.authority.handshake()
            body = {"source": "whop", "source_id": source_id, "payload_digest": event.payload_sha256,
                    "authority_id": identity["authority_id"], "signer_identity": identity,
                    "edition": "personal", "major_version": 1, "seat_limit": 2}
            self.authority.create_external_entitlement(**body)
            acknowledgement = self.authority.read_external_entitlement_acknowledgement(
                source="whop", source_id=source_id, signer_identity=identity)
            if type(acknowledgement) is not dict or acknowledgement.get("source_id") != source_id or type(acknowledgement.get("license_id")) is not str:
                db.rollback(); raise FulfillmentError("authority acknowledgement invalid")
            db.execute("UPDATE whop_fulfillments SET state='granted',license_id=?,granted_at=? WHERE payment_id=? AND state='granting'",
                       (acknowledgement["license_id"], self.clock().isoformat(), event.payment_id))
            db.commit(); return "granted"

    def _revoke(self, event: Event) -> str:
        digest = _canonical_event_digest(event)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            linked = db.execute("SELECT * FROM whop_fulfillments WHERE payment_id=?", (event.payment_id,)).fetchone()
            if not linked or linked["state"] == "granting" or not linked["license_id"]:
                db.rollback(); raise FulfillmentError("linked entitlement unavailable")
            if linked["product_id"] != event.product_id or linked["plan_id"] != event.plan_id:
                db.rollback(); raise PermanentFulfillmentError("reversal binding mismatch")
            if linked["state"] == "revoked":
                db.rollback(); return "revoked"
            identity = self.authority.handshake()
            action = "refund" if event.event_type == "refund.created" else "revoke"
            reason = "refund" if action == "refund" else "chargeback"
            payment_proof = hashlib.sha256(("whop-proof\0" + event.payment_id).encode()).hexdigest()
            tx_hash = "0x" + hashlib.sha256(("whop-reference\0" + event.payment_id).encode()).hexdigest()
            body = {"source": "whop", "source_id": linked["source_id"], "payload_digest": linked["payload_digest"],
                    "authority_id": identity["authority_id"], "signer_identity": identity,
                    "license_id": linked["license_id"], "action": action, "reason": reason,
                    "payment_proof": payment_proof, "tx_hash": tx_hash, "created_at": event.occurred_at}
            self.authority.revoke_external_entitlement(**body)
            acknowledgement = self.authority.read_external_revocation_acknowledgement(
                source="whop", source_id=linked["source_id"], signer_identity=identity)
            if type(acknowledgement) is not dict or acknowledgement.get("license_id") != linked["license_id"]:
                db.rollback(); raise FulfillmentError("authority acknowledgement invalid")
            db.execute("UPDATE whop_fulfillments SET state='revoked',revoked_at=? WHERE payment_id=?",
                       (self.clock().isoformat(), event.payment_id))
            db.commit(); return "revoked"

    def _finish(self, row, status: str):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE inbox SET status=? WHERE webhook_id=? AND payload_sha256=? AND status='verified_pending'",
                                 (status, row["webhook_id"], row["payload_sha256"])).rowcount
            if changed != 1:
                db.rollback(); raise FulfillmentError("inbox row changed")
            db.execute("DELETE FROM whop_fulfillment_attempts WHERE webhook_id=?", (row["webhook_id"],)); db.commit()

    def _fail(self, row, error: Exception, *, permanent: bool):
        attempts = row["attempts"] + 1
        digest = hashlib.sha256(type(error).__name__.encode()).hexdigest()
        delay = min(3600, 2 ** min(attempts, 11))
        next_at = datetime.fromtimestamp(self.clock().timestamp() + delay, timezone.utc).isoformat()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO whop_fulfillment_attempts(webhook_id,payload_sha256,attempts,next_attempt_at,last_error_digest) VALUES(?,?,?,?,?) ON CONFLICT(webhook_id) DO UPDATE SET attempts=excluded.attempts,next_attempt_at=excluded.next_attempt_at,last_error_digest=excluded.last_error_digest",
                       (row["webhook_id"], row["payload_sha256"], attempts, next_at, digest))
            if permanent:
                db.execute("UPDATE inbox SET status='rejected' WHERE webhook_id=? AND payload_sha256=? AND status='verified_pending'",
                           (row["webhook_id"], row["payload_sha256"]))
            db.commit()


def load_worker(config_path: Path) -> Worker:
    try:
        config = json.loads(Path(config_path).read_bytes())
    except Exception:
        raise FulfillmentError("worker configuration unavailable") from None
    required = {"database", "authority_origin", "authority_id", "authority_audience", "edge_identity",
                "edge_source", "edge_private_key_file", "signer_identity"}
    if type(config) is not dict or set(config) != required:
        raise FulfillmentError("worker configuration invalid")
    adapter = SignedAuthorityHTTPAdapter(origin=config["authority_origin"], authority_id=config["authority_id"],
        audience=config["authority_audience"], edge_identity=config["edge_identity"], edge_source=config["edge_source"],
        private_key_file=Path(config["edge_private_key_file"]), signer_identity=config["signer_identity"])
    return Worker(Path(config["database"]), adapter)


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=2.0); parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args(argv); worker = load_worker(Path(args.config)); worker.initialize()
    while True:
        result = worker.run_once(args.limit)
        print(json.dumps(result, sort_keys=True), flush=True)
        if args.once: return
        time.sleep(max(0.2, min(args.interval, 60.0)))


if __name__ == "__main__":
    main()
