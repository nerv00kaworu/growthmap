# GrowthMap payments v1 candidate

Independent FastAPI/SQLite candidate. Run tests only:

```sh
PYTHONPATH=services/payments:src/backend src/backend/venv/bin/pytest -q services/payments/tests
```

A pinned x402 2.17 `OfficialX402Facilitator` candidate adapter exists, but production credentials, a real recipient/endpoint, authenticated receipt/finality reconciler and deployment/live smoke evidence are still blocked. There is no PayPal API, production credential, recipient, or private key in this candidate. `GROWTHMAP_PAYMENTS_ENV=production` fails unless admin auth and an explicit Ed25519 key file are provided; recipient placeholders always fail. Never copy either payment or authority DB into the desktop DB.

Operations: stop writes or use SQLite online backup API; copy DB plus `-wal`/`-shm` consistently, encrypt, restrict access, test restore and `PRAGMA integrity_check`. Current migration version is `PRAGMA user_version=9`; baseline 001 is immutable and forward remediations are checksum-pinned 002–009; apply reviewed forward-only migrations before service startup.


Historical schema v4 authenticated terminal settlement evidence with HMAC-SHA256 using a dedicated external secret loaded only from `GROWTHMAP_SETTLEMENT_MAC_KEY_FILE` (minimum 32 bytes). The key is not stored in SQLite, logs, APIs, licenses, desktop artifacts, or packages. Loss of this key makes durable evidence unrecoverable and startup fails closed; key rotation requires a separately reviewed atomic re-MAC migration and is intentionally out of scope. Terminal settlement rows are database-trigger immutable except the evidence-preserving `settled` → `finalized_paid` transition. Release remains **NO-GO pending fresh independent review and Windows package-verifier CI**.

### R6 authenticated issuance closure
Assume SQLite rows and schema/triggers are attacker-controlled. The attacker is not assumed able to access the external MAC key file or authenticated checkpoint file. Configure both `GROWTHMAP_SETTLEMENT_MAC_KEY_FILE` and `GROWTHMAP_SETTLEMENT_CHECKPOINT_FILE`; the latter is a path, never secret material. Startup and every protected recovery/license/admin/PayPal/allocation operation verify checkpoint v2 over the normalized security schema and all rows in orders, proofs, provider events, intents, audit, migration ledger and checkpoint anchor. Trusted commits publish the authenticated next-state checkpoint while holding the SQLite writer transaction, then commit the DB; either crash ordering leaves a detectable mismatch and fails closed. Triggers are defense in depth. Historical paired DB+checkpoint replay is not prevented without an OS/HSM monotonic service, so production remains NO-GO. v5/v6 quarantine all legacy terminal evidence for operator inspection; no legacy row is auto-authenticated or issued.

## Device-bound activation candidate (schema 8)

The service is an evidence ledger/outbox, not a license signer. Official runtime dependency is hash-locked separately in `requirements.lock` as `x402[httpx]==2.17.0`; do not install this lock into the editor backend. Production construction accepts only `OfficialX402Facilitator` with an HTTPS endpoint. `MockFacilitator` is explicit isolated-test infrastructure and is rejected in production.

After durable paid evidence, `entitlement_outbox` delivers `(x402, order_id)` idempotently into `LicenseAuthority.external_entitlements`. Because these are distinct SQLite files, delivery is intentionally at-least-once with UNIQUE inbox/outbox identities—not falsely atomic. Restart recovery may finalize only already-authenticated paid evidence and pending outbox records; unknown settlement remains `manual_review` and is never blindly retried.

The claim endpoint is POST-body-only and requires order recovery authentication, device public key, fresh nonce, and Ed25519 device proof. It returns only a schema-v2 device activation certificate. Legacy `license_json` columns remain readable only for controlled migration of pre-schema-8 rows; new flows never call the removed portable `_license()` signer.

SDK 2.17 settle success is not represented as chain finality: the SDK response has no receipt/block/finality timestamp. The adapter never substitutes `datetime.now()`. It leaves the intent ambiguous for an authenticated receipt reconciler. Schema-8 entitlement and schema-9 revocation outbox triggers make payload/delete/ack mutation fail closed; authority entitlement and deterministic revocation receipt inbox rows are likewise immutable. Leased/fenced workers reclaim expired leases, reject stale workers, back off/quarantine failures, and safely replay Authority-commit/payment-ack crashes.
