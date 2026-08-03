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

## R1 external signer ceremony source seam (2026-08-02)

`LicenseAuthority.from_external_signer(...)` is the sole production construction seam. It accepts an opaque Ed25519 signature-only provider, separately reviewed public PEM/DER bytes, the exact strict ceremony descriptor, and an external atomic monotonic generation anchor. No HTTP request, renderer value, or raw environment secret participates. The Authority verifies every returned 64-byte signature against the reviewed public key before certificate persistence, pins append-only local ceremony metadata, and checks DB/anchor consistency before every activation signature. Code or DB rollback cannot authorize a lower generation while the external anchor remains authoritative.

The descriptor fixes schema 1, purpose `growthmap-license-authority-signing`, domain `growthmap-activation-certificate-v2`, algorithm `Ed25519`, canonical authority/key identifiers, positive generation, exact predecessor (`null` only for generation 1, otherwise generation − 1), canonical UTC activation with no future tolerance, exact lowercase SHA-256 of the supplied reviewed public-key bytes, and a bounded non-secret provider attestation ID. Unknown/missing fields and bool integers fail closed. Handshake adds only this non-secret signer identity; certificate v2 remains unchanged.

This source seam is **not** a real ceremony. Production HSM/KMS custody, two-person approval, independently matching the packaged desktop public key, durable anchor provisioning/monitoring/recovery, and signed Windows packaged E2E remain **BLOCKED_EXTERNAL**. `OfflineFixtureMonotonicAnchor` and the file-key constructor are explicitly isolated temporary-test/candidate fixtures, never production inputs.

The Authority preflights the local append-only transition before advancing the external anchor, reducing avoidable split-state failures. Each atomic anchor claim binds the positive generation and exact lowercase SHA-256 of the canonical ceremony descriptor bytes; reads return that same strict exact-field claim. Idempotency applies only to an identical generation+digest claim. It cannot make SQLite and an external HSM/KMS anchor atomic: if the anchor advances and the subsequent DB pin fails, every prior process immediately fails handshake/signing by claim identity. A later process may recover forward and pin only the exact already-claimed descriptor; a different descriptor/key at that generation fails closed permanently. Operators must quarantine the Authority, preserve both states, recover the DB to the claimed reviewed ceremony under the production runbook, and never decrement/reuse the anchor generation. Raw signer/anchor exceptions are cause-suppressed at the boundary so provider diagnostics cannot enter traceback logging or responses.

## Payment-source signer binding

External entitlement and revocation inbox rows persist the complete accepted signer identity (`authority_id`, `key_id`, generation, reviewed-public-key SHA-256, provider attestation). Idempotent request digests and deterministic receipts include that identity, so response-loss replay under a different generation is a contradiction rather than an implicit rotation. Payment outbox work is generation-pinned; a later Authority generation cannot silently take over old work. Provider attestation is treated as an immutable exact ceremony label in this v1 policy, not as dynamically refreshed provider status.

The repository has not independently compared this reviewed public-key digest with the public key inside an effective signed desktop package. That ceremony-to-package match remains an external release gate and is not inferred from fixture keys or source files.

Authority exposes read-only durable entitlement/revocation acknowledgement methods. They read the immutable inbox record, require its stored signer identity to equal the active exact ceremony identity, and fail `legacy_identity_unproven` for pre-binding NULL rows. Payment verifies these readbacks and canonical receipts before acknowledging delivery; handshake/operation/readback identity changes fail closed.

Durable Authority acknowledgement payloads use separate `growthmap-entitlement-authority-ack-v1\0` and `growthmap-revocation-authority-ack-v1\0` Ed25519 domains. Signature bytes are stored immutably with Authority inbox evidence and payment outbox acceptance. Legacy NULL signatures are `legacy_identity_unproven`. This cryptographically authenticates exact local acknowledgement payloads but does not replace production authenticated transport/service authorization or effective signed-package key comparison.

Response loss is recovered from immutable source/source-id by signed inbox readback, not assumed from operation return. Missing legacy or current acknowledgement remains reconciliation/manual-alert work; it is not terminal evidence. Delivered payment rows require acknowledgement signatures and fast-path verification.

Payment's pre-crossing durable phase distinguishes “definitely not crossed” from “may be committed.” Once the latter is recorded, all recovery is immutable-source signed readback only; neither restart nor refund can cause another create. Manual-review exhaustion remains an explicit active ambiguity requiring operator reconciliation.

The external call is authorized only after Payment's `crossing_authorized` checkpoint. This is not atomic with the remote service: a later refund is a durable compensation request, not proof that no entitlement can exist. Signed readback and revocation close that interval; production service authorization remains external.

Crash recovery after local crossing authorization never repeats create: the successor transitions the durable phase to readback-only and queries the signed Authority inbox. This applies whether the order is still payment-confirmed or has a compensation-required refund.
