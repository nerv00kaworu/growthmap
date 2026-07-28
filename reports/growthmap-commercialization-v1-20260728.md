# GrowthMap commercialization v1 candidate — 2026-07-28

Baseline: `5dfb5414ae9f92e2f170b655c4d69e8b7d7db3c9`
Result: local trust-boundary remediation verified; **commercial release remains fail-closed/blocked**. No commit, push, tag, release, provider write, charge, or live DB access occurred.

## Implemented

- Froze `docs/COMMERCIALIZATION-CONTRACT-v1.md`: state machine, exact route/capability matrix, rollback/offline behavior, two-device/current-major signed schema, refund/revocation truth boundary, payment APIs, update and recovery trust boundaries.
- Added atomically persisted seven-day trial state under desktop `userData`; first successful sidecar startup initializes it. Unknown/corrupt/future/rolled-back state becomes extraction mode without restricting reads or exports.
- Evolved signed Ed25519 entitlement to schema v1 with `major_version`, `device_allowance`, optional binding, issued/expiry/revocation seams, perpetual matching-major unlock, and no embedded private key.
- Added centralized desktop-only FastAPI mutation middleware: in extraction mode only GET/HEAD/OPTIONS and license import may pass. Project seat create/restore remains serialized and database-counted. Web authoring is unaffected.
- Added Electron IPC guard for database import/restore in extraction mode; backup/status/list/reveal remain usable.
- Added clear UI labels for trial days/2-project use, perpetual paid major, extraction mode, license import, configured checkout, and disabled principal mutation controls. Backend remains authoritative for all unhidden paths/shortcuts.
- Added exact-origin HTTPS checkout `openExternal` seam. Checkout URL is build/operator configured, not renderer supplied.
- Added `electron-updater` stable-channel framework, confirmation before check/download/restart, universal localhost/loopback/private-literal feed rejection, and required structured verified-managed DB evidence before download. Beta is fail-closed until protected persisted user opt-in UI exists; inherited channel environment is ignored. Existing startup database validation/migration/recovery remains the post-update safety path.
- Expanded commercial preflight to reject legal drafts, placeholder key, absent/placeholder update+checkout endpoints, and absent Windows signing credentials. Production source excludes E2E main.
- Added workflow gates for fail-closed commercial preflight and E2E exclusion.

## Verification (isolated only)

- Backend: `venv/bin/pytest -q` — **48 passed**, one upstream TestClient deprecation warning.
- Desktop: `npm test` — **62 passed**.
- Desktop: `npm audit --audit-level=high` — **0 vulnerabilities**.
- Frontend: `npm run lint` — PASS.
- Frontend: `npm run typecheck` — PASS.
- Frontend: `npm run build` — PASS; static export regenerated.
- CSP manifest regenerated after frontend build.
- `git diff --check` — PASS.
- Windows package/NSIS/AuthentiCode/Windows E2E — **PENDING**, unavailable on this Linux/WSL run; not represented as PASS.

## Changed source/config files

`.github/workflows/desktop-windows.yml`; `desktop/{main.js,preload.js,package.json,package-lock.json,update-policy.js,updater.js,scripts/preflight.js,tests/update-policy.test.js,generated/csp-script-hashes.json}`; `docs/COMMERCIALIZATION-CONTRACT-v1.md`; `src/backend/desktop/{entitlements.py,mutation_gate.py,routes.py}`; `src/backend/{main.py,tests/test_commercial_entitlements.py,tests/test_desktop_foundation.py}`; `src/frontend/src/{app/page.tsx,desktop.d.ts,lib/api.ts}` plus regenerated `src/frontend/out`; this job state and report.

## Honest release boundary / blockers

This is not a functioning paid product or production updater. Commercial packaging is intentionally blocked until all of these exist and are reviewed: approved legal documents; production Ed25519 public key plus secure offline issuance/private-key operations; real checkout, verified webhook, idempotent license/activation/refund service; real HTTPS update endpoint and release signing/integrity operations; Windows Authenticode certificate/credentials; successful Windows CI/package/E2E verification. Offline revocation cannot occur without check-in; the product does not claim otherwise. Existing purchased-major data and extraction access are never deleted or withheld.

## Fresh-eyes QA remediation

- Closed JSON-import seat bypass with one serialized allocator shared by create, restore, and active import; archived import consumes no seat. Mixed concurrent acceptance is tested.
- Trial no longer starts in FastAPI lifespan. Authenticated idempotent `/api/desktop/trial/start` is called only after Electron deep readiness; existing/corrupt state is never reset.
- Added durable pending-update marker after verified backup and before download. Startup deep-health/SQLite quick-check clears only on success; failure retains a recovery lock, blocks mutations/import, and keeps managed restore/reveal available.
- Initial update feed policy is enforced; updater transport redirects are not claimed as separately pinned.
- Added desktop-only Check for updates UI, persisted paid-major/wrong-major non-overwrite tests, broader route inventory matrix, and IPC/update recovery contracts.

## Security review remediation

Added safeStorage-correlated trial initialization/deletion fail-closed behavior; true query-only extraction startup that skips DDL; non-null device-binding rejection; compiled product-major/preflight agreement; canonical origin-only checkout validation; explicit expected publisher plus commercial Authenticode/updater metadata CI gate; and complete updater async error handling. Residual limit: local binary patching can defeat offline controls. Publisher identity remains unapproved and commercial release stays blocked. Existing paid/trial startup first receives a read-only schema preflight. Current schemas avoid DDL and ordinary-launch backups; outdated schemas require a verified managed pre-migration backup plus a separate nonce/hash/size-bound durable authorization marker before sidecar DDL. Missing or inherited-only authorization fails closed.

## Integration remediation

Fresh trial mode now also requires absence of an independent protected installation receipt plus database/residue, managed-backup, and update/migration evidence; deleting both trial files cannot reset trial. Packaged commercial authority is immutable signed-package configuration with a hash-pinned bundled public key, while inherited authority environment values are ignored. Pending/malformed updates lock startup in extraction before residue recovery/schema work and clear only after strict version/managed-backup/deep-health verification. Entitlement GET is now side-effect free; trial `last_seen_at` changes only through an authenticated writable checkpoint. Startup mode uses the backend cryptographic entitlement verifier plus a per-launch session-token HMAC verdict so protected-marker disagreement centrally forces backend extraction before mutation routes:  matching-major paid overrides missing trial artifacts; invalid/corrupt/wrong-major documents do not. Update and migration markers use atomic temp writes, file flush, rename, and supported parent-directory flush; failures abort download/migration. Migration authorization uses an exact durable marker authenticated by `GROWTHMAP_MIGRATION_MARKER_MAC` (HMAC-SHA-256 keyed by the per-launch session token), bound to backup id/hash/size/project count and versions. The sidecar revalidates marker, manifest, durability, stable file identity and bytes, then consumes the marker immediately before DDL; inherited boolean/missing/wrong MAC authorization is rejected and replay fails. Initial launch plus import/restore restart share `prepareAndStart`, including cryptographic entitlement decision, schema preflight, conditional migration backup/marker, and pending-update deep-health verification/lock handling. Extraction import is denied; update-recovery restore remains available and its restart keeps the lock until deep health succeeds. Zero-write extraction evidence applies after the separate crash-residue recovery phase; residue recovery is tested/documented as an intentional file-recovery operation that may rename app-owned artifacts.


## Final local remediation — 2026-07-28

The partial security remediation was completed and rerun in required order. One shared exact managed-backup validator now governs database listing/status/backup evidence, trial prior-use, updater pre-download evidence, update promotion/reset/recovery, and migration marker creation. Tests cover malformed timestamps/durability, exact key shape, hash/size, symlink/hardlink and stable identity replacement. Download-started interruption/rejection/error clears safely on the source version; install-ready deferral does not run deep health; only the exact target runs strict evidence plus deep health; impossible versions/corrupt evidence retain the recovery lock. `updateUrl` is a channel-free base path and the updater appends exactly `/stable`. Production ASAR/package lists include `managed-backup.js`.

Local state is **local_remediation_complete_pending_fresh_security**, not final commercial completion. Windows package/NSIS/AuthentiCode/E2E and the external legal, key, payment, feed and signing blockers remain. No live database, commit, push, publish or provider write occurred.
