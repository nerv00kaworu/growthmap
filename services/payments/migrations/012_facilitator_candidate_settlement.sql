-- Preserve a facilitator-accepted transaction as a non-final, immutable lookup hint.
-- A candidate never authorizes payment, finality, sale allocation, or entitlement.
CREATE TABLE settlement_candidates(
 intent_id TEXT PRIMARY KEY REFERENCES settlement_intents(intent_id),
 tx_hash TEXT NOT NULL UNIQUE,
 payer TEXT NOT NULL,
 network TEXT NOT NULL,
 amount_minor INTEGER NOT NULL CHECK(amount_minor>0),
 source TEXT NOT NULL,
 observed_at TEXT NOT NULL,
 response_hash TEXT NOT NULL UNIQUE
);
CREATE TRIGGER settlement_candidate_immutable BEFORE UPDATE ON settlement_candidates
BEGIN SELECT RAISE(ABORT,'settlement candidate is immutable'); END;
CREATE TRIGGER settlement_candidate_delete BEFORE DELETE ON settlement_candidates
BEGIN SELECT RAISE(ABORT,'settlement candidate is immutable'); END;
