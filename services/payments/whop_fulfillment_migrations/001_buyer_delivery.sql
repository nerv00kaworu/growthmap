-- Apply once to an existing verified-inbox fulfillment database while the
-- fulfillment worker and Payments API are stopped. New databases are created
-- with these columns by Worker.initialize(). Historical grants remain present
-- but intentionally have no recoverable buyer key.
ALTER TABLE whop_fulfillments ADD COLUMN whop_user_id TEXT;
ALTER TABLE whop_fulfillments ADD COLUMN order_id TEXT;
ALTER TABLE whop_fulfillments ADD COLUMN recovery_code_hash TEXT;
ALTER TABLE whop_fulfillments ADD COLUMN recovery_nonce BLOB;
ALTER TABLE whop_fulfillments ADD COLUMN recovery_ciphertext BLOB;
CREATE UNIQUE INDEX whop_fulfillments_order_id ON whop_fulfillments(order_id) WHERE order_id IS NOT NULL;
CREATE UNIQUE INDEX whop_fulfillments_recovery_hash ON whop_fulfillments(recovery_code_hash) WHERE recovery_code_hash IS NOT NULL;
CREATE INDEX whop_fulfillments_buyer_state ON whop_fulfillments(whop_user_id,state,granted_at);
CREATE TRIGGER whop_fulfillment_binding_immutable BEFORE UPDATE ON whop_fulfillments
WHEN NEW.payment_id IS NOT OLD.payment_id OR NEW.commercial_digest IS NOT OLD.commercial_digest OR
 NEW.product_id IS NOT OLD.product_id OR NEW.plan_id IS NOT OLD.plan_id OR NEW.tier IS NOT OLD.tier OR
 NEW.source_id IS NOT OLD.source_id OR NEW.payload_digest IS NOT OLD.payload_digest OR
 NEW.grant_webhook_id IS NOT OLD.grant_webhook_id OR NEW.whop_user_id IS NOT OLD.whop_user_id OR
 NEW.order_id IS NOT OLD.order_id OR NEW.recovery_code_hash IS NOT OLD.recovery_code_hash OR
 NEW.recovery_nonce IS NOT OLD.recovery_nonce OR NEW.recovery_ciphertext IS NOT OLD.recovery_ciphertext
BEGIN SELECT RAISE(ABORT,'Whop fulfillment binding is immutable'); END;
CREATE TRIGGER whop_fulfillment_no_delete BEFORE DELETE ON whop_fulfillments
BEGIN SELECT RAISE(ABORT,'Whop fulfillment is append-only'); END;
