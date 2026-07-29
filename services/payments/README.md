# GrowthMap payments v1 candidate

Independent FastAPI/SQLite candidate. Run tests only:

```sh
PYTHONPATH=services/payments:src/backend src/backend/venv/bin/pytest -q services/payments/tests
```

There is no production facilitator adapter, PayPal API, credential, recipient, or private key. `GROWTHMAP_PAYMENTS_ENV=production` fails unless admin auth and an explicit Ed25519 key file are provided; recipient placeholders always fail. Never copy the issuer DB into the desktop DB.

Operations: stop writes or use SQLite online backup API; copy DB plus `-wal`/`-shm` consistently, encrypt, restrict access, test restore and `PRAGMA integrity_check`. Current migration version is `PRAGMA user_version=7`; baseline 001 is immutable and forward remediations are checksum-pinned 002–007; apply reviewed forward-only migrations before service startup.


Historical schema v4 authenticated terminal settlement evidence with HMAC-SHA256 using a dedicated external secret loaded only from `GROWTHMAP_SETTLEMENT_MAC_KEY_FILE` (minimum 32 bytes). The key is not stored in SQLite, logs, APIs, licenses, desktop artifacts, or packages. Loss of this key makes durable evidence unrecoverable and startup fails closed; key rotation requires a separately reviewed atomic re-MAC migration and is intentionally out of scope. Terminal settlement rows are database-trigger immutable except the evidence-preserving `settled` → `finalized_paid` transition. Release remains **NO-GO pending fresh independent review and Windows package-verifier CI**.

### R6 authenticated issuance closure
Assume SQLite rows and schema/triggers are attacker-controlled. The attacker is not assumed able to access the external MAC key file or authenticated checkpoint file. Configure both `GROWTHMAP_SETTLEMENT_MAC_KEY_FILE` and `GROWTHMAP_SETTLEMENT_CHECKPOINT_FILE`; the latter is a path, never secret material. Startup and every protected recovery/license/admin/PayPal/allocation operation verify checkpoint v2 over the normalized security schema and all rows in orders, proofs, provider events, intents, audit, migration ledger and checkpoint anchor. Trusted commits publish the authenticated next-state checkpoint while holding the SQLite writer transaction, then commit the DB; either crash ordering leaves a detectable mismatch and fails closed. Triggers are defense in depth. Historical paired DB+checkpoint replay is not prevented without an OS/HSM monotonic service, so production remains NO-GO. v5/v6 quarantine all legacy terminal evidence for operator inspection; no legacy row is auto-authenticated or issued.
