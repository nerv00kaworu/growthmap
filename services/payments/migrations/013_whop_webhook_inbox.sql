-- Authenticated Whop events only. Raw request bodies and signature secrets are
-- never stored; immutable identity/payload digests retain an audit trail.
CREATE TABLE whop_webhook_inbox(
 event_id TEXT PRIMARY KEY,
 raw_digest TEXT NOT NULL CHECK(length(raw_digest)=64),
 occurred_at TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN('paid','refund','dispute','chargeback')),
 -- Deliberately no FK: authenticated events with an unknown local order must be
 -- retained durably for bounded quarantine and operator reconciliation.
 order_id TEXT NOT NULL,
 provider_order_ref TEXT NOT NULL,
 provider_payment_ref TEXT NOT NULL,
 received_at TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN('received','applied','quarantined')),
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0),
 applied_at TEXT,
 last_attempt_at TEXT,
 error_digest TEXT CHECK(error_digest IS NULL OR length(error_digest)=64),
 UNIQUE(provider_order_ref,event_id)
);
CREATE INDEX whop_webhook_inbox_state ON whop_webhook_inbox(state,received_at);
CREATE TRIGGER whop_webhook_payload_immutable BEFORE UPDATE ON whop_webhook_inbox
WHEN NEW.event_id!=OLD.event_id OR NEW.raw_digest!=OLD.raw_digest OR
 NEW.occurred_at!=OLD.occurred_at OR NEW.kind!=OLD.kind OR
 NEW.order_id!=OLD.order_id OR NEW.provider_order_ref!=OLD.provider_order_ref OR
 NEW.provider_payment_ref!=OLD.provider_payment_ref OR NEW.received_at!=OLD.received_at
BEGIN SELECT RAISE(ABORT,'Whop webhook payload is immutable'); END;
CREATE TRIGGER whop_webhook_no_delete BEFORE DELETE ON whop_webhook_inbox
BEGIN SELECT RAISE(ABORT,'Whop webhook inbox is append-only'); END;
CREATE TRIGGER whop_webhook_state_monotonic BEFORE UPDATE ON whop_webhook_inbox
WHEN (OLD.state='applied' AND NEW.state!='applied') OR
 (OLD.state='quarantined' AND NEW.state!='quarantined') OR
 (NEW.attempts<OLD.attempts) OR
 (OLD.applied_at IS NOT NULL AND NEW.applied_at IS NOT OLD.applied_at)
BEGIN SELECT RAISE(ABORT,'Whop webhook state is monotonic'); END;
