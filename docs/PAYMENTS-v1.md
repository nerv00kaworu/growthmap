# GrowthMap Payments v1 candidate

Status: local candidate; **not production deployable**. Product: one perpetual personal major-1 license, unlimited active projects, issuer-targeted two devices, same-major updates included.

## Price, inventory, and race semantics

The first 50 globally **payment-confirmed** sales across x402 and PayPal receive ordinal 1–50 and cost 10 USDC / USD 10. Ordinal 51 onward costs 29. Pending, expired, rejected, cancelled and refunded-before-confirmation claims do not allocate an ordinal. Checkout creates a short quote (default 5 minutes) but reserves no stock. `BEGIN IMMEDIATE`, a process lock, unique proof/transaction/ordinal constraints and `confirm_payment_and_allocate_sale` serialize allocation and issuance.

At confirmation the current tier is recalculated. If quote, authorization, attested amount, currency or tier differs, the order enters `manual_review`; it is not issued. The x402 adapter verifies before settlement while holding the candidate serialization lock; a stale 10U authorization after slot 50 is rejected before settlement and must be requoted. Settlement ambiguity enters manual review and is never automatically retried. This is safe for one process; production multi-instance deployment requires the official SDK/facilitator transaction and distributed/database locking review.

## x402

`POST /v1/orders` creates the order; `POST /v1/orders/{id}/purchase` without `PAYMENT-SIGNATURE` returns 402 plus base64 JSON in `PAYMENT-REQUIRED`, protocol v2, exact scheme, CAIP-2 `eip155:8453`, 6-decimal amount `10000000` or `29000000`, and payee. Native USDC is pinned to Circle's Base address `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` ([Circle contract list](https://developers.circle.com/stablecoins/usdc-contract-addresses), verified 2026-07-28). Requirements bind order, product, major, amount, network, asset and recipient. Replay IDs/payment proofs/transactions are unique. Client tx hashes alone are never trusted.

Only deterministic `MockFacilitator` exists. Real CDP/official SDK verify+settle types/API are an explicit production blocker; this candidate does not invent them. Recipient placeholder fails startup. Human wallets open an HTTPS portal/WalletConnect seam; the desktop never receives keys or fabricates x402 headers.

## PayPal runbook

Buyer opens configured Goods & Services/invoice URL, creates a PayPal order, then submits transaction ID, normalized email and license name. No file/screenshot endpoint exists. An authenticated admin opens PayPal directly and confirms transaction ID, completed status, exact USD amount, and intended payee; records those attestation fields; then confirms or rejects. Duplicate transaction IDs fail. No PayPal API or automatic verification is claimed. Refund/revoke/reissue operations must append audit state and preserve records.

## Issuer, recovery, and states

States: `pending_payment`, `payment_confirmed`, `license_issued`, `manual_review`, `rejected`, `expired`, `refunded`, `revoked`. Ed25519 JSON is exactly compatible with `src/backend/desktop/entitlements.py`; private material is loaded only from an explicit file/key-provider seam and never committed. Production fails without it. License download is explicit and desktop import cryptographically verifies it. Recovery uses public recovery code or normalized email behind a rate-limit seam; responses must avoid account enumeration.

Refund/revocation never deletes evidence. Offline licenses remain usable until the desktop imports/checks in and verifies a signed revocation assertion. That limitation must remain visible.

## Security, privacy, audit, operations

Admin auth is fail-closed with no default secret, exact origin + CSRF checks and a stored hash seam (production should use reviewed Argon2id/session infrastructure). Order/recovery/admin rate limiting is an integration seam. Email is normalized; audit data uses email/proof hashes and must not log raw secrets, private keys or license signatures. Audit events are append-only hash chained and tamper-checkable. External payloads are retained only as hashes.

SQLite is separate from every desktop DB, WAL enabled, FK/busy timeout enabled, schema `PRAGMA user_version=1`. Back up using SQLite online backup or quiesce writes and consistently preserve DB/WAL; encrypt, access-control, integrity-check and restore-test. Apply only reviewed forward migrations.

## Production blockers

Official x402/CDP SDK facilitator; production Base recipient; secure HSM/KMS/offline Ed25519 provider and matching packaged public key; real HTTPS payment API + purchase portal/WalletConnect; PayPal merchant/invoice URL and reviewed admin operations; Argon2id/session/CSRF/rate limiting; email/recovery delivery; monitoring, reconciliation, backups and privacy retention; signed revocation/check-in; legal approval; Windows signed package/E2E. Placeholders intentionally fail commercial preflight.
