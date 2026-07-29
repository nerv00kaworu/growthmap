-- Signed revocations are immutable issuer evidence and are included in the
-- authenticated issuance checkpoint closure. One license has one terminal
-- assertion in v1; idempotent revoke returns the same bytes.
CREATE TABLE revocation_assertions(
 license_id TEXT PRIMARY KEY,
 order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
 sequence INTEGER NOT NULL CHECK(sequence>=1),
 revoked_at TEXT NOT NULL,
 reason_code TEXT CHECK(reason_code IS NULL OR reason_code IN('refund','chargeback','fraud','terms_violation','administrative')),
 assertion_json TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL
);
CREATE TRIGGER revocation_assertion_no_update BEFORE UPDATE ON revocation_assertions
BEGIN SELECT RAISE(ABORT,'revocation assertion is immutable'); END;
CREATE TRIGGER revocation_assertion_no_delete BEFORE DELETE ON revocation_assertions
BEGIN SELECT RAISE(ABORT,'revocation assertion is immutable'); END;
