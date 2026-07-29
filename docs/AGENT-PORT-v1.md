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
