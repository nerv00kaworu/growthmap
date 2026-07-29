# R4 blocker 7 detached release gate — 2026-07-29

Status: **R4 Linux detached gate PASS / ready to form a candidate commit for fresh independent Jian review**. The earlier failed attempt remains historical evidence; the entirely fresh second gate below is authoritative Linux evidence. No commit, push, tag, archive, publication, live DB, credentials, providers, payments, deployment, or master mutation was performed.

## Reproducibility

- Preserved source: `/tmp/zhu-growthmap-r4-1785312695`; HEAD/candidate `cb913327dcb85b16205921b3c51a465178c08e5e`.
- Verified `origin/master=fbcfeb7a9b8f147227c192cf2db3065561b30dac` and `origin/agent-port-v1-20260729=cb913327dcb85b16205921b3c51a465178c08e5e`.
- Fresh detached checkout: `/tmp/growthmap-r4-final-gate-1785316881-961049`.
- Materialization evidence: `/tmp/growthmap-r4-materialization-1785316881-961049`.
- Tracked binary patch SHA-256: `10b5334eb86b77aa0f66fc565607e18eba84f0048a7d887fd200665fe09ad757`.
- Untracked archive SHA-256: `962dba081fd98d31531d823d82ff3a91295d4073a5937bfa8de50542f5f43f4d`.
- Untracked manifest SHA-256: `d424aa95c68853e4720417a3a6c398748c8985a5f2e4a19c6854c4f9d9ad94b0`.
- Detached `git diff --binary HEAD` was byte-identical to the source patch, and every explicit untracked source file matched the SHA-256 manifest before testing.

## Commands and results before mandatory stop

- Fresh Python 3.12.3 venv: `python3 -m venv .gate-venv`; installed `requirements.lock` plus `packaging/requirements-test.txt`. Required imports including official `mcp.ClientSession` passed.
- `DATABASE_URL='sqlite+aiosqlite:///:memory:' .gate-venv/bin/python -m pytest -ra` → **79 passed, 0 skipped**, one upstream Starlette/httpx deprecation warning. This includes SharedRevisionContract (5), Agent Port security (4), official MCP (4), R4 migrations (3), context digest (1), and touched revisions (5); these are included in the 79 and not double-counted.
- Fresh frontend `npm ci` → 396 packages installed; both `npm audit --omit=dev` and full `npm audit` → **0 vulnerabilities**.
- Frontend `npm test` → **9 passed, 0 skipped**; lint, typecheck, and production build passed.
- Mandatory Python security gate `.gate-venv/bin/pip-audit -r requirements.lock` → **FAILED: 3 known vulnerabilities in `mcp==1.26.0`**: `PYSEC-2026-3482` (fix 1.27.2), `PYSEC-2026-3483` (fix 1.28.1), `PYSEC-2026-3481` (fix 1.27.2).

Per release discipline, execution stopped at that mandatory failure. Desktop install/tests/preflight, post-build CSP generation/verification, compileall, final `git diff --check`, production ASAR/provenance, and Windows gates were **not run** in this attempt. The Linux desktop production ASAR/provenance path is not canonical: the repository gate is PowerShell/Windows CI and requires fresh Windows packaging provenance. No Windows evidence is claimed.

## Focused MCP security remediation — 2026-07-29

In preserved source `/tmp/zhu-growthmap-r4-1785312695`, both dependency policy files now pin exact `mcp==1.28.1`. `requirements.lock` follows its existing reviewed exact-pin/no-hash format and now explicitly pins the MCP 1.28.1 transitive set (`attrs`, `httpx-sse`, `jsonschema`, `jsonschema-specifications`, `pydantic-settings`, `PyJWT`, `python-multipart`, `referencing`, `rpds-py`, and `sse-starlette`) rather than relying on floating resolution.

A fresh Python 3.12.3 venv at `/tmp/zhu-growthmap-mcp1281-final-venv` installed the exact updated lock plus `packaging/requirements-test.txt`; `pip check` reported no broken requirements, package metadata reported `mcp 1.28.1` with `Requires-Python >=3.10`, and `pip-audit -r requirements.lock` reported **No known vulnerabilities found**. Inspection confirmed the used 1.28.1 API signatures remain compatible (`ClientSession.initialize`, `list_tools`, `call_tool`, `stdio_client`, `StdioServerParameters`, and `McpError`), so no runtime adapter or schema/error/security compatibility weakening was required.

Focused official SDK/live tests passed **8/8**: `test_mcp_official.py` and `test_agent_port_v1.py`. This covers initialized protocol `2025-11-25`, canonical strict `tools/list` schemas, live localhost uvicorn/REST forwarding, malformed/oversize/invalid-param recovery, unknown/unsupported methods, stdout JSON purity, and bearer non-leakage from MCP/uvicorn stdout and stderr. `compileall` passed for `scripts/growthmap_mcp.py` and the backend. The complete backend suite then passed **79/79, 0 skipped**, with one upstream Starlette/httpx deprecation warning.

The MCP protocol version `2025-11-25` is intentionally distinct from SDK package version `mcp==1.28.1`; docs and the adapter module description now say so. Both temporary focused venvs were removed after recording results.

## Mandatory next step

Run an **entirely new detached full blocker-7 gate** materialized from the final candidate. Do not reuse the prior detached checkout, its venv, this source worktree, or the focused remediation venv as release evidence. The prior unrun desktop/CSP/ASAR/provenance/Windows gates remain unrun in this task.

## Mandatory second fresh detached full gate — 2026-07-29

Status: **R4 Linux detached gate PASS / ready to form a candidate commit for fresh independent Jian review**. This is not a release, merge, Windows package, or deployment PASS. No commit, push, tag, publication, credentials, live DB, provider call, master mutation, or deployment occurred.

### Fresh materialization and immutable refs

- Fresh detached worktree: `/tmp/growthmap-r4-second-gate-1785323120-964888` at `cb913327dcb85b16205921b3c51a465178c08e5e`; evidence: `/tmp/growthmap-r4-second-gate-1785323120-964888-evidence`. The prior failed worktree, its venv, dependencies, builds, and evidence were not reused.
- Before/after refs remained: candidate/`origin/agent-port-v1-20260729` = `cb913327dcb85b16205921b3c51a465178c08e5e`; `master`/`origin/master` = `fbcfeb7a9b8f147227c192cf2db3065561b30dac`.
- Source tracked binary patch SHA-256 `89c1bc60f09b991ae09615d5b5cc47fc4ae999447421a6e69c12905912b83fc9`; explicit untracked manifest `7b80238a09054c67c6469f45763324c0091d34c3a125eb7c5c6ff1dc0ac7a8a8`; archive `810e61f3ea625902562781f4436f7752fd92655479fd04a76b338189d9eda648`.
- Detached tracked binary diff compared byte-for-byte equal; sorted untracked path manifests and per-file SHA-256 lists compared equal before testing. Caches, dependencies, build outputs, DBs, and temp artifacts were excluded.

### Complete Linux-applicable results

- Fresh Python 3.12.3 `.gate-venv`; exact `requirements.lock`, canonical `packaging/requirements-test.txt`, and gate-only `pip-audit` installed. `pip check`: clean. `pip-audit -r requirements.lock`: **0 known vulnerabilities**. Import probes passed for FastAPI/SQLAlchemy/aiosqlite and official MCP (`ClientSession`, `StdioServerParameters`, `stdio_client`, `McpError`); exact package version **mcp 1.28.1**.
- `DATABASE_URL='sqlite+aiosqlite:///:memory:' .gate-venv/bin/python -m pytest -ra`: **79 passed, 0 skipped**, one upstream Starlette/httpx deprecation warning. The single full count includes, without double-counting focused subsets: Agent Port/security, official MCP ClientSession (including malformed/oversize/invalid/recovery and bearer-output boundaries), migrations, context digest, touched revisions, shared revision contract, races, and idempotency.
- Fresh frontend `npm ci`: 396 packages; `npm audit --omit=dev` and full `npm audit`: **0 vulnerabilities**; `npm test`: **9 passed, 0 skipped**; lint, typecheck, and production build passed.
- Strictly after the final frontend build, canonical `node desktop/scripts/generate-csp-manifest.js` plus `csp-manifest.verify(...)` passed. Deterministic manifest SHA-256: `96b1706f09cb4db5c93a91676cb37d578acfb97d37069d0853dc9afca5fb96ba`. It differed from the pre-gate tracked overlay and was the sole deterministic generated file synced to preserved source; source/detached hashes then matched.
- Fresh desktop `npm ci`: 287 packages; omit-dev and full audit: **0 vulnerabilities**; `npm test`: **96 passed, 0 skipped**. Production file-set E2E exclusions passed. Commercial preflight correctly failed closed without production legal/key/endpoint/signing inputs. Linux `npm run preflight` passed against the freshly built frontend/CSP and an explicitly isolated executable sidecar stub; this proves preflight behavior only, not packaged-sidecar provenance.
- Inspected repository scripts/workflow before platform classification. Actual production provenance/ASAR gates are `.github/workflows/scripts/new-node-provenance.ps1` and `verify-production-asar.ps1`, dependent on the Windows workflow's clean `desktop/node_modules`, Windows sidecar build (`src/backend/packaging/build-sidecar.ps1`), final `dist:win`, and packaged `app.asar`; `verify-windows-package.ps1`, `test-windows-database-boundaries.ps1`, renderer E2E, NSIS, Authenticode/updater metadata are likewise Windows-only/pending. No Linux production provenance/ASAR evidence is invented.
- Canonical no-credential checks passed: backend/scripts `compileall`; `git diff --check`; candidate path scan excluding ephemeral gate dependencies/builds; embedded-token scan (test vectors excluded and separately known synthetic); developer `/home`/`/Users`/source-coupled `/tmp` scan outside historical docs/lock registry URLs. No DB, developer venv, cache, build, node_modules, or temp source coupling entered the candidate.
- CLI/MCP inspection and tests confirm thin localhost REST clients, provider/model neutrality, bounded input/output, and no direct DB/model/filesystem authority beyond explicit token/input-file CLI reads. No privilege regression was found.

Full logs are `backend.log`, `frontend.log`, `csp.log`, `desktop.log`, `commercial-preflight.log`, and `final-static.log` under the evidence directory. Both the preserved source and detached worktree are retained for independent inspection.
