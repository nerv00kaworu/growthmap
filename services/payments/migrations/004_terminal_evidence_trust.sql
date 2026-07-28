-- Terminal settlement evidence is immutable after it has been authenticated by the
-- service's external HMAC trust root. The sole terminal transition is settlement
-- finalization; it may change only state and updated_at.
CREATE TRIGGER settlement_terminal_immutable BEFORE UPDATE ON settlement_intents
WHEN OLD.state IN('settled','finalized_paid','cancelled_unpaid') AND NOT (
  OLD.state='settled' AND NEW.state='finalized_paid' AND
  NEW.intent_id IS OLD.intent_id AND NEW.order_id IS OLD.order_id AND
  NEW.proof_hash IS OLD.proof_hash AND NEW.nonce_hash IS OLD.nonce_hash AND
  NEW.amount_minor IS OLD.amount_minor AND NEW.currency IS OLD.currency AND
  NEW.reserved_ordinal IS OLD.reserved_ordinal AND NEW.lease_expires_at IS OLD.lease_expires_at AND
  NEW.tx_hash IS OLD.tx_hash AND NEW.evidence_hash IS OLD.evidence_hash AND
  NEW.evidence_source IS OLD.evidence_source AND NEW.finality_at IS OLD.finality_at AND
  NEW.evidence_binding IS OLD.evidence_binding AND NEW.reconciled_by IS OLD.reconciled_by AND
  NEW.created_at IS OLD.created_at
)
BEGIN SELECT RAISE(ABORT,'terminal settlement evidence is immutable'); END;

CREATE TRIGGER settlement_terminal_delete BEFORE DELETE ON settlement_intents
WHEN OLD.state IN('settled','finalized_paid','cancelled_unpaid')
BEGIN SELECT RAISE(ABORT,'terminal settlement evidence is immutable'); END;
