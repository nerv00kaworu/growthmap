# GrowthMap payments v1 candidate

Independent FastAPI/SQLite candidate. Run tests only:

```sh
PYTHONPATH=services/payments:src/backend src/backend/venv/bin/pytest -q services/payments/tests
```

There is no production facilitator adapter, PayPal API, credential, recipient, or private key. `GROWTHMAP_PAYMENTS_ENV=production` fails unless admin auth and an explicit Ed25519 key file are provided; recipient placeholders always fail. Never copy the issuer DB into the desktop DB.

Operations: stop writes or use SQLite online backup API; copy DB plus `-wal`/`-shm` consistently, encrypt, restrict access, test restore and `PRAGMA integrity_check`. Migration version is `PRAGMA user_version=1`; apply reviewed forward-only migrations before service startup.
