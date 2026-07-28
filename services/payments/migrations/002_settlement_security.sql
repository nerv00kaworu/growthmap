CREATE TABLE orders_v2(
 id TEXT PRIMARY KEY,recovery_code_hash TEXT NOT NULL UNIQUE,rail TEXT NOT NULL CHECK(rail IN('x402','paypal')),
 state TEXT NOT NULL CHECK(state IN('pending_payment','payment_confirmed','license_issued','manual_review','rejected','expired','refunded','revoked')),
 quoted_amount_minor INTEGER NOT NULL CHECK(quoted_amount_minor>0),currency TEXT NOT NULL,tier TEXT NOT NULL CHECK(tier IN('early','regular')),quote_expires_at TEXT NOT NULL,
 buyer_email TEXT NOT NULL,license_name TEXT NOT NULL,payer_ref TEXT,tx_hash TEXT UNIQUE,sale_ordinal INTEGER UNIQUE CHECK(sale_ordinal IS NULL OR sale_ordinal>0),
 license_id TEXT UNIQUE,license_json TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,confirmed_at TEXT,
 CHECK((rail='x402' AND currency='USDC') OR (rail='paypal' AND currency='USD')));
CREATE TABLE payment_proofs_v2(proof_hash TEXT PRIMARY KEY,rail TEXT NOT NULL,order_id TEXT NOT NULL REFERENCES orders_v2(id),tx_hash TEXT UNIQUE,created_at TEXT NOT NULL);
CREATE TABLE external_events_v2(event_hash TEXT PRIMARY KEY,source TEXT NOT NULL,order_id TEXT REFERENCES orders_v2(id),received_at TEXT NOT NULL);
INSERT INTO orders_v2 SELECT id,recovery_code_hash,rail,state,CASE WHEN rail='paypal' THEN CAST(quoted_amount/10000 AS INTEGER) ELSE quoted_amount END,currency,tier,quote_expires_at,buyer_email,license_name,payer_ref,tx_hash,sale_ordinal,license_id,license_json,created_at,updated_at,confirmed_at FROM orders;
INSERT INTO payment_proofs_v2 SELECT * FROM payment_proofs;
INSERT INTO external_events_v2 SELECT * FROM external_events;
DROP TABLE payment_proofs;
DROP TABLE external_events;
DROP TABLE orders;
ALTER TABLE orders_v2 RENAME TO orders;
ALTER TABLE payment_proofs_v2 RENAME TO payment_proofs;
ALTER TABLE external_events_v2 RENAME TO external_events;
CREATE UNIQUE INDEX one_early_per_ordinal ON orders(sale_ordinal) WHERE sale_ordinal<=50;
CREATE TABLE settlement_intents(intent_id TEXT PRIMARY KEY,order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),proof_hash TEXT NOT NULL UNIQUE,nonce_hash TEXT NOT NULL UNIQUE,amount_minor INTEGER NOT NULL,currency TEXT NOT NULL,reserved_ordinal INTEGER NOT NULL,lease_expires_at TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('prepared','settled','ambiguous','finalized_paid','cancelled_unpaid')),tx_hash TEXT UNIQUE,evidence_hash TEXT,evidence_source TEXT,finality_at TEXT,reconciled_by TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX active_intent_ordinal ON settlement_intents(reserved_ordinal) WHERE state!='cancelled_unpaid';
CREATE TABLE migration_ledger(version INTEGER PRIMARY KEY,filename TEXT NOT NULL UNIQUE,checksum TEXT NOT NULL,applied_at TEXT NOT NULL);
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT,'audit is append-only');END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT,'audit is append-only');END;
