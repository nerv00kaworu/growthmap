PRAGMA user_version=1;
CREATE TABLE IF NOT EXISTS orders(
 id TEXT PRIMARY KEY,recovery_code_hash TEXT NOT NULL UNIQUE,rail TEXT NOT NULL CHECK(rail IN('x402','paypal')),
 state TEXT NOT NULL CHECK(state IN('pending_payment','payment_confirmed','license_issued','manual_review','rejected','expired','refunded','revoked')),
 quoted_amount INTEGER NOT NULL,currency TEXT NOT NULL,tier TEXT NOT NULL CHECK(tier IN('early','regular')),quote_expires_at TEXT NOT NULL,
 buyer_email TEXT NOT NULL,license_name TEXT NOT NULL,payer_ref TEXT,tx_hash TEXT UNIQUE,sale_ordinal INTEGER UNIQUE CHECK(sale_ordinal IS NULL OR sale_ordinal>0),
 license_id TEXT UNIQUE,license_json TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,confirmed_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_early_per_ordinal ON orders(sale_ordinal) WHERE sale_ordinal<=50;
CREATE TABLE IF NOT EXISTS payment_proofs(proof_hash TEXT PRIMARY KEY,rail TEXT NOT NULL,order_id TEXT NOT NULL REFERENCES orders(id),tx_hash TEXT UNIQUE,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS external_events(event_hash TEXT PRIMARY KEY,source TEXT NOT NULL,order_id TEXT REFERENCES orders(id),received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL UNIQUE,at TEXT NOT NULL,actor TEXT NOT NULL,operation TEXT NOT NULL,object_id TEXT NOT NULL,data_hash TEXT NOT NULL,previous_hash TEXT NOT NULL,chain_hash TEXT NOT NULL UNIQUE);
