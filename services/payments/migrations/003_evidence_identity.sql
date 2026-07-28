ALTER TABLE settlement_intents ADD COLUMN evidence_binding TEXT;
CREATE UNIQUE INDEX settlement_evidence_identity ON settlement_intents(evidence_hash) WHERE evidence_hash IS NOT NULL;
CREATE UNIQUE INDEX settlement_evidence_binding ON settlement_intents(evidence_binding) WHERE evidence_binding IS NOT NULL;
CREATE TRIGGER settlement_evidence_required_insert BEFORE INSERT ON settlement_intents
WHEN NEW.state IN('settled','finalized_paid','cancelled_unpaid') AND (NEW.evidence_hash IS NULL OR NEW.evidence_binding IS NULL)
BEGIN SELECT RAISE(ABORT,'settlement evidence binding required'); END;
CREATE TRIGGER settlement_evidence_required_update BEFORE UPDATE ON settlement_intents
WHEN NEW.state IN('settled','finalized_paid','cancelled_unpaid') AND (NEW.evidence_hash IS NULL OR NEW.evidence_binding IS NULL)
BEGIN SELECT RAISE(ABORT,'settlement evidence binding required'); END;
