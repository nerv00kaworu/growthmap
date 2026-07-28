# GrowthMap Payments v1 candidate

Status: local candidate; **not production deployable**. Product: one perpetual personal major-1 license, unlimited active projects, issuer-targeted two devices, same-major updates included.

## Price, inventory, and race semantics

The first 50 globally **payment-confirmed** sales across x402 and PayPal receive ordinal 1–50 and cost 10 USDC / USD 10. Ordinal 51 onward costs 29. Pending, expired, rejected, cancelled and refunded-before-confirmation claims do not allocate an ordinal. Checkout creates a short quote (default 5 minutes) but reserves no stock. `BEGIN IMMEDIATE`, unique proof/transaction/ordinal constraints and durable settlement intents serialize allocation and issuance across service instances; process locks are not authority.

At confirmation the current tier is recalculated. If quote, authorization, attested amount, currency or tier differs, the order enters `manual_review`; it is not issued. After verification, the ledger durably reserves one current-tier ordinal before external settlement; a stale 10U authorization after slot 50 is rejected before any intent or settlement. Settlement ambiguity preserves the intent and enters manual review, with no blind retry. SQLite transactions are authoritative across candidate service instances; production still requires official SDK/facilitator and deployment-topology review.

## x402

`POST /v1/orders` creates the order; `POST /v1/orders/{id}/purchase` without `PAYMENT-SIGNATURE` returns 402 plus base64 JSON in `PAYMENT-REQUIRED`, protocol v2, exact scheme, CAIP-2 `eip155:8453`, 6-decimal amount `10000000` or `29000000`, and payee. Native USDC is pinned to Circle's Base address `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` ([Circle contract list](https://developers.circle.com/stablecoins/usdc-contract-addresses), verified 2026-07-28). Requirements bind order, product, major, amount, network, asset and recipient. Replay IDs/payment proofs/transactions are unique. Client tx hashes alone are never trusted.

Only deterministic `MockFacilitator` exists. Real CDP/official SDK verify+settle types/API are an explicit production blocker; this candidate does not invent them. Recipient placeholder fails startup. Human wallets open an HTTPS portal/WalletConnect seam; the desktop never receives keys or fabricates x402 headers.

## PayPal runbook

Buyer opens configured Goods & Services/invoice URL, creates a PayPal order, then submits transaction ID, normalized email and license name. No file/screenshot endpoint exists. An authenticated admin opens PayPal directly and confirms transaction ID, completed status, exact USD amount, and intended payee; records those attestation fields; then confirms or rejects. Duplicate transaction IDs fail. No PayPal API or automatic verification is claimed. Refund/revoke operations append audit state and preserve records. Reissue is not implemented.

## Issuer, recovery, and states

States: `pending_payment`, `payment_confirmed`, `license_issued`, `manual_review`, `rejected`, `expired`, `refunded`, `revoked`. Ed25519 JSON is exactly compatible with `src/backend/desktop/entitlements.py`; private material is loaded only from an explicit file/key-provider seam and never committed. Production fails without it. License download is explicit and desktop import cryptographically verifies it. Recovery uses a high-entropy public recovery code behind an enforced rate limiter; email recovery is unsupported until authenticated delivery exists. Responses avoid account enumeration.

Refund/revocation never deletes evidence. Offline licenses remain usable until the desktop imports/checks in and verifies a signed revocation assertion. That limitation must remain visible.

## Security, privacy, audit, operations

Candidate admin auth uses configured exact origin, CSRF and constant-time test-session verification with no defaults. Production startup is unconditionally blocked until reviewed Argon2id session infrastructure is integrated. Order/recovery/admin rate limiting is an integration seam. Email is normalized; audit data uses email/proof hashes and must not log raw secrets, private keys or license signatures. Audit events are append-only hash chained and tamper-checkable. External payloads are retained only as hashes.

SQLite is separate from every desktop DB, WAL enabled, FK/busy timeout enabled, current schema `PRAGMA user_version=6` (preserved baseline migration 001 plus checksum-pinned forward migrations 002–006). Back up using SQLite online backup or quiesce writes and consistently preserve DB/WAL; encrypt, access-control, integrity-check and restore-test. Apply only reviewed forward migrations.

## Production blockers

Official x402/CDP SDK facilitator; production Base recipient; secure HSM/KMS/offline Ed25519 provider and matching packaged public key; real HTTPS payment API + purchase portal/WalletConnect; PayPal merchant/invoice URL and reviewed admin operations; Argon2id/session/CSRF/rate limiting; email/recovery delivery; monitoring, reconciliation, backups and privacy retention; signed revocation/check-in; legal approval; Windows signed package/E2E. Placeholders intentionally fail commercial preflight.

## Remediation clarification

`quoted_amount_minor` is rail-specific smallest units: 6-decimal micro-USDC for x402 and USD cents for PayPal. x402 durable `settlement_intents` reserve the ordinal under `BEGIN IMMEDIATE` before external settlement; a crash/timeout becomes durable `ambiguous` + `manual_review` and operators reconcile without automatic retry. The mock uses a nested test authorization envelope and is **not official protocol compatibility evidence**. Audit rows are protected by UPDATE/DELETE triggers. Reissue and signed revocation assertion endpoints do not exist and remain production blockers.

## Evidence reconciliation and migrations

Schema `001_payments_v1.sql` is preserved byte-for-byte from the original candidate (SHA-256 `311bc81c68f1fc7f63ec27c309600b8ac852774ee7f535a5783bc2dc625ca28d`). Forward migration 002 table-copies orders, converting candidate PayPal micro-USD integers to USD cents, adds a checksum ledger and durable evidence fields. Unknown versions or checksum drift fail startup.

Expired intents become ambiguous and keep inventory reserved. Only an authenticated reconciliation operation backed by an injected adapter may resolve them: immutable paid evidence records exact transaction/proof/nonce/order/source/finality before idempotent issuance; final unpaid evidence after the adapter's finality window transitions to `cancelled_unpaid` and releases the ordinal atomically. Admin assertion alone cannot resolve an intent. There is no production reconciler or automatic production reconciliation. Mock facilitator/reconciler use requires explicit isolated test opt-in and is not official x402 compatibility.

Migration SQL, `user_version`, and checksum-ledger rows commit atomically per migration; existing v2+ databases fail closed if the ledger is missing, empty, or tampered. Migration 002 rebuilds both FK child tables (`payment_proofs`, `external_events`) alongside `orders`; migration 003 adds unique evidence identity plus a canonical binding over intent, order, proof, nonce, transaction, source, finality, outcome, and evidence hash. Startup finalizes already-recorded settled evidence idempotently without calling a provider, while ambiguous evidence still requires the trusted reconciler.

Every HTTP response, including generic non-leaking unhandled 500s, carries `Cache-Control: no-store`. Windows packaging extracts and scans complete app-owned files regardless of suffix or size. Packaged `node_modules` is an explicit third-party subtree verified file-by-file against the lock-installed dependency inventory, preventing payment/issuer/key/SQLite payloads from hiding under blanket exclusions.


Historical schema v4 authenticated terminal settlement evidence with HMAC-SHA256 using a dedicated external secret loaded only from `GROWTHMAP_SETTLEMENT_MAC_KEY_FILE` (minimum 32 bytes). The key is not stored in SQLite, logs, APIs, licenses, desktop artifacts, or packages. Loss of this key makes durable evidence unrecoverable and startup fails closed; key rotation requires a separately reviewed atomic re-MAC migration and is intentionally out of scope. Terminal settlement rows are database-trigger immutable except the evidence-preserving `settled` → `finalized_paid` transition. Release remains **NO-GO pending fresh independent review and Windows package-verifier CI**.

## R6 authenticated issuance boundary
The threat model assumes an attacker can arbitrarily read/write SQLite rows and schema, including dropping triggers/indexes/tables, but cannot read or modify the external MAC key/checkpoint. R6 checkpoint v2 authenticates the canonical security-schema manifest plus all rows of `orders`, `payment_proofs`, `external_events`, `settlement_intents`, `audit_events`, `migration_ledger`, and `terminal_checkpoint_state`. This is the issuance closure for confirmation, recovery/license exposure, early ordinals, provider evidence, manual review, refunds/revocations and audit anchors. It is verified on startup and before protected reads/mutations/allocation; triggers remain defense in depth. Current DB edits/deletes/inserts and relevant schema drift fail closed. It **does not** solve replay of a historical matching DB+checkpoint pair; production needs an OS/HSM monotonic counter or equivalent and remains blocked until one is integrated.

Migrations v5 and v6 quarantine legacy terminal rows and their orders to `ambiguous`/`manual_review`; it never converts legacy evidence into authenticated truth. Only a future trusted external reconciler may re-verify them. Missing/mismatched checkpoint or key fails closed. `GROWTHMAP_SETTLEMENT_CHECKPOINT_FILE` supplies only the checkpoint path; secret bytes remain file-loaded through `GROWTHMAP_SETTLEMENT_MAC_KEY_FILE`.

The Windows job freezes every file path/hash and package root from the clean `desktop/npm ci`, plus package/lock hashes, into a job-external read-only manifest and separately captures its digest before scripts/build. The final ASAR dependency tree may be a pruned subset, but every packaged byte must appear in that frozen clean-install inventory; the mutable installed tree must remain exact. This proves continuity from that CI install, not registry provenance or reproducible builds.


### Legacy migration semantics
A direct populated v4→v6 upgrade deliberately does not authenticate v4 evidence as current truth: v5 first transforms every terminal row/order to `ambiguous`/`manual_review`, then v6 establishes checkpoint v2 only over that quarantined state. Thus even forged v4 terminal evidence is never issued. A pre-existing v5 database must first pass its authenticated v1 terminal checkpoint; v6 then quarantines terminal evidence before establishing the full closure. Tests construct real checksum-ledger v4 and v5 databases and verify migration, reopen/idempotence, FK/integrity and absence of auto-issuance.
