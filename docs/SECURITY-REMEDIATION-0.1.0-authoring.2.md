# GrowthMap security remediation report — 2026-07-27

## Scope and baseline

- Baseline: immutable `growthmap-authoring-v0.1.0-authoring.1` / `2c2de88deb31fd08c93ff73bbe06b88993165651`.
- Candidate: `v0.1.0-authoring.2`; no commit, tag, push, or archive was created.
- Excluded: desktop shell, payment, license seats, and all Abyss runtime code/data. No live database or current 3100/8100 process was touched.

## Remediation

- Frontend: exact Next.js 15.5.21 and sharp 0.35.3 (top-level dependency plus override so Next's production tree cannot retain vulnerable sharp); React remains 19.1-compatible. Lockfile regenerated deliberately, without `npm audit fix --force`.
- Python: lock resolves FastAPI 0.140.0 / Starlette 1.3.1, Mako 1.3.12, click 8.4.2, idna 3.18 and reviewed compatible transitive versions.
- BYOK: removed browser secret fields and direct provider HTTP helper. LocalStorage migration rewrites legacy records to provider type/ID/model only. Expand/deepen/chat and connection testing accept only `provider_id`; strict request schemas reject secret/endpoint overrides. Backend resolves endpoint/model/key from an enabled profile and environment.
- Secret storage: localhost-only endpoint, atomic environment-file replacement, mode 0600, empty 204 response; profile responses contain no key.
- Network boundary: release launcher rejects non-loopback backend or frontend binds before prerequisites/startup. Backend Trusted Host enforcement rejects external Host values, independent of CORS.

## Regression tests

- Original 12 core backend tests: PASS.
- Added 8 security tests: browser metadata-only contract/no direct helper; AI secret override rejection; mock provider_id path and connection test; secret file/response behavior and locality predicate; Trusted Host rejection; launcher non-loopback rejection.
- Combined backend suite: 20/20 PASS.

## Verification results

- `cd src/frontend && npm ci`: PASS (reproducible clean install). npm reports dev-tree advisories during install; the required production-only audit below is clean.
- `npm run lint`: PASS.
- `npm run typecheck`: PASS.
- `npm run build`: PASS (Next.js 15.5.21, static routes generated).
- `npm audit --omit=dev`: PASS — 0 vulnerabilities.
- `npm ls next sharp --all`: Next 15.5.21; all sharp resolves to 0.35.3.
- Backend `python -m compileall -q -x 'venv|__pycache__' .`: PASS.
- Backend `python -m unittest discover -s tests -v`: PASS — 20 tests.
- `pip-audit -r requirements.lock`: PASS — no known vulnerabilities. (`pip-audit` was installed in disposable `/tmp/growthmap-remediation-venv`, not added to the application lock.)

## Residual blockers / release status

- Production dependency vulnerability targets are at 0; no vulnerability blocker remains for the requested production npm/Python gates.
- The full npm tree still reports 9 high advisories confined to development tooling; `npm audit --omit=dev` is 0 as required. This is disclosed rather than hidden or force-fixed.
- Candidate is **not released**: review, release commit, immutable `.2` tag, clean-checkout verification, and archive remain intentionally pending.

## Fresh-eyes blocker closure

- App-owned environment namespace is enforced on create, patch, and write; hostile process-variable names are regression-tested.
- Release bind policy is consistently IPv4 loopback/localhost only; IPv6 loopback spellings are intentionally rejected and tested.
- API/OpenAPI/root version is `0.1.0-authoring.2`; manifest integrity references only existing tracked artifacts.

## Third-pass fail-closed closure

- Removed the legacy secret-name resolution exception. Every provider profile, including `mock`, must have a namespaced `secret_env_key` before test-connection or AI resolution.
- Existing database rows bound to non-namespaced variables now fail closed with an explicit rebind/migration message; no unsafe legacy variable is resolved.
- Directly seeded `openai_compatible` and `mock` profiles using the historical unnamespaced key are rejected by secret write, connection test, and AI resolution regressions.
- User-facing settings, READMEs, and env examples use only `GROWTHMAP_LLM_KEY_DEFAULT` or the app-owned namespace.

- Namespace validation now centralizes consistent `rebind the profile to GROWTHMAP_LLM_KEY_[A-Z0-9_]{1,96}` guidance across create, patch, secret write, connection test, and AI resolution without echoing secret values.
