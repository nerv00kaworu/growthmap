# GrowthMap payments v1 candidate — 2026-07-28

Documented baseline `3023e16`; implemented without rewriting later clean commits on current `5941384`. No live desktop DB, production credential/private key, real money, external provider write, commit, push, tag or release.

## Delivered

- Separate WAL SQLite v1 ledger/migration, cross-rail atomic ordinal/price/issuance path, unique proofs/transactions/ordinals, normalized email and public recovery-code hash, hash-chain audit.
- Canonical Ed25519 major-1 personal license compatible with desktop verifier; test keys generated only in temporary tests.
- x402 v2 exact challenge on Base `eip155:8453`, Circle native USDC, 10/29 million base units, fail-closed payee, requirements binding, deterministic mock facilitator and stale-tier verify-before-settle policy.
- Manual PayPal claim/admin attestation boundary with no screenshot evidence and no false API-verification claim.
- Desktop two-rail purchase panel, explicit HTTPS portal/PayPal external-open IPC, no wallet keys/headers, explicit verified license import.
- Commercial config schema v2, packaged-env isolation retained, payment trust fields/placeholders and E2E schema evolved.
- `docs/PAYMENTS-v1.md`, commercialization amendment, service ops notes.

## Verification

- Payment: **4 passed** (mixed x402/PayPal 60-way confirms => exactly ordinals 1–50 issued, ten stale quotes reviewed; exact challenge/errors/replay; PayPal auth/attestation; desktop signature; audit tamper).
- Backend (correct `src/backend` cwd): **53 passed**, one upstream deprecation warning.
- Frontend lint/typecheck/build: **PASS**.
- CSP generate then desktop: **79 passed**; npm audit: **0 vulnerabilities**.
- `git diff --check`: recorded separately at final check.
- Windows package/ASAR/resources/AuthentiCode/E2E: **pending parent/fresh Windows review**.

## Honest gaps

Candidate HTTP surface does not yet include complete list/reject/refund/revoke/reissue/recovery handlers or production rate limiter/session implementation; core states/schema and documented seams exist. Real x402 facilitator and PayPal API are intentionally absent. Single-process lock must not be represented as multi-instance safe. Signed revocation assertion/check-in remains blocked. See docs for all production blockers.
