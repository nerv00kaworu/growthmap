-- Pin each payment outbox item to one independently reviewed Authority signer identity.
-- Existing rows cannot be attributed retroactively: they retain NULL identity and are
-- explicitly classified legacy_identity_unproven. Undelivered work is quarantined.
ALTER TABLE entitlement_outbox ADD COLUMN authority_id TEXT;
ALTER TABLE entitlement_outbox ADD COLUMN authority_key_id TEXT;
ALTER TABLE entitlement_outbox ADD COLUMN authority_generation INTEGER;
ALTER TABLE entitlement_outbox ADD COLUMN authority_public_key_sha256 TEXT;
ALTER TABLE entitlement_outbox ADD COLUMN authority_attestation TEXT;
ALTER TABLE entitlement_outbox ADD COLUMN authority_identity_status TEXT;
ALTER TABLE entitlement_outbox ADD COLUMN authority_ack_signature TEXT;
ALTER TABLE entitlement_outbox ADD COLUMN reconciliation_phase TEXT NOT NULL DEFAULT 'none' CHECK(reconciliation_phase IN('none','crossing_prepared','crossing_authorized','readback_only','manual_review'));
UPDATE entitlement_outbox SET authority_identity_status='legacy_identity_unproven';
UPDATE entitlement_outbox SET state='quarantined',last_error_hash='legacy_identity_unproven'
WHERE state IN('pending','leased');

ALTER TABLE revocation_outbox ADD COLUMN authority_key_id TEXT;
ALTER TABLE revocation_outbox ADD COLUMN authority_generation INTEGER;
ALTER TABLE revocation_outbox ADD COLUMN authority_public_key_sha256 TEXT;
ALTER TABLE revocation_outbox ADD COLUMN authority_attestation TEXT;
ALTER TABLE revocation_outbox ADD COLUMN authority_identity_status TEXT;
ALTER TABLE revocation_outbox ADD COLUMN authority_ack_signature TEXT;
ALTER TABLE revocation_outbox ADD COLUMN authority_revoked_at TEXT;
ALTER TABLE revocation_outbox ADD COLUMN authority_request_digest TEXT;
UPDATE revocation_outbox SET authority_identity_status='legacy_identity_unproven';
UPDATE revocation_outbox SET state='quarantined',last_error_hash='legacy_identity_unproven'
WHERE state IN('pending','leased');

CREATE TRIGGER entitlement_outbox_authority_identity_required BEFORE INSERT ON entitlement_outbox
WHEN NEW.authority_id IS NULL OR NEW.authority_key_id IS NULL OR NEW.authority_generation IS NULL OR
 NEW.authority_public_key_sha256 IS NULL OR NEW.authority_attestation IS NULL OR NEW.authority_identity_status!='verified'
BEGIN SELECT RAISE(ABORT,'authority signer identity required'); END;
CREATE TRIGGER entitlement_outbox_authority_identity_immutable BEFORE UPDATE ON entitlement_outbox
WHEN NEW.authority_id IS NOT OLD.authority_id OR NEW.authority_key_id IS NOT OLD.authority_key_id OR
 NEW.authority_generation IS NOT OLD.authority_generation OR NEW.authority_public_key_sha256 IS NOT OLD.authority_public_key_sha256 OR
 NEW.authority_attestation IS NOT OLD.authority_attestation OR NEW.authority_identity_status IS NOT OLD.authority_identity_status
BEGIN SELECT RAISE(ABORT,'authority signer identity is immutable'); END;

CREATE TRIGGER revocation_outbox_authority_identity_required BEFORE INSERT ON revocation_outbox
WHEN NEW.authority_key_id IS NULL OR NEW.authority_generation IS NULL OR NEW.authority_public_key_sha256 IS NULL OR
 NEW.authority_attestation IS NULL OR NEW.authority_identity_status!='verified'
BEGIN SELECT RAISE(ABORT,'authority signer identity required'); END;
CREATE TRIGGER revocation_outbox_authority_identity_immutable BEFORE UPDATE ON revocation_outbox
WHEN NEW.authority_key_id IS NOT OLD.authority_key_id OR NEW.authority_generation IS NOT OLD.authority_generation OR
 NEW.authority_public_key_sha256 IS NOT OLD.authority_public_key_sha256 OR NEW.authority_attestation IS NOT OLD.authority_attestation OR
 NEW.authority_identity_status IS NOT OLD.authority_identity_status
BEGIN SELECT RAISE(ABORT,'authority signer identity is immutable'); END;

CREATE TRIGGER entitlement_outbox_authority_ack_once BEFORE UPDATE ON entitlement_outbox
WHEN OLD.authority_ack_signature IS NOT NULL AND NEW.authority_ack_signature IS NOT OLD.authority_ack_signature
BEGIN SELECT RAISE(ABORT,'authority acknowledgement is immutable'); END;
CREATE TRIGGER revocation_outbox_authority_ack_once BEFORE UPDATE ON revocation_outbox
WHEN OLD.authority_ack_signature IS NOT NULL AND NEW.authority_ack_signature IS NOT OLD.authority_ack_signature
BEGIN SELECT RAISE(ABORT,'authority acknowledgement is immutable'); END;

CREATE TRIGGER entitlement_outbox_delivered_ack_required BEFORE UPDATE ON entitlement_outbox
WHEN NEW.state='delivered' AND (NEW.license_id IS NULL OR NEW.delivery_receipt IS NULL OR length(NEW.delivery_receipt)!=64 OR NEW.authority_ack_signature IS NULL OR length(NEW.authority_ack_signature)!=88)
BEGIN SELECT RAISE(ABORT,'delivered authority acknowledgement required'); END;
CREATE TRIGGER revocation_outbox_delivered_ack_required BEFORE UPDATE ON revocation_outbox
WHEN NEW.state='delivered' AND (NEW.license_id IS NULL OR NEW.authority_receipt IS NULL OR length(NEW.authority_receipt)!=64 OR NEW.authority_ack_signature IS NULL OR length(NEW.authority_ack_signature)!=88 OR NEW.authority_revoked_at IS NULL OR NEW.authority_request_digest IS NULL)
BEGIN SELECT RAISE(ABORT,'delivered authority acknowledgement required'); END;
CREATE TRIGGER revocation_outbox_authority_result_once BEFORE UPDATE ON revocation_outbox
WHEN (OLD.authority_revoked_at IS NOT NULL AND NEW.authority_revoked_at IS NOT OLD.authority_revoked_at) OR
 (OLD.authority_request_digest IS NOT NULL AND NEW.authority_request_digest IS NOT OLD.authority_request_digest)
BEGIN SELECT RAISE(ABORT,'authority revocation result is immutable'); END;

CREATE TRIGGER entitlement_outbox_reconciliation_protocol BEFORE UPDATE ON entitlement_outbox
WHEN
 (OLD.reconciliation_phase='none' AND NEW.reconciliation_phase!='none' AND NOT(NEW.reconciliation_phase='crossing_prepared' AND NEW.state='leased' AND NEW.lease_owner IS NOT NULL AND NEW.authority_identity_status='verified')) OR
 (OLD.reconciliation_phase='crossing_prepared' AND NEW.reconciliation_phase NOT IN('crossing_prepared','crossing_authorized','none')) OR
 (OLD.reconciliation_phase='crossing_prepared' AND NEW.reconciliation_phase='crossing_authorized' AND NOT(OLD.state='leased' AND NEW.state='leased' AND OLD.lease_owner IS NEW.lease_owner AND NEW.lease_owner IS NOT NULL AND OLD.fencing_version=NEW.fencing_version)) OR
 (OLD.reconciliation_phase='crossing_prepared' AND NEW.reconciliation_phase='none' AND NOT(NEW.state='quarantined' AND NEW.lease_owner IS NULL)) OR
 (OLD.reconciliation_phase='crossing_authorized' AND NEW.reconciliation_phase NOT IN('crossing_authorized','readback_only')) OR
 (OLD.reconciliation_phase='readback_only' AND NEW.reconciliation_phase NOT IN('readback_only','manual_review')) OR
 (OLD.reconciliation_phase='readback_only' AND NEW.reconciliation_phase='manual_review' AND NEW.attempt_count<8) OR
 (OLD.reconciliation_phase='manual_review' AND NEW.reconciliation_phase!='manual_review')
BEGIN SELECT RAISE(ABORT,'invalid reconciliation phase transition'); END;
CREATE TRIGGER entitlement_outbox_prepared_lease_immutable BEFORE UPDATE ON entitlement_outbox
WHEN OLD.reconciliation_phase='crossing_prepared' AND NEW.reconciliation_phase='crossing_prepared' AND
 (NEW.state IS NOT OLD.state OR NEW.lease_owner IS NOT OLD.lease_owner OR NEW.lease_expires_at IS NOT OLD.lease_expires_at OR NEW.fencing_version!=OLD.fencing_version)
BEGIN SELECT RAISE(ABORT,'prepared crossing lease is immutable'); END;
