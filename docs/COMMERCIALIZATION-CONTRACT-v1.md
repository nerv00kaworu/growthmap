# GrowthMap Commercialization Contract v1

Status: frozen candidate contract, 2026-07-28. Product major: **1**. This contract is stricter than UI behavior; the desktop backend is authoritative.

## Entitlement state machine

`uninitialized -> trial` only after the first successful desktop sidecar launch. Trial is seven calendar days from the persisted UTC instant and permits at most two active projects. Archive frees a seat; restore is subject to the same atomic seat check. At `now >= started_at + 7 days`, trial becomes `extraction`. A valid signed major-1 entitlement transitions any local state to `paid`; invalid, expired, refunded/revoked (after a truthful check-in), corrupt, or wrong-major documents do not. Paid major 1 is perpetual unless its signed document explicitly has an expiry (nonstandard grant) or a later check-in replaces it with a signed revocation assertion. Failure never deletes data.

States:
- **trial**: all normal product mutations; two active projects.
- **paid**: all normal product mutations; unlimited projects; perpetual for the signed `major_version`.
- **extraction**: no product/settings mutation; all extraction remains available.

A future major may require another purchase. Refusing it leaves the purchased major usable forever. A major-1 license cannot unlock major 2, and running major 2 cannot invalidate the installed major-1 binary.

## Exact capability matrix

| Capability | Trial | Paid matching major | Extraction |
|---|---:|---:|---:|
| list/get/view/history/branch compare/actions | allow | allow | allow |
| local search/filter | allow | allow | allow |
| Markdown/JSON/spec export/download | allow | allow | allow |
| database status/backup/list backups/reveal folder | allow | allow | allow |
| license status/import/activation recovery | allow | allow | allow |
| create/update/delete/archive/restore project | allow (2 active) | allow | **deny** |
| node/edge/block/branch create/update/delete/move/reparent/promote/merge | allow | allow | **deny** |
| project/database import or backup restore | allow | allow | **deny** |
| agent session/artifact create/update/apply/approve/reject; AI expand/deepen/chat that persists | allow | allow | **deny** |
| provider/secret/settings mutation or connection operations with side effects | allow | allow | **deny** |

Implementation uses a centralized fail-closed rule in desktop mode: GET/HEAD/OPTIONS plus license import and idempotent explicit trial-start are the entitlement-extraction HTTP allowlist. Every other POST/PUT/PATCH/DELETE is denied before route execution. Desktop IPC permits backup/status/list/reveal; entitlement extraction denies import/restore. A distinct pending-update recovery lock denies import/product mutation but permits managed backup restore and reveal. Authoring Web mode does not mount this restriction.

## Clock, offline, corruption, concurrency

Trial timestamps are UTC and atomically persisted under Electron `userData`; `started_at` never resets. `last_seen_at` advances monotonically only through an explicitly authenticated writable lifecycle checkpoint; entitlement GET/peek and every extraction/recovery GET are side-effect free. A wall-clock rollback over five minutes, future start, malformed/unknown fields, unreadable state, or write failure fails closed to extraction. Small clock jitter is tolerated. No network is required for trial or paid use. Extraction is always available even when state/license verification fails. Project seat allocation is guarded by a process lock plus a fresh database count so concurrent creates/restores cannot exceed two.

## Signed entitlement schema and devices

Ed25519 JSON, canonical UTF-8 sorted compact JSON excluding `signature`:

```json
{"schema_version":1,"edition":"personal","license_id":"provider-id","major_version":1,"device_allowance":2,"device_binding":"optional-provider-neutral-fingerprint","issued_at":"ISO-8601 UTC","expires_at":null,"revoked_at":null,"max_active_projects":null,"signature":"base64"}
```

Target allowance is two personal devices. Issuance service—not the client—tracks activations and binds/rebinds devices. Binding is optional until a real privacy-reviewed service exists. The repository contains no private key and the shipped placeholder public key blocks commercial packaging. Offline documents cannot be remotely revoked without a check-in; UI/service must say this honestly. A refund/revocation learned through a signed response transitions to extraction, never deletion.

## Payment/activation provider contract

Client requests `POST /v1/checkouts` with `{product:"growthmap",major_version:1,device_request:{device_id,device_name},return_url}`. Service returns `{checkout_id,checkout_url,expires_at}`; `checkout_url` must be HTTPS and exactly on the configured origin before Electron `openExternal`.

Provider webhook adapter verifies the provider signature and timestamp, deduplicates `event_id`, records immutable raw-event hash, maps `paid|refunded|chargeback`, and never accepts entitlement claims from the browser. On paid settlement it calls issuer `POST /v1/licenses/issue` with `{checkout_id,provider_customer_ref,major_version,device_allowance:2}` and receives `{license_document}` matching the schema above. Activation `POST /v1/licenses/{id}/activate` accepts `{device_id,nonce}` and returns a signed document or explicit allowance error. Refund/revocation produces a signed revocation/check-in response. These are schemas/stubs only: no provider, charge, account, production key, or webhook endpoint exists.

## Update trust and recovery boundary

This candidate ships the **stable channel only**. Beta identifiers are recognized internally but rejected at runtime until a user-facing, persisted protected opt-in/enrollment and leave-beta flow exists; inherited environment variables cannot enroll a packaged application. Packaged authority is loaded only from signed-package `commercial-config.json` and its hash-pinned bundled public key; inherited public-key, checkout, update, channel, product-major, and publisher environment values are scrubbed or ignored. Placeholder, hash, identity, or endpoint mismatch fails packaged startup closed. Development-only overrides are limited to unpackaged runs. `updateUrl` is the channel-free generic-provider base path; the updater appends exactly `/stable`, rejects configured `/stable` or `/beta` suffixes, and removes one trailing slash to prevent double slashes. The configured stable generic-provider feed URL is HTTPS-only and universally forbids credentials, fragments, localhost, loopback, and private literal IP hosts; production also rejects placeholder hosts. Redirect behavior is delegated to `electron-updater`/Electron transport and is not claimed as separately pinned here. `electron-updater` supplies platform integrity/signature mechanisms; production additionally requires OS code signing and a real operational endpoint/public-key policy. Update check, download, and restart each require user intent/confirmation. Before download GrowthMap requires structured verified-managed backup evidence (id, manifest verification, SHA-256, and size), then atomically writes and flushes a durable pending marker containing that evidence and version metadata; any flush/rename/directory-sync failure aborts the download. On restart, marker presence or malformed marker forces extraction before residue recovery, schema preflight, backup, or DDL. Strict recovery verifies exact marker schema, actual running target version, older source version, managed backup file/manifest/hash/size, and deep health; only then is the marker durably cleared and a controlled entitlement-aware restart allowed. Failure retains it, blocks product mutations/import, and keeps managed restore/reveal recovery available—never silently discarding data.

Production commercial packaging fails closed until legal drafts are approved, a real license public key, HTTPS checkout/update origins, and Windows code-signing credentials exist. E2E entry points and bypasses are explicitly excluded from production ASAR. This repository does not claim payment or production updating works.

## Security-review clarifications

Trial initialization is corroborated by Electron `safeStorage`: an encrypted immutable trial marker, an independent protected installation receipt, and the sidecar JSON must agree. Fresh mode requires all trial artifacts and all durable prior-use evidence (installation receipt, valid database/residue, managed backups, and update/migration markers) to be absent; deleting both trial files after use therefore forces extraction.  either missing/corrupt after creation is extraction. This resists casual deletion/tamper, not a determined local attacker who can patch binaries or OS storage; offline DRM is never perfect. After the separate validated residue-recovery phase, extraction sidecar startup skips all schema DDL/migrations and sets SQLite query-only, preserving the selected live DB bytes/mtime/schema. Residue recovery may deliberately rename/recover/quarantine app-owned crash artifacts before entitlement-mode startup and is not claimed as zero-write. Electron obtains startup entitlement through the backend's cryptographic maintenance verifier and sends a per-launch nonce/HMAC verdict bound to the unguessable session token. That verdict can narrow a trial to extraction when the protected marker is missing, corrupt, or disagrees with JSON; environment values alone cannot manufacture writable trial/paid state. A cryptographically valid matching-major paid license remains authoritative and may override missing trial artifacts, while mere file existence never does. For paid/trial databases, a read-only schema preflight decides whether migration is needed. A current schema starts without DDL or a backup; an outdated schema starts writable only after a verified managed pre-migration backup and separate durable authorization marker containing its exact backup id/hash/size/project count and versions, authenticated with `GROWTHMAP_MIGRATION_MARKER_MAC` (HMAC-SHA-256 keyed by the per-launch `GROWTHMAP_SESSION_TOKEN`). The sidecar checks the exact marker path/schema/MAC, backup metadata, manifest, durability and bytes, then consumes the marker immediately before entering the DDL transaction; Electron also removes any residue after the attempt. Inherited authorization variables are scrubbed. Initial launch and every import/restore restart use the same prepare-and-start protocol, including update-recovery deep-health verification; startup fails closed without verified schema-current or migration evidence.

Non-null `device_binding` is rejected until a privacy-reviewed activation service and stable device identifier exist; it is never silently accepted on every device. `device_allowance` is issuer-side enforcement. Product major is compiled as v1 and packaging verifies package/identity agreement rather than trusting inherited environment. Windows publisher expectation is committed but deliberately not approved; commercial preflight remains blocked until legal identity/certificate approval, exact Authenticode signer/status/timestamp/chain and updater metadata verification pass.

## Payments v1 amendment (2026-07-28)

The provider-neutral checkout stub above is superseded for major 1 by `docs/PAYMENTS-v1.md`: x402 exact USDC on Base plus manually verified PayPal Goods & Services. The first 50 globally payment-confirmed allocations are 10 USDC/USD; later allocations are 29. A quote is not inventory. Issuance and ordinal allocation share one transaction, and stale-price authorization never silently settles or upgrades price.
