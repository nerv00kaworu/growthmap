-- R6 expands the external authenticated checkpoint from terminal intents to the
-- complete issuance closure. Existing v5 terminal rows cannot be proven to have
-- been protected by that closure, so they are quarantined rather than issued.
DROP TRIGGER IF EXISTS settlement_terminal_immutable;
DROP TRIGGER IF EXISTS settlement_terminal_delete;
DROP TRIGGER IF EXISTS settlement_evidence_required_insert;
DROP TRIGGER IF EXISTS settlement_evidence_required_update;
UPDATE orders SET state='manual_review',updated_at=CURRENT_TIMESTAMP
WHERE id IN (SELECT order_id FROM settlement_intents WHERE state IN('settled','finalized_paid','cancelled_unpaid'));
UPDATE settlement_intents SET state='ambiguous',evidence_binding=NULL,updated_at=CURRENT_TIMESTAMP
WHERE state IN('settled','finalized_paid','cancelled_unpaid');
CREATE TRIGGER settlement_terminal_immutable BEFORE UPDATE ON settlement_intents
WHEN OLD.state IN('settled','finalized_paid','cancelled_unpaid') AND NOT (
 OLD.state='settled' AND NEW.state='finalized_paid' AND
 NEW.intent_id IS OLD.intent_id AND NEW.order_id IS OLD.order_id AND NEW.proof_hash IS OLD.proof_hash AND
 NEW.nonce_hash IS OLD.nonce_hash AND NEW.amount_minor IS OLD.amount_minor AND NEW.currency IS OLD.currency AND
 NEW.reserved_ordinal IS OLD.reserved_ordinal AND NEW.lease_expires_at IS OLD.lease_expires_at AND
 NEW.tx_hash IS OLD.tx_hash AND NEW.evidence_hash IS OLD.evidence_hash AND NEW.evidence_source IS OLD.evidence_source AND
 NEW.finality_at IS OLD.finality_at AND NEW.evidence_binding IS OLD.evidence_binding AND
 NEW.reconciled_by IS OLD.reconciled_by AND NEW.created_at IS OLD.created_at)
BEGIN SELECT RAISE(ABORT,'terminal settlement evidence is immutable'); END;
CREATE TRIGGER settlement_terminal_delete BEFORE DELETE ON settlement_intents
WHEN OLD.state IN('settled','finalized_paid','cancelled_unpaid')
BEGIN SELECT RAISE(ABORT,'terminal settlement evidence is immutable'); END;
CREATE TRIGGER settlement_evidence_required_insert BEFORE INSERT ON settlement_intents
WHEN NEW.state IN('settled','finalized_paid','cancelled_unpaid') AND (NEW.evidence_hash IS NULL OR NEW.evidence_binding IS NULL)
BEGIN SELECT RAISE(ABORT,'settlement evidence binding required'); END;
CREATE TRIGGER settlement_evidence_required_update BEFORE UPDATE ON settlement_intents
WHEN NEW.state IN('settled','finalized_paid','cancelled_unpaid') AND (NEW.evidence_hash IS NULL OR NEW.evidence_binding IS NULL)
BEGIN SELECT RAISE(ABORT,'settlement evidence binding required'); END;
