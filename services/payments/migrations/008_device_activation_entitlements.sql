-- New issuance uses a durable immutable outbox into LicenseAuthority. The old
-- orders.license_json column remains only so pre-v8 rows can be quarantined and
-- manually extracted; v8 runtime never writes or serves it.
ALTER TABLE settlement_intents ADD COLUMN verified_payer TEXT;
ALTER TABLE settlement_intents ADD COLUMN settled_payer TEXT;
ALTER TABLE settlement_intents ADD COLUMN finality_basis TEXT;

CREATE TABLE entitlement_outbox(
 order_id TEXT PRIMARY KEY REFERENCES orders(id),
 source TEXT NOT NULL CHECK(source='x402'), source_id TEXT NOT NULL,
 proof_hash TEXT NOT NULL UNIQUE, tx_hash TEXT NOT NULL UNIQUE,
 evidence_hash TEXT NOT NULL UNIQUE, payer TEXT NOT NULL,
 network TEXT NOT NULL CHECK(network='eip155:8453'),
 asset TEXT NOT NULL CHECK(asset='0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'),
 amount_minor INTEGER NOT NULL CHECK(amount_minor>0),
 product TEXT NOT NULL CHECK(product='growthmap'), major_version INTEGER NOT NULL CHECK(major_version=1),
 state TEXT NOT NULL CHECK(state IN('pending','leased','delivered','quarantined')),
 license_id TEXT UNIQUE, created_at TEXT NOT NULL, delivered_at TEXT,
 lease_owner TEXT, lease_expires_at TEXT, attempt_count INTEGER NOT NULL DEFAULT 0,
 next_attempt_at TEXT, last_error_hash TEXT, delivery_receipt TEXT UNIQUE,
 fencing_version INTEGER NOT NULL DEFAULT 0,
 UNIQUE(source,source_id)
);
CREATE INDEX entitlement_outbox_pending ON entitlement_outbox(state,created_at);
CREATE TRIGGER entitlement_outbox_payload_immutable BEFORE UPDATE ON entitlement_outbox
WHEN NEW.order_id!=OLD.order_id OR NEW.source!=OLD.source OR NEW.source_id!=OLD.source_id OR
 NEW.proof_hash!=OLD.proof_hash OR NEW.tx_hash!=OLD.tx_hash OR NEW.evidence_hash!=OLD.evidence_hash OR
 NEW.payer!=OLD.payer OR NEW.network!=OLD.network OR NEW.asset!=OLD.asset OR
 NEW.amount_minor!=OLD.amount_minor OR NEW.product!=OLD.product OR NEW.major_version!=OLD.major_version OR
 NEW.created_at!=OLD.created_at
BEGIN SELECT RAISE(ABORT,'entitlement outbox payload is immutable'); END;
CREATE TRIGGER entitlement_outbox_no_delete BEFORE DELETE ON entitlement_outbox
BEGIN SELECT RAISE(ABORT,'entitlement outbox is append-only'); END;
CREATE TRIGGER entitlement_outbox_ack_once BEFORE UPDATE ON entitlement_outbox
WHEN OLD.state='delivered' AND (NEW.state!=OLD.state OR NEW.license_id!=OLD.license_id OR NEW.delivered_at!=OLD.delivered_at)
BEGIN SELECT RAISE(ABORT,'entitlement outbox acknowledgement is immutable'); END;

-- Any portable candidate produced before this migration is never promoted by
-- the new path. It remains read-only evidence for an explicit manual process.
CREATE TRIGGER legacy_license_json_no_insert BEFORE INSERT ON orders WHEN NEW.license_json IS NOT NULL
BEGIN SELECT RAISE(ABORT,'portable license output forbidden'); END;
CREATE TRIGGER legacy_license_json_no_update BEFORE UPDATE OF license_json ON orders WHEN NEW.license_json IS NOT OLD.license_json
BEGIN SELECT RAISE(ABORT,'legacy portable license is read-only'); END;
