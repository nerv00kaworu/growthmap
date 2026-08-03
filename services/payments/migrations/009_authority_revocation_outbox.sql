-- Durable at-least-once revocation delivery into LicenseAuthority. Payload fields
-- are immutable; only lease/retry/ack fields may change.
CREATE TABLE revocation_outbox(
 event_id TEXT PRIMARY KEY,
 order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
 authority_id TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source='x402'), source_id TEXT NOT NULL,
 entitlement_payload_digest TEXT NOT NULL,
 license_id TEXT NOT NULL UNIQUE,
 action TEXT NOT NULL CHECK(action IN('refund','revoke')),
 reason TEXT NOT NULL,
 proof_hash TEXT NOT NULL, tx_hash TEXT NOT NULL, evidence_hash TEXT NOT NULL,
 created_at TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN('pending','leased','delivered','quarantined')),
 lease_owner TEXT, lease_expires_at TEXT,
 attempt_count INTEGER NOT NULL DEFAULT 0,
 next_attempt_at TEXT, last_error_hash TEXT,
 fencing_version INTEGER NOT NULL DEFAULT 0,
 delivered_at TEXT, authority_receipt TEXT UNIQUE,
 UNIQUE(authority_id,source,source_id)
);
CREATE INDEX revocation_outbox_pending ON revocation_outbox(state,created_at);
CREATE TRIGGER revocation_outbox_payload_immutable BEFORE UPDATE ON revocation_outbox
WHEN NEW.event_id!=OLD.event_id OR NEW.order_id!=OLD.order_id OR NEW.authority_id!=OLD.authority_id OR
 NEW.source!=OLD.source OR NEW.source_id!=OLD.source_id OR
 NEW.entitlement_payload_digest!=OLD.entitlement_payload_digest OR NEW.license_id!=OLD.license_id OR
 NEW.action!=OLD.action OR NEW.reason!=OLD.reason OR NEW.proof_hash!=OLD.proof_hash OR
 NEW.tx_hash!=OLD.tx_hash OR NEW.evidence_hash!=OLD.evidence_hash OR NEW.created_at!=OLD.created_at
BEGIN SELECT RAISE(ABORT,'revocation outbox payload is immutable'); END;
CREATE TRIGGER revocation_outbox_no_delete BEFORE DELETE ON revocation_outbox
BEGIN SELECT RAISE(ABORT,'revocation outbox is append-only'); END;
CREATE TRIGGER revocation_outbox_ack_once BEFORE UPDATE ON revocation_outbox
WHEN OLD.state='delivered' AND (NEW.state!=OLD.state OR NEW.delivered_at!=OLD.delivered_at OR NEW.authority_receipt!=OLD.authority_receipt)
BEGIN SELECT RAISE(ABORT,'revocation acknowledgement is immutable'); END;
