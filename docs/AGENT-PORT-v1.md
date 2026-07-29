# GrowthMap Agent Port v1

**Protocol:** `growthmap-agent-port` **Version:** `1.0` **Truth:** REST/JSON

Base URL: `http://127.0.0.1:<port>/agent/v1`. Only loopback clients and trusted local Host headers are accepted. Except `GET /capabilities`, requests require `Authorization: Bearer gm1.<12-hex-prefix>.<secret>`. Tokens in URLs are forbidden. JSON requests are limited to 1 MiB and 120 requests/grant/minute.

## Grants

GUI REST (`/api/agent-port`): `POST /grants`, `GET /grants?project_id=`, `POST /grants/{id}/revoke`, `GET /activity?project_id=`, `POST /proposals/{id}/approve|reject`. Grant creation accepts project, permission, at most one `node_scope_id`/`branch_root_id`, expiry (1 minute–90 days), label, and agent identity. Omit both scopes for project-wide. The response contains `token` exactly once.

Permission ordering: read < propose < write. Node scope is exact-node; branch scope contains its root and current `child_of` descendants. New references and both endpoints of relations are checked. Revoked/expired grants fail closed.

## Agent endpoints

- `GET /capabilities` — unauthenticated discovery, no project data.
- `GET /project`, `GET /graph` — grant-scoped canonical data and revisions.
- `GET /context/{target_id}?objective=` — target, ancestors, children, current decisions/constraints/risks/relations, revisions, and canonical SHA-256 snapshot digest.
- `POST /proposals` — propose/write grant. Body: `idempotency_key`, `expected_project_revision`, optional target, title/rationale, bounded operations. Canon remains unchanged until human approval.
- `POST /batch` — write grant. Body: `idempotency_key`, `expected_project_revision`, 1–50 operations.
- `POST /events` — propose/write grant; started/progress/blocked/completed/failed.
- `POST /readbacks` — propose/write grant; target, summary, commit refs, files, tests, decisions, risks, todos, evidence.

Batch operations are typed commands, never arbitrary patches: `create_node`, `update_node`, `create_edge`, `create_content_block`, `create_branch`. `update_node` also requires `expected_revision`. All shapes, permissions, revisions and scope references are validated before one transaction commits. Exact retry with the same idempotency key/payload returns the same receipt. Changed payload returns 409 `IDEMPOTENCY_MISMATCH`. Stale revisions return 409 `REVISION_CONFLICT`; nothing is applied.

## Error contract

JSON `detail` carries stable `code` values: `AUTH_REQUIRED`, `INVALID_TOKEN`, `GRANT_INACTIVE`, `LOCALHOST_ONLY`, `PERMISSION_DENIED`, `SCOPE_DENIED`, `REVISION_CONFLICT`, `IDEMPOTENCY_MISMATCH`, `RATE_LIMITED`. Validation is 422; missing resources 404. Clients must refresh after revision conflict.

## Thin clients

`scripts/growthmap_agent.py` exposes capabilities/project/graph/context/propose/apply-batch/report-event/submit-readback. Base URL is env or flag; token is env/file/stdin, never argv. JSON stdin/files produce JSON stdout and stable nonzero failures (2 input/transport, 3 HTTP, 4 auth/scope, 10 conflict).

`scripts/growthmap_mcp.py` is MCP JSON-RPC stdio and exposes matching tools. It forwards every call over REST and has no database or provider path.

## R3 security semantics

All agent references are UUIDs and are validated against the grant project and exact scope before any canonical write. Project scope may create roots. Exact-node and branch scopes may create nodes only beneath an in-scope parent; a child inherits the parent's branch and cannot cross branches. Branch scope is the bounded `child_of` descendant set rooted at the grant root and may manipulate only contained nodes, edges whose two endpoints are contained, blocks on contained nodes, and branches sourced inside it. Branch IDs must be active and owned by the same project. Same-batch IDs are reserved and validated before execution.

Revoking or expiring a grant invalidates every pending proposal from it. Approval reloads current proposal/grant/project state, re-runs the same operation validator, applies canon, writes the receipt/log, and marks approval in one transaction. Repeat review is deterministic; rejection never changes canon.

Canonical transactions increment the project revision exactly once and each touched pre-existing entity once. New entities start at revision 1. Context/read outputs are bounded (5,000-node scope, 500 children, 200 relevant records) and their digest covers the returned canonical snapshot. Agent Port mutations require project and entity revisions. Human control endpoints require a separate unguessable launch/session bearer in every mode (`GROWTHMAP_SESSION_TOKEN`, or explicit local `GROWTHMAP_HUMAN_CONTROL_TOKEN`); absent capability disables them. `/agent/v1` continues to use only grant bearers.

CLI and MCP accept only explicit-port plain HTTP at exact `localhost`, `127.0.0.1`, or `::1`; redirects are disabled. Token files are bounded regular non-symlinks and POSIX owner-only. Never place tokens in URLs. Last-used authentication bookkeeping is intentionally separate from canonical mutation atomicity.

## R3 implementation evidence (2026-07-29)

Implemented on branch `agent-port-v1-20260729` from reviewed baseline `5c34233ddce4302ce12997ef20134757767259ee`; master was not merged or modified. Closure includes strict discriminated operation schemas; all-reference/same-batch/scope/branch validation; atomic proposal review with grant revalidation; bounded graph/context; separate fail-closed human capability; hardened redirect-free loopback CLI/MCP transports; MCP initialize/tool/error semantics; receipt uniqueness/concurrency handling; prefix and rate-table bounds; and detached desktop interpreter dependency probing.

Verified locally: backend `60 passed`; Agent Port focused `4 passed`; frontend typecheck/lint/build; deterministic CSP generation; desktop `96 passed`; Python compileall and `git diff --check`. Remaining architectural work: migrating every legacy GUI canonical mutation route to mandatory shared optimistic-revision request fields is deliberately not represented as complete by this patch; those routes predate Agent Port and require a coordinated API/frontend contract migration. Agent Port itself remains fail-closed and revision-safe.
