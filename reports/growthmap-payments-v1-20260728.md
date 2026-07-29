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

- Payment: **24 passed** in the exact local suite (`PYTHONPATH=services/payments:src/backend src/backend/venv/bin/pytest -q services/payments/tests/test_payments.py`), with one Starlette/httpx deprecation warning.
- Backend (correct `src/backend` cwd): **53 passed**, one upstream deprecation warning.
- Frontend lint/typecheck/build: **PASS**.
- CSP generate then desktop: **80 passed**; npm audit: **0 vulnerabilities**.
- `git diff --check`: **PASS** after the local payment repair.
- Windows package/ASAR/resources/AuthentiCode/E2E: **pending parent/fresh Windows review**.

## Honest gaps

Candidate HTTP surface includes list/reject/refund/revoke/recovery, strict transitions and an enforced in-process limiter, but intentionally has no reissue endpoint, signed revocation assertion/check-in, production session provider, real x402 facilitator or PayPal API. SQLite transactions—not process locks—are authoritative across candidate service instances. See docs for production blockers.

## NO-GO remediation

Status remains **remediation_required pending fresh parent review**. SQLite is now authoritative across service instances for quote creation and durable x402 settlement intents/ordinal reservations. External settlement follows a committed intent; ambiguity is durable manual review and is never blindly retried. PayPal uses USD cents parsed from exact Decimal strings, claim binding, strict transitions, append-only audit triggers, enforced in-process rate-limit seam/no-store recovery, and configurable test admin origin/CSRF. Production HTTP startup remains explicitly blocked until reviewed Argon2id session infrastructure and official facilitator integration exist. Reissue and signed revocation assertions are not implemented or claimed.

## Second security NO-GO remediation

Status remains **NO-GO / remediation required pending fresh parent review**. Added evidence-backed ambiguous intent reconciliation, separate durable settlement-result recording before idempotent issuance, preserved migration 001 plus checksum-pinned 002 upgrade, explicit mock opt-in, configurable HTTPS resource base, and extension/path-based ASAR/resources exclusions. No production reconciler or official x402 compatibility is claimed.

## Parent reproducer remediation

Kept status **NO-GO pending parent fresh review**. Migration 002 now table-copies FK child tables before replacing orders, preserving populated payment proof/external event/audit rows. Added realistic v1 child-row fixture plus idempotence/FK/integrity assertions. Windows verifier now extracts ASAR and scans complete app-owned ASAR/resource files; generic `.dat`/`.bin` adversarial private-key, SQLite, Python issuer and migration payload fixtures must fail independent of names.

Historical R4 payment remediation suite was **17 passed**; current R6 suite is **24 passed**. Fresh adjudication remediation adds idempotent startup finalization of durable settled evidence without provider calls; generic non-leaking no-store 500 handling and 200/402/404/409/422/500 coverage; atomic migration SQL/version/ledger writes with fail-closed v2+ ledgers; checksum-pinned evidence migrations through v4, external settlement-MAC fail-closed validation, and complete app-owned package scanning plus lock-installed third-party byte inventory checks (including >2 MiB suffix, native-looking, and `node_modules` adversarial fixtures).

Current verdict remains **NO-GO pending fresh independent security/QA adjudication and the Windows CI/package gate**. Local non-Windows checks do not constitute that independent verdict.

## R5 remediation status
Implemented candidate controls for complete terminal-row MAC binding, external authenticated terminal-set checkpointing, v5 legacy quarantine, separated failed-auth/admin-action limiting, and frozen clean-install desktop dependency provenance. Current-DB mutation/deletion and checkpoint/key mismatch fail closed. Historical paired DB+checkpoint rollback remains unsolved without an external monotonic/HSM anchor. Production facilitator/reconciler/auth/key/session/deployment and an actual Windows workflow run remain blockers; Windows is NO-GO.

## R6 authenticated issuance-closure remediation (current)

R5 sections above are retained as historical chronology; this section supersedes their counts and terminal-only trust description. Schema **v6** checkpoint v2 authenticates the normalized security-relevant SQLite schema plus orders, payment proofs, provider events, settlement intents, issued license/order state, audit chain, migration ledger and checkpoint anchor. Verification occurs before startup recovery, issuance/recovery exposure, PayPal/admin mutation/read and ordinal allocation. Current row/schema tamper fails closed; trusted DB commit followed by checkpoint-write failure leaves an intentional fail-closed mismatch.

Fresh payment suite: **24 passed**, including true populated checksum-ledger schema-v4 terminal evidence → v6 quarantine and authenticated populated v5 checkpoint → v6 quarantine, with `ambiguous`/`manual_review`, no auto-license, ledger 1–6, integrity/FK, reopen/idempotence. Backend remains **53 passed**. Frontend lint/typecheck/build passed. Desktop CSP generation and tests are rerun below. Desktop audit is clean; **frontend npm audit is not clean: 9 high-severity development-toolchain findings in ESLint/minimatch/brace-expansion; the complete suggested fix requires breaking ESLint 10 and was not applied.**

Status remains **NO-GO** pending fresh independent review, actual Windows execution, provider/auth/session/key/deployment integration, and an external monotonic/HSM control for paired historical DB+valid-checkpoint rollback.

## R7 same-transaction trust remediation (current)
R6 text above is historical. Every protected operation now acquires the shared checkpoint serializer, opens its operation connection, executes `BEGIN IMMEDIATE`, and verifies checkpoint-v2/schema/closure and terminal evidence on that same locked connection before reading or mutating. It holds the transaction through decision, issuance and checkpoint publication/DB commit; recovery/admin reads use service helpers with the same boundary. Deterministic attacker races prove x402 finalization and recovery cannot be changed between verification and result, and subsequent post-commit tamper returns exactly `external issuance checkpoint/database mismatch`.

Fresh payment suite: **26 passed**, including a 60-way, 8-service mixed x402/PayPal concurrency test: exactly 50 licenses/unique ordinals 1–50/proofs/transactions and 10 stale-price manual-review outcomes, with FK/integrity/audit/checkpoint reopen verification. Backend **53 passed**; clean frontend lint/typecheck/build passed; desktop CSP + **80 tests** + audit 0 passed. Frontend audit remains **9 high** in ESLint/minimatch/brace-expansion development tooling; breaking ESLint 10 remediation was not applied. Overall remains **NO-GO** pending fresh re-review, Windows execution and external deployment/provider/auth/key/session/monotonic controls.

## R8 Windows candidate evidence (current)

Exact GitHub Actions run [`30417689211`](https://github.com/nerv00kaworu/growthmap/actions/runs/30417689211) completed **PASS** on Windows for candidate `0950afdb87583d13d11d1e81e58ab3466532a16a`. Backend tests, frontend lint/typecheck/build, desktop tests, commercial-preflight fail-closed check, isolated non-shipped packaged E2E, final unsigned NSIS build, normal sidecar smoke, adversarial database/crash-recovery boundaries, final production ASAR/resources/E2E exclusion, installer existence/SHA-256, and artifact upload all passed. The final verifier binds packaged production dependencies to frozen npm-ci provenance by non-dev package identity, exact non-manifest file hashes, and package-manifest subset semantics after electron-builder flattening/pruning.

This is **Windows candidate/package evidence, not commercial publication approval**. Authenticode/updater metadata verification was intentionally skipped because production signing/publication inputs were not supplied. No live DB, production credentials/private keys, provider write, or real-money operation was used. Overall product status remains **NO-GO for production/public release** pending production facilitator/reconciler, auth/session/key/deployment integration, revocation check-in, external monotonic/HSM rollback protection, legal/config/signing inputs, and fresh independent security/QA adjudication of the final committed candidate.

## R9 independent adjudication and manifest HIGH closure (current)

Fresh QA adjudication passed the payment candidate gates, but fresh security review found a **HIGH** in the Windows dependency verifier: packaged dependency `package.json` files could initially omit arbitrary fields, and a first remediation still compared JSON property names through PowerShell's case-insensitive `PSCustomObject` lookup. Those defects allowed runtime-semantic fields such as `main`, `exports`, `type`, or `bin` to be removed or case-renamed (`main` → `MAIN`), potentially redirecting Node to another otherwise frozen file.

Candidate `d62091e7c4f3a867d40046fbd5010c4958902bfc` closes both paths. Source and packaged manifests are copied into separate `Dictionary[string,object]` maps using `StringComparer.Ordinal`; only the exact non-runtime fields `bugs`, `contributors`, `eslintConfig`, `keywords`, `scripts`, and `xo` may be pruned. Behavioral self-tests require deletion and case-renaming of `main`, `exports`, `type`, and `bin` to fail at the manifest-semantic gate. Exact GitHub Actions run [`30420037621`](https://github.com/nerv00kaworu/growthmap/actions/runs/30420037621) passed at that SHA, including Windows tests, packaged E2E, NSIS, adversarial DB/crash recovery, and final ASAR/provenance verification.

A second fresh targeted security review returned **PASS** for the scoped HIGH. It confirmed ordinal key identity, exact-case pruning, genuine self-test reachability, fail-closed case-colliding JSON keys, local PowerShell verifier self-test PASS, desktop **80/80 PASS**, and the exact Windows run/SHA evidence. Raw exact duplicate JSON keys remain a non-blocking hardening caveat because PowerShell and Node both consume the last duplicate value; no semantic divergence or bypass was reproduced.

The candidate security/QA and Windows package gates are now closed for the implemented offline/mock scope. **Production/public release remains NO-GO** because official x402/facilitator and production reconciler integration, production auth/session/key/deployment, signed revocation/check-in, external monotonic/HSM historical rollback protection, and legal/config/Authenticode/updater publication inputs remain unresolved or intentionally out of scope.

## R10 frontend audit closure (current)

The previous frontend audit showed 9 high findings, all transitive effects of `GHSA-mh99-v99m-4gvg` in `brace-expansion` through the ESLint development toolchain. A global `minimatch` 10 override was explicitly rejected after isolated testing showed it broke ESLint 9's expected default export. Candidate `4f381930d2849c87356de73ff655e3851784f1d9` instead applies the narrow compatible override `brace-expansion: 5.0.8`, retaining Next 15, ESLint 9, and minimatch 3 APIs.

Fresh clean-install evidence: frontend `npm ci` PASS, `npm audit --audit-level=high` **0 vulnerabilities**, lint/typecheck/build PASS, desktop CSP regeneration and **80/80 tests** PASS. Exact Windows run [`30421389694`](https://github.com/nerv00kaworu/growthmap/actions/runs/30421389694) passed at that SHA, including frontend clean install/build, packaged E2E, NSIS, adversarial DB/crash recovery, and final ASAR/provenance verification. The frontend 9-high blocker is closed without an ESLint/Next major upgrade.

Production/public release remains **NO-GO** only for the remaining external/production boundaries: official provider/reconciler integration, production auth/session/key/deployment and payment endpoints, signed revocation/check-in, external monotonic/HSM rollback protection, and legal/config/Authenticode/updater publication inputs.
