# GrowthMap x402 production composition runbook (draft; NO-GO)

This runbook separates the **evidence-only dependency review manifest** from **runtime composition authorization**. A valid review manifest is necessary source evidence; it does not authorize startup, prove that reviewed bytes are deployed, or prove that a payment occurred. The current source intentionally keeps both `create_app(Config.production=True, ...)` and `from_env()` blocked.

## Required external inputs (names only)

- Immutable production-input document conforming to `services/payments/deployment/production-input.schema.json`.
- Independently authenticated deployment authorization binding deployment identity, release commit, production-input digest, review-manifest digest, effective artifact/config digests, ceremony context, and expiry/freshness.
- Official x402 2.17 client provider pinned to PayAI canonical origin `https://facilitator.payai.network`. The current PayAI free tier requires no account or API key; if a future paid tier is adopted, credential custody must remain outside request data and raw application environment values.
- Low-volume beta finality RPC is pinned to the official Base origin `https://mainnet.base.org`; only `eth_chainId`, receipt lookup, canonical block lookup and finalized-block lookup are allowed. Every unavailable/rate-limited/malformed response fails closed. The external settlement MAC key file remains mandatory.
- Finality sidecar on a private Unix socket: transport transcript key file (mode 0600) plus independently pinned Ed25519 finality public key. The payment process verifies signed evidence and never reads the sidecar private signing key.
- Authority sidecar on a different private Unix socket and different transport key (mode 0600), with exact independently pinned Authority signer identity. Allowed calls are limited to handshake, entitlement/revocation crossing and durable readback.
- External signer/KMS/HSM provider and rollback-resistant signer-generation anchor for Authority. Authority DB, signer and generation anchor remain outside the payment process.
- Argon2id PHC hash file for `Argon2idSessionVerifier` (mode 0600, owned by service UID); bearer tokens are request-only and are never startup inputs.
- Monitoring/alert route, restore-test evidence, rollback artifact, signed package identity and fresh QA/Security/release approvals.

Sidecar path names in production input: `FINALITY_SIDECAR_PUBLIC_KEY_FILE`, `FINALITY_SIDECAR_UNIX_SOCKET`, `FINALITY_TRANSPORT_KEY_FILE`, `AUTHORITY_UNIX_SOCKET`, and `AUTHORITY_TRANSPORT_KEY_FILE`. Finality and Authority must use different sockets, Unix users and transport keys.

Environment/path keys used by existing code: `GROWTHMAP_PAYMENTS_ENV`, `GROWTHMAP_PAYMENTS_DB`, `GROWTHMAP_X402_RECIPIENT`, `GROWTHMAP_ADMIN_ORIGIN`, `GROWTHMAP_CSRF_SECRET`, `GROWTHMAP_PURCHASE_RESOURCE_BASE`, `GROWTHMAP_SIGNING_KEY_FILE`, `GROWTHMAP_SETTLEMENT_MAC_KEY_FILE`, `GROWTHMAP_SETTLEMENT_CHECKPOINT_FILE`, `GROWTHMAP_ADMIN_SESSION_HASH_FILE`, `GROWTHMAP_AUTHORITY_ID`, `GROWTHMAP_AUTHORITY_KEY_ID`, `GROWTHMAP_AUTHORITY_GENERATION`, `GROWTHMAP_AUTHORITY_PUBLIC_KEY_SHA256`, `GROWTHMAP_AUTHORITY_ATTESTATION`, `GROWTHMAP_AUTHORITY_PUBLIC_KEY_FILE`. Future provider configuration is path-based: `PRODUCTION_INPUT_PATH`, `DEPLOYMENT_AUTHORIZATION_PATH`, `AUTHORITY_TRANSPORT_CONFIG_PATH`, `FACILITATOR_PROVIDER_CONFIG_PATH`, `FINALITY_PROVIDER_CONFIG_PATH`, `SIGNING_KEY_PROVIDER_CONFIG_PATH`.

Do not place secret values in the production-input document, command line, logs, review manifest, HTTP request bodies, desktop package, or this runbook.

## Deterministic preflight order

1. Verify exact release commit/package identity and public-config generator check.
2. Validate production-input schema with no template placeholders; reject extra/missing keys.
3. Safe-open and digest the production-input and review-manifest files; require exact independent pins.
4. Cryptographically validate review evidence against caller-pinned policy and dependency pins.
5. Separately validate authenticated deployment authorization and freshness. Never derive authorization from the review manifest, dependency classes, duck typing, marker attributes, or runtime handshakes.
6. Construct exact reviewed dependency implementations from external providers; compare effective identities/config/artifact measurements to authorization pins. Verify socket owner/mode, expected peer UID, distinct socket inode/key digests, sidecar artifact hashes, Authority DB inode, signer ceremony and generation anchor. A runtime handshake is checked only against independent pins and cannot self-approve.
7. Verify Argon2 parameters/file ownership, Authority signer identity, exact PayAI facilitator origin/TLS policy and independently pinned `/supported` document digest, finality MAC provider, checkpoint, database schema/migration ledger, monitor health and backup restore evidence.
8. Refuse startup on any mismatch or unavailable input. Successful composition means only “startup inputs accepted,” not “payment happened.”

The repository now contains bounded authenticated Unix client seams and Ed25519 finality-envelope verification, but it still lacks the independently authorized sidecar server compositions, real deployment authorization verifier, externally provisioned Authority signer/monotonic anchor, and effective deployed-artifact measurement. The user accepted the official rate-limited Base RPC for initial low-volume beta; replace its transport when traffic warrants without changing ledger/finality semantics. PayAI's public `/supported`, `/verify`, or `/settle` response cannot fill those gaps or authorize startup. Therefore do not bypass the production block.

## Sidecar server boundary

- Bind each AF_UNIX socket only after confirming the path does not exist; never unlink or replace an existing file/symlink. Socket mode is `0600`.
- Enforce `SO_PEERCRED` expected payment-worker UID where supported, plus separate request/response transcript keys. Peer UID and HMAC are both required; neither replaces business-evidence signatures.
- One request per connection, strict JSON shape, 32 KiB request/response caps, bounded timeout, exact operation allowlist and generic errors only. Nonces are single-use within a bounded replay window; service restarts are safe because business operations are idempotent/readback-based and operation-specific evidence remains signed.
- Finality sidecar exposes only `sign_finality` and accepts only the exact finality payload schema. It has no key-generation/export endpoint.
- Authority sidecar exposes only `handshake`, entitlement/revocation crossing, and their durable readbacks. It cannot expose license creation, activation, device, admin, DB, signer, or ceremony methods.
- Run payment, finality and Authority under distinct Unix identities. Finality/Authority private signers are readable only by their own service; payment receives only reviewed public keys and transcript keys.

## Database and backup boundary

- Payment DB, Authority DB, and desktop DB must be three different files and storage identities. Never copy/attach/merge one into another.
- Back up SQLite with the online backup API while writes continue, or stop writes and copy the DB with a consistent WAL/SHM state. Never copy only the main DB during WAL writes.
- Back up the payment checkpoint consistently with the payment DB and retain the external MAC key through its separate custody process. Encrypt backups, restrict access, record digests, run `PRAGMA integrity_check`, and perform a restore rehearsal before launch.
- Authority backup/restore must preserve its separate signer ceremony ledger and be checked against the external monotonic generation anchor. A historical DB snapshot must not roll the anchor back.

## Rollout and rollback

1. Preserve current artifact, service definition, production-input/auth digests, DB/checkpoint backup, and Authority backup before change.
2. Deploy without enabling traffic; run deterministic preflight and non-monetary smoke tests.
3. Enable narrowly, monitor 402 challenge, ambiguous-intent alerts, Authority outbox/readback, admin auth failures, checkpoint verification, and restore telemetry.
4. Before any real paid/mainnet smoke transaction, obtain the separate explicit operator confirmation required by launch policy.
5. On anomaly, remove traffic, stop writers, preserve logs and DB/checkpoint pair, restore the prior artifact/config and the matching DB/checkpoint backup. Do not auto-retry settlement and do not delete ambiguous intents.
6. Rollback of Authority state is prohibited unless consistent with its external monotonic anchor; otherwise keep it offline for reconciliation.
