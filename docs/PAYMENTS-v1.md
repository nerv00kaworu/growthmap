# GrowthMap Payments v1 candidate

Status: local candidate; **not production deployable**. Product: one perpetual personal major-1 license, unlimited active projects, issuer-targeted two devices, same-major updates included.

## Price, inventory, and race semantics

The first 50 globally **payment-confirmed** sales across x402 and PayPal receive ordinal 1–50 and cost 10 USDC / USD 10. Ordinal 51 onward costs 29. Pending, expired, rejected, cancelled and refunded-before-confirmation claims do not allocate an ordinal. Checkout creates a short quote (default 5 minutes) but reserves no stock. `BEGIN IMMEDIATE`, unique proof/transaction/ordinal constraints and durable settlement intents serialize allocation and issuance across service instances; process locks are not authority.

At confirmation the current tier is recalculated. If quote, authorization, attested amount, currency or tier differs, the order enters `manual_review`; it is not issued. After verification, the ledger durably reserves one current-tier ordinal before external settlement; a stale 10U authorization after slot 50 is rejected before any intent or settlement. Settlement ambiguity preserves the intent and enters manual review, with no blind retry. SQLite transactions are authoritative across candidate service instances; production still requires official SDK/facilitator and deployment-topology review.

## x402

`POST /v1/orders` creates the order; `POST /v1/orders/{id}/purchase` without `PAYMENT-SIGNATURE` returns 402 plus base64 JSON in `PAYMENT-REQUIRED`, protocol v2, exact scheme, CAIP-2 `eip155:8453`, 6-decimal amount `10000000` or `29000000`, and payee. Native USDC is pinned to Circle's Base address `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` ([Circle contract list](https://developers.circle.com/stablecoins/usdc-contract-addresses), verified 2026-07-28). Requirements bind order, product, major, amount, network, asset and recipient. Replay IDs/payment proofs/transactions are unique. Client tx hashes alone are never trusted.

A candidate `OfficialX402Facilitator` adapter for the pinned x402 2.17 contract exists alongside the deterministic isolated-test `MockFacilitator`. It deliberately does not claim production readiness: production credentials, a real recipient/endpoint, authenticated receipt/finality reconciliation, deployment review and live smoke evidence remain blockers. Recipient placeholders fail startup. Human wallets open an HTTPS portal/WalletConnect seam; the desktop never receives keys or fabricates x402 headers.

## PayPal runbook

Buyer opens configured Goods & Services/invoice URL, creates a PayPal order, then submits transaction ID, normalized email and license name. No file/screenshot endpoint exists. An authenticated admin opens PayPal directly and confirms transaction ID, completed status, exact USD amount, and intended payee; records those attestation fields; then confirms or rejects. Duplicate transaction IDs fail. No PayPal API or automatic verification is claimed. Refund/revoke operations append audit state and preserve records. Reissue is not implemented.

## Issuer, recovery, and states

States: `pending_payment`, `payment_confirmed`, `license_issued`, `manual_review`, `rejected`, `expired`, `refunded`, `revoked`. Ed25519 JSON is exactly compatible with `src/backend/desktop/entitlements.py`; private material is loaded only from an explicit file/key-provider seam and never committed. Production fails without it. License download is explicit and desktop import cryptographically verifies it. Recovery uses a high-entropy public recovery code behind an enforced rate limiter; email recovery is unsupported until authenticated delivery exists. Responses avoid account enumeration.

Refund/revocation never deletes evidence. Offline licenses remain usable until the desktop imports/checks in and verifies a signed revocation assertion. That limitation must remain visible.

## Security, privacy, audit, operations

Candidate admin auth uses configured exact origin, CSRF and constant-time test-session verification with no defaults. Production startup is unconditionally blocked until reviewed Argon2id session infrastructure is integrated. Order/recovery/admin rate limiting is an integration seam. Email is normalized; audit data uses email/proof hashes and must not log raw secrets, private keys or license signatures. Audit events are append-only hash chained and tamper-checkable. External payloads are retained only as hashes.

SQLite is separate from every desktop DB, WAL enabled, FK/busy timeout enabled, current schema `PRAGMA user_version=9` (preserved baseline migration 001 plus checksum-pinned forward migrations 002–009). Back up using SQLite online backup or quiesce writes and consistently preserve DB/WAL; encrypt, access-control, integrity-check and restore-test. Apply only reviewed forward migrations.

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

## R7 signed revocation/check-in candidate

Schema 7 adds immutable `revocation_assertions` to the checkpoint-authenticated issuance closure. Revoke signs exact canonical JSON (`sort_keys`, UTF-8, compact separators) with Ed25519 over `growthmap-revocation-v1\0 || JSON`, separate from license signatures. Assertions bind schema/type/product, product major, license ID, UTC revocation time, monotonically increasing sequence, and reason (`refund`, `chargeback`, `fraud`, `terms_violation`, `administrative`, or null). The v1 administrative transition creates sequence 1 once; retries return byte-identical evidence. Recovery for revoked orders returns no license and may return this candidate assertion; all responses remain `no-store`. This is not a production network availability promise.

New licenses contain a signed `next_check_in_at` 30 days after issue. Paid writes fail closed after that instant (including while offline) until a future candidate check-in refreshes the signed license; wall-clock rollback cannot extend the signed deadline. Trials and no-license/extraction paths do not inherit this check-in requirement. This bounded model explicitly does not promise permanent-offline revocation.

Electron imports an assertion only after sidecar signature/schema/license/major validation, then atomically writes the assertion and an OS-safeStorage-encrypted digest/sequence receipt. Startup compares both: deletion, rollback, or tamper becomes extraction mode where durable receipt/assertion evidence remains. `safeStorage` availability is mandatory. OS credential-store rollback together with file rollback remains outside existing primitives and is a production blocker requiring an OS/HSM monotonic counter. The candidate intentionally exposes file import rather than automatic network check-in.

Legacy schema-v1 licenses without `next_check_in_at` are signature-verified without altering their signed bytes, then receive a separate safeStorage-authenticated first-observation deadline of at most 30 days. The first observation uses local trusted application observation time, never `issued_at`. Paid-clock observations are checkpointed even when the signed license is already check-in-expired, so moving the clock forward and then backward cannot reactivate it. Revocation timestamps use canonical UTC `YYYY-MM-DDTHH:MM:SS[.ffffff]Z`, may be at most five minutes ahead of observation, and cannot precede license issuance. Raw license/revocation JSON rejects duplicate and Unicode-casefold-colliding keys before object construction.

## R8 x402 → device activation closure

New x402 settlements never create schema-v1 JSON and never set `device_binding=None`. The payment DB and authority DB are separate SQLite databases, so no cross-database atomicity is claimed:

```text
wallet portal → official x402 2.17 verify → payment settlement intent (durable)
              → settle once → authenticated paid evidence → payment outbox (UNIQUE order)
              ⇢ idempotent LicenseAuthority inbox (UNIQUE x402/order)
              → POST body recovery auth + device Ed25519 PoP → signed v2 certificate
              → existing desktop verifier/import → unlocked only on matching device
```

Schema 8 adds `entitlement_outbox`; `LicenseAuthority.external_entitlements` is the idempotent inbox. A crash at either side is recovered by replaying pending outbox rows: the same `(source,source_id)` returns the same license identity. Legacy `orders.license_json` is retained solely for explicit old recovery/manual migration; R8 code does not write it and the new activation response never returns portable entitlement JSON. Payment success may return `activation_required`, not a license.

Activation secrets are accepted only by `POST /v1/activation/challenge` JSON. Responses are generic on authentication/proof failure and carry `Cache-Control: no-store`, `Pragma: no-cache`, and `Referrer-Policy: no-referrer`. The desktop/wallet boundary remains strict: wallet signing belongs to the external HTTPS purchase portal; device private keys remain in Electron main/safeStorage and only device proofs/certificates cross the seam.

Production remains gated on reviewed TLS/auth and log redaction, HSM/KMS + rollback resistance, real recipient and facilitator credentials, mainnet smoke/reconciliation runbook, monitoring/backups, and signed Windows package E2E. No production recipient, secret, deployment, chain transaction, or Agent Port grant is included.

### Official facilitator receipt/finality boundary

The audited x402 2.17.0 `SettleResponse` includes success, payer, transaction, network and optional amount, but no authenticated block receipt, block number or finality timestamp. The official adapter therefore validates settle payer equals verify payer and then deliberately enters `manual_review`; it does **not** use local wall clock as finality. Promotion requires the authenticated reconciler to provide payer, transaction, immutable receipt/evidence digest, source, finality timestamp and explicit finality basis bound to the original order/proof/nonce/amount. This is a production integration gate, not an automatic retry.

The schema-8 entitlement outbox payload is append-only and binds order/source, proof, transaction, evidence, payer, Base network, native USDC, exact atomic amount, product and major. Schema 9 adds an immutable revocation outbox binding authority/source identity, the original entitlement digest/license/order, refund-or-revoke action and reason, payment proof/transaction/evidence and creation time. Both use leased/fenced workers with expired-lease reclaim, bounded retry/quarantine, stale-worker rejection and immutable deterministic Authority receipts. Refund before delivery atomically cancels/quarantines the pending entitlement and creates no false Authority revoke; refund/revoke after delivery atomically writes local terminal state plus the revocation event. Crash windows on both paths replay by the same source identity. Reconciliation must quarantine any payment/outbox/authority disagreement.
