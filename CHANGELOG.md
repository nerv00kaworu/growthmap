# Changelog

All notable changes to the GrowthMap **authoring/editor** package are documented here.

## [Personal v1 live sync] - 2026-09-01

### Publicly verifiable release
- Publishes Windows Personal v1 live canonical-sync evidence for `GrowthMap-Setup-0.1.0-desktop.2-x64.exe`: `145385238` bytes and SHA-256 `cc1a4e15a390b8b56773d531902617ee84c41526c6fedbcfd233b5960ba8b928`.
- Documents separate installer source commit `6702f5815b5f71b996cf87a95eab6e242ed62f5f` and website deployed source `35634595392f1e75ee64725a2b1d80f735eca185`; neither is substituted for the other.
- Documents shared canonical revisions/CAS conflict re-read and SSE stale-state signals. SSE is not mutation truth or a cloud project database.
- Confirms the installer is unsigned and uses manual overwrite updates; public guidance requires matching filename/bytes/SHA-256 and never advises bypassing Windows security.


## [0.1.0-authoring.2] - 2026-07-27

### Security
- Updates Next.js to 15.5.21 and forces the production sharp tree to 0.35.3; updates the reviewed Python lock to Mako 1.3.12, click 8.4.2, idna 3.18, Starlette 1.3.1, and compatible FastAPI 0.140.0.
- Removes browser API-key fields and direct provider calls. Browser persistence is metadata-only and all AI operations resolve a server-side provider profile by `provider_id`.
- Rejects per-request AI `api_key`/`base_url` fields and changes connection testing to `provider_id`.
- Requires `GROWTHMAP_LLM_KEY_[A-Z0-9_]{1,96}` for every profile on create/patch/write and before test/AI resolution (including mock); unsafe existing rows fail closed with a rebind error; keeps writes localhost-only, atomic, mode `0600`, and response-empty.
- Makes release launcher binds strictly `127.0.0.1`/`localhost` only (IPv6 forms rejected) and adds matching backend Trusted Host enforcement.

### Verification
- Frontend clean install, lint, typecheck, production build, and production npm audit pass (0 vulnerabilities).
- Backend compile and 20 isolated tests pass (original 12 core tests plus 8 security regressions); pip-audit reports 0 known vulnerabilities.

### Excluded
- No desktop shell, payments, license seats, or Abyss runtime changes are included in this security remediation release.

## [0.1.0-authoring.1] - 2026-07-24

### Release boundary
- Declares GrowthMap as the authoring/editor package only.
- Excludes the split Abyss Bureau player Web/API runtime, gameplay release/replay tooling, player database, payment, PvP, runtime LLM, and runtime image generation.
- Excludes local databases, backups, logs, runtime state, historical player artifacts, and candidate artwork from release inputs.

### Changed
- Adds formal node authoring fields to the editor surface: description, rules, constraints, examples, questions, decision notes, workflow status, priority, confidence, and file paths.
- Enforces one `child_of` mainline per parent through shared API write logic plus SQLite protection for compatible databases.
- Normalizes legacy nullable fields at API output boundaries.
- Makes CORS an exact opt-in allowlist outside development/test and adds authoring deep-health readiness.
- Replaces unsafe launch behavior with a loopback-default launcher that refuses port collisions, dependency installation, and implicit database selection.

### Verification
- Frontend lint, typecheck, and production build pass.
- Backend compile and in-memory SQLite test suite pass.
- Launcher smoke test passes with an isolated temporary SQLite database.

### Known limitations
- Backend schema compatibility steps execute at startup against the explicitly selected `DATABASE_URL`; operators must retain a verified backup before upgrading an existing database.
- Automated tests use isolated in-memory SQLite and do not cover external AI provider integration.

### Upgrade note
- Provide an explicit `DATABASE_URL` before starting. Backend startup can apply lightweight schema compatibility steps to that database; take an operator-managed backup before upgrading an existing database.
