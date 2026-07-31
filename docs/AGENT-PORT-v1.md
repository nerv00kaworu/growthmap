# GrowthMap Agent Port v1

**Protocol:** `growthmap-agent-port` **Version:** `1.0` **Truth:** REST/JSON

Base URL: `http://127.0.0.1:<port>/agent/v1`. Only loopback clients and trusted local Host headers are accepted. Except `GET /capabilities`, requests require `Authorization: Bearer gm1.<12-hex-prefix>.<secret>`. Tokens in URLs are forbidden. JSON requests are limited to 1 MiB and 120 requests/grant/minute.

## Grants and human control

Agent Port REST remains provider-neutral. In v1, the **human grant, activity, and proposal-review GUI is desktop-only**: its menu and panel require explicit trusted desktop preload markers (`isDesktop` and `agentPortControl`). Normal web authoring—including a localhost browser—does not infer or bootstrap that capability. This does not disable other web authoring features.

Human-control REST (`/api/agent-port`): `POST /grants`, `GET /grants?project_id=`, `POST /grants/{id}/revoke`, `GET /activity?project_id=`, `POST /proposals/{id}/approve|reject`. Every route requires an explicit bearer capability. Desktop uses its per-launch `GROWTHMAP_SESSION_TOKEN`. Headless/local operators may explicitly configure `GROWTHMAP_HUMAN_CONTROL_TOKEN` and send it only in `Authorization: Bearer`; they must protect it as a local secret and retain loopback/trusted-host controls. With neither variable configured the routes are disabled, and there is no automatic web bootstrap.

Grant creation accepts project, permission, at most one `node_scope_id`/`branch_root_id`, expiry (1 minute–90 days), label, and agent identity. Omit both scopes for project-wide. The response contains `token` exactly once.

Permission ordering: read < propose < write. Node scope is exact-node; branch scope contains its root and current `child_of` descendants. New references and both endpoints of relations are checked. Revoked/expired grants fail closed.

## Agent endpoints

- `GET /capabilities` — unauthenticated discovery, no project data.
- `GET /project`, `GET /graph` — grant-scoped canonical data and revisions.
- `GET /context/{target_id}?objective=` — complete executable target/ancestor/child fields, scoped ordered content blocks, decisions/constraints/risks/relations, project/entity revisions, and canonical SHA-256 snapshot digest.
- `POST /proposals` — propose/write grant. Body: `idempotency_key`, `expected_project_revision`, optional target, title/rationale, bounded operations. Canon remains unchanged until human approval.
- `POST /batch` — write grant. Body: `idempotency_key`, `expected_project_revision`, 1–50 operations.
- `POST /events` — propose/write grant; started/progress/blocked/completed/failed.
- `POST /readbacks` — propose/write grant; target, required based-on project revision/context digest, summary, commit refs, files, tests, decisions, risks, todos, evidence; response marks current/stale provenance.

Batch operations are typed commands, never arbitrary patches: `create_node`, `update_node`, `create_edge`, `update_edge`, `delete_edge`, `create_content_block`, `update_content_block`, `delete_content_block`, `create_branch`. `update_node` requires `expected_revision`; creates require CAS for every existing canonical input: `expected_parent_revision`, endpoint `expected_from_revision`/`expected_to_revision`, `expected_node_revision`, and `expected_source_revision`. All shapes, permissions, revisions and scope references are validated before one transaction commits. Agent and human `create_node` share canonical validation/application (including branch inheritance, first-child mainline, parent touch, maturity and per-node provenance). Agent and GUI `create_content_block` likewise share canonical owner/reference validation, block staging, sanitized per-block history, owner touch and post-stage maturity evaluation; Agent and GUI `update_content_block` share canonical existing-block/owner/project validation, application, sanitized history, deduplicated block/owner touches and post-batch maturity; P0 updates existing blocks only and does not permit create-block→update-block dependencies in one batch. Agent and GUI `delete_content_block` share canonical existing-block/owner/project validation, IDs-only sanitized history, deduplicated owner touch and post-batch maturity; P0 deletes pre-existing blocks only and rejects create-block→delete-block and duplicate-delete batches; authorization, wire vocabulary/bounds, CAS, idempotency, transaction and commit remain adapter-owned. Agent and human `create_branch` share one transaction-local canonical primitive: it creates the active revision-1 Branch and deep-copies the complete `child_of` source subtree, ordered content blocks, and internal containment edges (including `is_mainline`) with distinct revision-1 IDs while leaving source entities untouched. The caller alone owns the single Project CAS, audit/receipt behavior, and commit. Exact retry with the same idempotency key/payload returns the same receipt. Changed payload returns 409 `IDEMPOTENCY_MISMATCH`. Stale revisions return 409 `REVISION_CONFLICT`; nothing is applied.

## Error contract

JSON `detail` carries stable `code` values (including non-leaking `CANONICAL_WRITE_CONFLICT` for malformed writes; only a durable matching receipt is treated as a genuine same-key race): `AUTH_REQUIRED`, `INVALID_TOKEN`, `GRANT_INACTIVE`, `LOCALHOST_ONLY`, `PERMISSION_DENIED`, `SCOPE_DENIED`, `REVISION_CONFLICT`, `IDEMPOTENCY_MISMATCH`, `RATE_LIMITED`. Validation is 422; missing resources 404. Clients must refresh after revision conflict.

## Thin clients

`scripts/growthmap_agent.py` exposes capabilities/project/graph/context/propose/apply-batch/report-event/submit-readback. Base URL is env or flag; token is env/file/stdin, never argv. JSON stdin/files produce JSON stdout and stable nonzero failures (2 input/transport, 3 HTTP, 4 auth/scope, 10 conflict).

`scripts/growthmap_mcp.py` is MCP JSON-RPC stdio and exposes matching tools. It forwards every call over REST and has no database or provider path. The adapter negotiates MCP protocol version `2025-11-25`; this protocol identifier is distinct from the pinned official Python SDK package version `mcp==1.28.1` used for client conformance tests.

## R3 security semantics

All agent references are UUIDs and are validated against the grant project and exact scope before any canonical write. Project scope may create roots. Exact-node and branch scopes may create nodes only beneath an in-scope parent; a child inherits the parent's branch and cannot cross branches. Branch scope is the bounded `child_of` descendant set rooted at the grant root and may manipulate only contained nodes, edges whose two endpoints are contained, blocks on contained nodes, and branches sourced inside it. Branch IDs must be active and owned by the same project. Same-batch IDs are reserved and validated before execution.

Revoking or expiring a grant invalidates every pending proposal from it. Approval reloads current proposal/grant/project state, re-runs the same operation validator, applies canon, writes the receipt/log, and marks approval in one transaction. Repeat review is deterministic; rejection never changes canon.

Canonical transactions increment the project revision exactly once and each touched entity once. New entities start at revision 1; if a later operation in the same batch mutates a new entity (for example, by adding its first child), its authoritative final revision advances once. Context/read outputs are bounded (5,000-node scope, 500 children, 200 relevant records) and their digest covers the returned canonical snapshot. Agent Port mutations require project and entity revisions. Human control endpoints require a separate unguessable launch/session bearer in every mode (`GROWTHMAP_SESSION_TOKEN`, or explicit local `GROWTHMAP_HUMAN_CONTROL_TOKEN`); absent capability disables them. `/agent/v1` continues to use only grant bearers.

CLI and MCP accept only explicit-port plain HTTP at exact `localhost`, `127.0.0.1`, or `::1`; redirects are disabled. Token files are bounded regular non-symlinks and POSIX owner-only. Never place tokens in URLs. Last-used authentication bookkeeping is intentionally separate from canonical mutation atomicity.

## R4 canonical touched-existing/CAS audit (2026-07-29)

`Project` is implicit in every canonical write and requires `expected_project_revision`; success increments it exactly once. “Touched” below means an existing canonical row whose state or owned relationship changes and therefore requires entity CAS and one revision bump. New rows start at revision 1.

| Canonical route | Direct and implicit existing mutations | Entity CAS inputs | Source |
|---|---|---|---|
| `POST /api/projects/{id}/nodes` | parent node (new child relationship and possible maturity advance) | `expected_parent_revision` when parent supplied | [`api/routes.py:create_node`](../src/backend/api/routes.py), [`models/schemas.py:NodeCreate`](../src/backend/models/schemas.py) |
| `PATCH/DELETE /api/nodes/{id}` | target node; delete also removes owned descendant/edge/block rows rather than revising deleted rows | `expected_revision` | [`api/routes.py`](../src/backend/api/routes.py) |
| `POST /api/edges` | any currently-mainline sibling edges demoted; created edge is rev1 | no endpoint CAS currently; project CAS only | [`api/routes.py:create_edge`](../src/backend/api/routes.py), `demote_mainline_siblings` |
| `PATCH /api/edges/{id}` | target edge | `expected_revision` | [`api/routes.py:update_edge`](../src/backend/api/routes.py) |
| edge/mainline promote routes | promoted edge plus every mainline sibling actually demoted | promoted edge `expected_revision`; siblings are implicit | [`api/routes.py:promote_mainline`](../src/backend/api/routes.py), `promote_child_mainline` |
| move/reparent | moved node, old parent node, new parent node; old `child_of` Edge is deleted and replacement Edge is new rev1 (the relationship is an `Edge`, not a `Node`) | moved `expected_revision`, `expected_old_parent_revision`, `expected_new_parent_revision` | [`api/routes.py:move_node`](../src/backend/api/routes.py), `reparent_node` |
| content block create | owner node once (ownership/content richness and possible maturity); block new rev1 | `expected_node_revision` | shared [`services/canonical_content_blocks.py`](../src/backend/services/canonical_content_blocks.py), GUI [`api/routes.py:create_block`](../src/backend/api/routes.py), Agent batch |
| content block update | block and owner node | `expected_revision`, `expected_node_revision` | [`api/routes.py:update_block`](../src/backend/api/routes.py) |
| content block delete | owner node; deleted block has no post-delete revision | `expected_revision`, `expected_node_revision` | [`api/routes.py:delete_block`](../src/backend/api/routes.py) |
| branch create | no existing canonical entity is intended to change; copied nodes/blocks/edges and branch are rev1 | project CAS only; source is read input | [`api/routes.py:create_branch`](../src/backend/api/routes.py) |
| branch merge | source branch becomes merged; every existing branch node is cleared/reassigned; target node gains child relationship; old branch-root relationship Edge deleted, new Edge rev1 | branch `expected_revision`; target `expected_target_revision` | [`api/routes.py:merge_branch`](../src/backend/api/routes.py) |
| artifact approve | target node always (update, new child relationship, or new block ownership); created child/edge/block rev1 | `expected_node_revision` | [`api/routes.py:approve_agent_artifact`](../src/backend/api/routes.py) |
| Agent proposal approve | union of each operation: update-node targets; create-node parents; content-block owner nodes; create-edge endpoints; created rows rev1; branch source is CAS-validated read input and deliberately not bumped; proposal terminal state and receipt commit atomically | project CAS plus every existing operation owner/input CAS exposed by operation schema | [`agent_port/routes.py:review`](../src/backend/agent_port/routes.py), [`agent_port/service.py:apply_batch`](../src/backend/agent_port/service.py) |
| Agent batch | same operation union as proposal approval, deduplicated transaction-locally; existing parent/owner/edge endpoints bump once, new rows remain rev1; branch source is derived-from read input and does not bump | project CAS and operation CAS | [`agent_port/service.py`](../src/backend/agent_port/service.py) |

Focused audit progress and unresolved gaps are recorded in [`docs/R4-BLOCKERS-3-5-PROGRESS.md`](R4-BLOCKERS-3-5-PROGRESS.md); this table is an audit, not a claim that every listed gap is closed.

## R3 implementation evidence (2026-07-29)

Implemented on branch `agent-port-v1-20260729` from reviewed baseline `5c34233ddce4302ce12997ef20134757767259ee`; master was not merged or modified. Closure includes strict discriminated operation schemas; all-reference/same-batch/scope/branch validation; atomic proposal review with grant revalidation; bounded graph/context; separate fail-closed human capability; hardened redirect-free loopback CLI/MCP transports; MCP initialize/tool/error semantics; receipt uniqueness/concurrency handling; prefix and rate-table bounds; and detached desktop interpreter dependency probing.

Verified locally: backend `60 passed`; Agent Port focused `4 passed`; frontend typecheck/lint/build; deterministic CSP generation; desktop `96 passed`; Python compileall and `git diff --check`. Remaining architectural work: migrating every legacy GUI canonical mutation route to mandatory shared optimistic-revision request fields is deliberately not represented as complete by this patch; those routes predate Agent Port and require a coordinated API/frontend contract migration. Agent Port itself remains fail-closed and revision-safe.

## P0 executable context/readback slice (2026-07-30)

This slice makes the scoped context packet executable: target, in-scope ancestors/children/relevant nodes carry implementation fields (rules, examples, questions, priority/confidence, workflow status, file paths, authorship and revisions), while ordered in-scope content blocks include node/type/content/order/revision and creator source attribution. The canonical digest covers the complete returned packet, including these fields and blocks; deterministic query/order rules keep unchanged packets stable. Authorship (`created_by`/`last_edited_by`) is intentionally digest-visible, so equivalent GUI and Agent mutations have equal graph semantics after provenance normalization but distinct raw context digests. Grant project/node/branch filtering happens before node, relation, block, or attribution serialization.

Implementation readbacks now require `based_on_project_revision`, the bounded context `objective` (empty is valid), and the 64-character lowercase SHA-256 `context_snapshot_digest`. They record those values plus submission-time `current_project_revision` and `context_stale`; the same objective is used when recomputing provenance. A revision, objective-context digest, or target-context digest mismatch is accepted as historical evidence but explicitly stale. Readback/event ledger writes do not advance canonical project revision. Human activity and the desktop panel expose revision provenance, digest fingerprint, stale/current state, and commits/files/tests/decisions/risks/todos/evidence.

CLI `context --target ID --objective TEXT` and MCP `get_context {target_id, objective}` preserve the same bounded objective through URL-encoded REST queries. Empty objective remains compatible. Packaged v1 databases without an Agent Port readback table migrate transactionally to the canonical v2 ledger, indexes, stale-safe defaults, and validation surface. A legacy table is upgraded only when its complete core columns, foreign keys, and index semantics are canonical; partial or drifted legacy ledgers fail closed and require repair/export rather than inferred rebuilding.

Deferred: readbacks without a target cannot reconstruct a target context and are therefore marked stale. This slice does not add agent dispatch, repository access, payments, or claim the broader Agent Port product loop is complete.


Shared-truth status: `create_node`, `update_node`, `create_edge`, `update_edge`, `delete_edge`, `create_content_block`, `update_content_block`, `delete_content_block`, and `create_branch` now use shared canonical primitives across GUI and Agent entry points. P0 `update_edge` is restricted to weight/note on pre-existing non-`child_of` relations with persisted two-endpoint scope and union CAS. P0 `delete_edge` accepts only pre-existing non-`child_of` relations, requires both persisted endpoints in scope, performs project+edge CAS without touching endpoints, and writes IDs-only sanitized history. Full graph/context read services remain deferred to later slices.

### Shared canonical update intersection

`update_node` shares its canonical mutation service with GUI REST for title, summary,
status, maturity, priority, confidence, formal text fields, tags, workflow status,
and file paths. Omitted fields remain unchanged; explicit null and an empty fields
object are validation errors; empty lists clear tags/file paths. Maturity uses only
`seed`, `rough`, `developing`, `stable`, and `finalized`. GUI-only node type and
canvas position remain outside Agent Port. Create-edge, update-edge, create-content-block,
update-content-block, and delete-content-block are shared; delete-edge and full
graph/context read services remain deferred.
