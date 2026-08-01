# GrowthMap License Issuance & Device Activation v1 (Phase 1)

## Scope and status

Phase 1 is payment-independent. It proves that an administrator can create an entitlement identity, activate at most two random installation identities, and import a signed per-device certificate which the pinned desktop key verifies before authoring is unlocked. It does **not** implement checkout, x402, PayPal, payment evidence, or any transaction.

The authority implementation (`src/backend/licensing/authority.py`) is an API/service candidate, not a public deployment. Its current file-key constructor is isolated-test/candidate infrastructure; production must inject an external signer provider and must fail closed if the provider, declared key ID/generation, or matching reviewed public-key digest is missing. Provider methods return signatures only: private bytes must never enter the repository, desktop, payment service, DB, response, or logs. Tests generate explicitly isolated temporary fixture keys; they are not production inputs.

The production key ceremony contract is: independently approve issuer purpose/domain, algorithm, key ID, monotonically increasing generation, activation time, predecessor generation, and public-key SHA-256; bind that exact public key into signed release metadata and the runtime ASAR path; require two-person approval before enabling the signer; record a non-secret provider attestation and rollback-resistant generation anchor; disable the predecessor only after genuine Windows verification and recovery rehearsal. Rotation may move only to a higher approved generation. A lower/unknown generation, key-ID/public-key mismatch, unavailable signer, or restored stale metadata blocks issuance. Emergency rollback restores code but never decrements key generation; compromised keys require revocation/reissue procedure, not silent reuse.

## Canonical documents

Activation request signature domain: `growthmap-activation-request-v1\0`. The device signs canonical UTF-8 JSON containing `device_public_key`, `license_id`, and a fresh nonce. The device ID is `gmdev_` plus SHA-256 of the raw Ed25519 public key. The server stores that irreversible ID and public key; GrowthMap does not read hardware serial numbers.

Activation certificate schema v2 is exact-field/strict JSON and signed over `growthmap-activation-certificate-v2\0` plus canonical JSON excluding `signature`. It identifies product, entitlement, activation, major version, allowance, device ID/public key, issue/expiry/revocation/check-in timestamps and limits. Only a valid v2 certificate matching the safeStorage-backed local private identity is writable.

Legacy schema v1 remains verifiable only as a migration/bootstrap signal and is read-only (`legacy_bootstrap_required`). It cannot permanently unlock writes.

## Seat ledger and recovery boundary

SQLite uses a license row, unique `(license_id, device_id)` activation row, active-seat transaction under `BEGIN IMMEDIATE`, and append-only audit events. Same-device retry returns the same stored certificate and consumes no seat. A third active device is rejected. Deactivation frees a seat. **Deployment must authenticate the license owner or administrator before create/deactivate/recovery operations**; this module intentionally does not pretend local possession proves that authority.

## Desktop security

Electron generates a random Ed25519 installation identity and encrypts PKCS8 private material with `safeStorage`; only the public key is passed to the local sidecar. An expected marker makes deletion/tamper fail closed instead of silently generating a different identity while a certificate exists. Import rejects symlinks/non-files, files over 64 KiB, duplicate/case-colliding JSON keys, invalid signatures, wrong major/device, and valid-license substitution before atomic replacement. Duplicate import is deterministic. Existing valid entitlement bytes survive rejected imports.

## Production deployment gates (not solved here)

- HSM/KMS-backed signing provider, rotation ceremony, separated issuer and revocation keys.
- Authenticated/authorized issuance, activation, deactivation and recovery API; rate limiting and abuse controls.
- TLS, production database with durable transactions, backups, HA, audit export/monitoring and rollback protection.
- Server-side freshness/revocation delivery and an external trusted time/rollback anchor. Local DB + safeStorage cannot prove global rollback resistance.
- Recovery design for OS reinstall/lost safeStorage that cannot be used to steal seats.
- Windows signed packaged E2E on a Windows runner. Linux packaged gates do not constitute Windows PASS.

The global two-seat guarantee exists only while the authority ledger is authoritative and rollback-resistant. Offline JSON by itself cannot enforce a global seat count.

## Startup possession and verifier error contract

Every paid startup uses a new random nonce and startup-session value. Electron signs the canonical `growthmap-device-startup-v1` challenge with the safeStorage private key. The session-token HMAC covers mode, public key, nonce, session and proof. The sidecar verifies HMAC and Ed25519 possession before evaluating the matching certificate; a copied certificate plus attacker-set environment public key is extraction-only. A proof from an earlier session cannot authorize a new session.

Verifier error precedence is stable: exact shape and basic primitive types are checked first; signature authenticity precedes detailed signed semantic constraints; then device binding, major, expiry/revocation and check-in policy are enforced. Canonical signed semantic tampering therefore reports signature failure rather than providing a bypass.

The installation identity is one safeStorage-encrypted, atomically replaced container in a real 0700 directory, written 0600 with no-follow creation plus file/directory fsync. Electron's single-instance lock is the cross-process serialization assumption. Deleting identity while a certificate exists fails closed. Atomic local storage still has no OS monotonic rollback anchor; paired rollback remains a production blocker.

Activation request consumption is append-only: each combined license/device/nonce/proof digest has a unique ledger row. Deactivation marks that request consumed but never deletes or overwrites it, so later activations cannot make an old request reusable. Reservation, seat check, certificate, activation row and audit commit in one `BEGIN IMMEDIATE` transaction.

Desktop stable readers bound identity/license files to 64 KiB, require a regular single-link file, read exact bytes from one descriptor, and verify descriptor identity afterward. POSIX uses `O_NOFOLLOW`; platforms without it additionally require non-symlink `lstat`, canonical real path equality, and post-open identity checks. Windows reparse-point behavior still requires the signed Windows packaged reparse regression gate and is not inferred from Linux results. Backend POSIX import uses descriptor-bound reads plus a directory-fd anchored temporary create and replace; Windows uses conservative prechecks because Python does not expose equivalent dirfd replacement there, and remains covered by the same Windows gate.
