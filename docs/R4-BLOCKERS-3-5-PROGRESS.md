> **Historical record.** This document describes its own stated baseline/source-security record and is **not** current release or deployment guidance. See the [root README](../README.md) and [current release evidence](RELEASE-EVIDENCE.md).

# R4 blockers 3–5 report — 2026-07-29

Preserved worktree: `/tmp/zhu-growthmap-r4-1785312695`, branch `zhu-r4-remediation`. No reset, commit, push, or master/live work performed.

## Blocker 3 — touched-existing/CAS route audit

Implemented shared project/entity revision handling and focused route tests for:

- create-child parent CAS, stale/missing parent mutation-free behavior, parent relationship bump exactly once even when maturity does not change;
- mainline promotion: promoted edge + only actually demoted mainline sibling bump; untouched sibling remains unchanged;
- move/reparent old parent, new parent, and moved node each +1, project +1, replacement edge rev1;
- content-block owner +1 and new block rev1 even without maturity transition;
- branch copies remain rev1; merge now treats target node as an existing canonical mutation, requires `expected_target_revision`, and bumps target + source branch nodes + branch exactly once;
- artifact approval target ownership/update bump and proposal operation union remain transactionally covered by the route/service implementation and Agent Port tests.

The canonical matrix and source links remain in `docs/AGENT-PORT-v1.md`. Missing/stale CAS checks occur before project claim; successful transactions increment project exactly once, touched existing entities once, and new rows start at revision 1.

## Blocker 4 — real frontend orchestration

`runMutationWithConflict` is now wired through normal create, single suggestion, **acceptAllSuggestions**, deepen-summary, and deepen-block writes. `acceptDeepen` stops after a summary conflict rather than continuing block writes. Conflict behavior is no replay, exactly one refresh, visible error, and preserved suggestion/deepen input.

Added store-level tests invoking the real exported Zustand methods with captured API requests. They prove sequential revision propagation for accept-all and real summary/block 409 behavior.

## Blocker 5 — deterministic race/idempotency coverage

Fixed the SQLAlchemy lifecycle bug by snapshotting primitive grant/proposal IDs and payload fields before commit/rollback expiration; no expired ORM attribute is accessed after transaction lifecycle changes. Audited the batch service path, which already snapshots `grant_id`/`project_id`. Supplemental lock storage is now a fixed 256-stripe array rather than an unbounded key map.

Independent-client/session race tests cover batch, proposal, event, readback, and concurrent proposal approval. Assertions include identical durable responses, changed-payload 409, one activity row per kind, one canonical proposal effect, project/node +1 once, and terminal proposal approval. The focused suite surfaces exceptions, so MissingGreenlet/OperationalError/500 cannot pass silently.

## Exact verification

Repository backend venv used as required:

- `pytest test_r4_touched_revisions.py test_shared_revisions.py test_agent_port_v1.py test_smoke_api.py` → **25 passed**, 1 upstream Starlette deprecation warning.
- original focused three-file command → **10 passed**, 1 warning.
- frontend `npm test` → **6 passed**.
- frontend `npm run typecheck` → **passed**.
- `git diff --check` → see final handoff gate.

Blockers 6/7 remain parent-owned.

## Blocker 7 detached gate (2026-07-29)

The prior detached gate **BLOCKED** at mandatory `pip-audit` because `mcp==1.26.0` had three known advisories. Focused remediation in the preserved source now pins exact `mcp==1.28.1` in policy and the exact no-hash lock (including explicit MCP transitives). A fresh local Python 3.12.3 venv reported `pip check` clean and `pip-audit -r requirements.lock` **No known vulnerabilities found**; official MCP/live Agent Port focused tests passed 8/8, compileall passed, and the complete backend suite passed 79/79 with no skips. MCP 1.28.1 API inspection required no compatibility weakening or adapter behavior change. The protocol version remains `2025-11-25`, distinct from SDK package version 1.28.1.

This is only narrow remediation evidence: an **entirely new detached full blocker-7 gate remains mandatory**, including all previously unrun desktop/CSP/ASAR/provenance/Windows work. Exact evidence is in `docs/R4-BLOCKER-7-RELEASE-GATE.md`. No commit or push.


## Blocker 7 second detached gate completion

The mandatory entirely fresh second gate completed all Linux-applicable checks: backend 79/79, frontend 9/9, desktop 96/96, all with zero skips; Python and both npm audits reported zero vulnerabilities; post-build deterministic CSP verification passed and its sole changed generated manifest was synced. Exact materialization hashes, commands, logs, and Windows-only production provenance/ASAR/package limits are recorded in `docs/R4-BLOCKER-7-RELEASE-GATE.md`. Status: **R4 Linux detached gate PASS / ready to form a candidate commit for fresh independent Jian review**. No commit or push.

## Fresh-review remediation follow-up — 2026-07-29

Jian's fresh review at `62f5796` found H1 union-wide Agent owner CAS and H2 fresh-build CSP blockers. Remediation is underway on the preserved isolated worktree. Status is **PENDING A NEW FULL DETACHED GATE AND NEW FRESH JIAN REVIEW**; do not interpret prior PASS wording as applying to this new source state. No commit, push, merge, master/live mutation, package publication, or deployment has occurred.

## Third fresh detached gate after Jian H1/H2 remediation

The wholly new Linux detached gate at `/tmp/zhu-growthmap-r4-gate3-1785325381-974984` completed with backend **85/85**, frontend **9/9**, and desktop **96/96**, all with zero skips; Python and both npm production/full audits were clean; three-build cross-path deterministic CSP verification matched tracked manifest SHA-256 `44adadee693cbe570a6d3d637cebaebf6646478964d94a0835eeefe337d26b1c`. Exact provenance, caveats, and Windows-only platform blocks are in `docs/R4-BLOCKER-7-RELEASE-GATE.md`. Status: **R4 Linux detached gate PASS after fresh-review remediation / ready to form a new candidate commit for another fresh Jian review**. No commit or push.
