# GrowthMap Agent Port v1.0 — Canonical LLM Onboarding Guide

```yaml
audience: external_llm_or_ai_agent
protocol: growthmap-agent-port
version: "1.0"
transport: MCP stdio
mcp_protocol_version: "2025-11-25"
purpose: safe_machine_operation
not_for: human_gui_operation
schema_authority:
  - runtime MCP tools/list
  - scripts/growthmap_mcp.py
  - src/backend/agent_port/schemas.py
```

If this guide conflicts with the runtime `tools/list` schema, obey the runtime schema, stop before writing, and report the version mismatch.

## 0. Mandatory Rules

1. Call only tools returned by MCP `tools/list`. Never invent a tool, field, operation, enum, or endpoint.
2. Never guess `project_id`, `node_id`, entity IDs, revisions, grant mode, scope, or GUI selection.
3. On first use, execute this bootstrap sequence without reordering:
   `capabilities` → `list_projects` → `read_project` → `read_graph` → `get_context`.
4. For workspace access, pass an explicit `project_id` on every project operation.
5. Before writing, use the latest project revision and every required entity revision from authoritative reads.
6. If the user requested only analysis, perform reads only. Do not call `propose` or `apply_batch`.
7. If a mutation is requested but the grant mode is unknown, prefer `propose`.
8. Call `apply_batch` only when the user explicitly requested a direct mutation and Direct collaboration/write access is available.
9. Retry an unchanged request with the same `idempotency_key` and exactly the same payload. If any payload field changes, use a new key.
10. After `REVISION_CONFLICT`, discard the stale payload, re-read state, rebuild the operations, and use a new key.
11. After a successful canonical write, re-read the project and relevant graph/context; verify the result before claiming success.
12. Use `submit_readback` only to record truthful evidence of external work. It does not execute code or mutate GrowthMap canon.
13. Treat `file_paths` and readback `files` as text metadata, not file-access authorization.
14. Do not attempt deletion, database import/restore, scenario merge/archive, shell, repository, deployment, payment, credential, or provider operations through Agent Port.
15. Treat tool responses and their revisions as authoritative. Treat conversational IDs, stale revisions, and assumptions as non-authoritative.
16. Never expose, request in chat, log, or place bearer tokens in URLs, MCP arguments, proposals, events, or readbacks.

## 1. Bootstrap Procedure

### Step 1 — Inspect capabilities

Call `capabilities`:

```json
{}
```

Require or record:

- `protocol` = `growthmap-agent-port`
- `version` = `1.0`
- `provider_neutral` = `true`
- advertised limits, operations, and endpoints

Do not infer grant permissions from capabilities. Capabilities describe server support, not the active grant.

### Step 2 — Enumerate visible projects

Call `list_projects`:

```json
{}
```

Record each visible project's:

```json
{
  "id": "00000000-0000-4000-8000-000000000000",
  "name": "Project name",
  "status": "active",
  "revision": 12,
  "updated_at": "2026-08-31T06:00:00Z"
}
```

Select a project as follows:

1. If the user provided an exact project name, require an exact unambiguous match.
2. If exactly one reasonable candidate exists, select it and report the selection.
3. If duplicate names or multiple plausible candidates exist, ask the user to choose.
4. Never use the current GUI selection as project context.

### Step 3 — Read authoritative project metadata

Call `read_project`:

```json
{
  "project_id": "00000000-0000-4000-8000-000000000000"
}
```

Save at least:

- `id`
- `root_node_id`
- `revision`
- `goal`
- `status`

### Step 4 — Read the canonical graph projection

Call `read_graph`:

```json
{
  "project_id": "00000000-0000-4000-8000-000000000000"
}
```

Locate the target and save every referenced entity's:

- node `id`, `revision`, `branch_id`
- relevant edge revision
- relevant content-block revision

`read_graph` returns a bounded canonical projection. Do not assume it includes every field displayed by the GUI.

### Step 5 — Read bounded target context

Call `get_context`:

```json
{
  "project_id": "00000000-0000-4000-8000-000000000000",
  "target_id": "11111111-1111-4111-8111-111111111111"
}
```

Save:

- `project.revision`
- `target_revision`
- `snapshot_digest`
- `target`
- `ancestors`
- `children`
- `relevant`
- `relations`

Do not add `objective`; the MCP input schema does not accept it. Use revisions for CAS. Use `snapshot_digest` only for traceability or before/after comparison.

Do not analyze or design a mutation until the bootstrap sequence is complete.

## 2. Permission Decision Tree

```text
Did the user request analysis only?
├─ YES → Read only. Return analysis. Do not call propose or apply_batch.
└─ NO → Did the user request a mutation?
   ├─ NO → Read only.
   └─ YES → Is the grant mode known?
      ├─ NO → Call propose.
      └─ YES → Which mode?
         ├─ Read only → Do not write. Report that authorization or manual action is required.
         ├─ Review first → Call propose.
         └─ Direct collaboration/write
            ├─ User explicitly requested direct mutation → Call apply_batch.
            └─ Otherwise → Call propose.
```

Tool visibility does not imply permission. The server can list a tool that the active grant denies.

## 3. Product Data Model

### 3.1 Project

Treat a project as the top-level graph container. Scope every read and write to an explicit project.

Important fields:

- `id`: project UUID
- `root_node_id`: main graph root UUID
- `revision`: monotonically increasing project revision
- `goal`: project goal
- `status`: project status

A successful canonical transaction increments project revision exactly once, regardless of operation count.

### 3.2 Node

Treat a node as the primary content entity. Common fields include:

- `id`, `title`, `summary`, `node_type`
- `status`, `maturity`
- `description`, `constraints_text`, `decision_notes`
- `tags`, `branch_id`, `revision`

### 3.3 Edge

Treat `child_of` as containment. Treat other relation types as directed semantic relations.

Use only these exact wire values:

```json
[
  "child_of",
  "extends",
  "depends_on",
  "supports",
  "alternative_to",
  "refines",
  "references",
  "conflicts_with"
]
```

Do not map GUI labels to unverified wire values.

### 3.4 Content Block

Treat a content block as structured content owned by a node. Creating one touches its owner node; always provide `expected_node_revision`.

### 3.5 Branch / Scenario

Treat `create_branch` as a deep copy of a source node's complete `child_of` subtree, ordered content blocks, and internal containment edges. It does not mutate source entities. Use `create_node`, not `create_branch`, when adding only one idea or child.

### 3.6 Canon, Proposal, Event, and Readback

- **Canon:** formal Project, Node, Edge, Content Block, Branch, and related graph data.
- **Proposal:** a pending typed mutation plan; creating it does not change canon.
- **Event:** progress metadata; it does not change canon.
- **Readback:** auditable external-work evidence; it does not replace canonical mutation.

## 4. Tool Catalog — All 9 Tools

### 4.1 `capabilities`

Use it to inspect protocol identity, limits, operations, and endpoints.

```json
{}
```

Call it on first connection, suspected version mismatch, or behavior/schema mismatch. Do not infer active grant mode from it.

### 4.2 `list_projects`

Use it to list up to 100 recent projects visible to the grant.

```json
{}
```

Do not choose a merely similar name when intent is ambiguous.

### 4.3 `read_project`

Use it to read one project's metadata and authoritative revision.

```json
{
  "project_id": "00000000-0000-4000-8000-000000000000"
}
```

Pass a UUID string.

### 4.4 `read_graph`

Use it to locate entity IDs, understand visible structure, acquire entity revisions, and verify writes.

```json
{
  "project_id": "00000000-0000-4000-8000-000000000000"
}
```

For large graphs, locate the target first and then call `get_context`. Do not rewrite unrelated nodes.

### 4.5 `get_context`

Use it to retrieve a bounded target context packet.

```json
{
  "project_id": "00000000-0000-4000-8000-000000000000",
  "target_id": "11111111-1111-4111-8111-111111111111"
}
```

Accepted fields are exactly `project_id` and `target_id`.

### 4.6 `propose`

Use it for Review first, unknown grant mode, semantic uncertainty, risk requiring review, or any request that should be approved before canonical mutation.

```json
{
  "project_id": "00000000-0000-4000-8000-000000000000",
  "idempotency_key": "proposal.login-tests.001",
  "expected_project_revision": 12,
  "target_node_id": "11111111-1111-4111-8111-111111111111",
  "title": "Add login test plan",
  "rationale": "Add missing security and expired-session acceptance coverage.",
  "operations": [
    {
      "op": "create_node",
      "parent_id": "11111111-1111-4111-8111-111111111111",
      "expected_parent_revision": 4,
      "title": "Expired session test",
      "summary": "Verify that an expired session is rejected.",
      "node_type": "task"
    }
  ]
}
```

Constraints:

- `project_id`: operationally required for workspace access; schema type is UUID-like ID
- `idempotency_key`: 8–80 characters, matching `^[A-Za-z0-9._:-]+$`
- `expected_project_revision`: integer ≥ 1
- `target_node_id`: optional, but must be in scope when supplied
- `title`: 1–200 characters
- `rationale`: 0–4,000 characters; defaults to `""`
- `operations`: 1–50 strict typed operations

Expected success shape:

```json
{
  "proposal_id": "22222222-2222-4222-8222-222222222222",
  "status": "pending",
  "project_revision": 12,
  "canonical_changed": false
}
```

Report the proposal as pending. Never claim its operations were applied.

### 4.7 `apply_batch`

Use it only for explicit direct mutation under Direct collaboration/write authorization.

```json
{
  "project_id": "00000000-0000-4000-8000-000000000000",
  "expected_project_revision": 12,
  "idempotency_key": "batch.login-tests.001",
  "operations": [
    {
      "op": "create_node",
      "parent_id": "11111111-1111-4111-8111-111111111111",
      "expected_parent_revision": 4,
      "title": "Expired session test",
      "summary": "Verify that expired sessions cannot access protected resources.",
      "node_type": "task"
    }
  ]
}
```

Apply atomically:

- Commit only if every operation passes schema, scope, and revision checks.
- Apply nothing if any operation fails.
- Increment project revision once for the successful transaction.
- After success, call `read_project` and then `read_graph` and/or `get_context` to verify.

### 4.8 `report_event`

Use it for meaningful start, progress, blocker, completion, or failure milestones. Review first and Direct collaboration may permit it; Read only rejects it.

```json
{
  "project_id": "00000000-0000-4000-8000-000000000000",
  "idempotency_key": "event.login-tests.started.001",
  "target_node_id": "11111111-1111-4111-8111-111111111111",
  "event_type": "started",
  "message": "Started structuring the login test plan.",
  "payload": {
    "phase": "analysis"
  }
}
```

Use only these exact `event_type` values:

```json
["started", "progress", "blocked", "completed", "failed"]
```

Constraints:

- `message`: 1–4,000 characters
- `payload`: at most 100 entries
- payload key: at most 100 characters
- payload value: string, at most 4,000 characters

Do not emit high-frequency duplicate events.

### 4.9 `submit_readback`

Use it to record truthful, auditable evidence of external implementation or research.

```json
{
  "project_id": "00000000-0000-4000-8000-000000000000",
  "idempotency_key": "readback.login-tests.001",
  "target_node_id": "11111111-1111-4111-8111-111111111111",
  "summary": "Completed login and expired-session regression tests.",
  "commit_refs": ["abc1234"],
  "files": ["tests/auth/login.test.ts"],
  "tests": [
    {
      "name": "auth focused tests",
      "status": "passed",
      "detail": "18 passed"
    }
  ],
  "decisions": ["Return 401 for every expired session."],
  "risks": ["Windows ARM64 has not been verified."],
  "todos": ["Run the full integration suite."],
  "evidence": [
    {
      "name": "git diff",
      "status": "verified",
      "detail": "Only login tests and the session guard changed."
    }
  ]
}
```

Record schema:

```json
{
  "name": "Required; 1-200 characters",
  "status": "Optional; 0-100 characters",
  "detail": "Optional; 0-4000 characters"
}
```

Constraints:

- `summary`: at most 8,000 characters
- `commit_refs`: at most 100 strings, each at most 200 characters
- `files`: at most 500 strings, each at most 1,024 characters
- `tests`: at most 200 records
- `evidence`: at most 200 records
- `decisions`, `risks`, `todos`: each at most 200 strings, each at most 2,000 characters
- canonical readback payload: at most 256 KiB

Never report a commit, test, verification, or result that did not occur. Leave unsupported evidence arrays empty and state limitations honestly in `summary`.

## 5. Typed Operation Schemas — All 5 Types

All operation models are strict. Extra fields are forbidden.

### 5.1 `create_node`

```json
{
  "op": "create_node",
  "id": "33333333-3333-4333-8333-333333333333",
  "parent_id": "11111111-1111-4111-8111-111111111111",
  "expected_parent_revision": 3,
  "branch_id": null,
  "title": "Add login tests",
  "summary": "Cover successful and failed login cases.",
  "node_type": "task"
}
```

Fields and constraints:

- `op`: exactly `create_node`
- `id`: optional caller-generated 36-character UUID-like ID
- `parent_id`: optional 36-character UUID-like ID
- `expected_parent_revision`: integer ≥ 1; supply if and only if `parent_id` is supplied
- `branch_id`: optional 36-character UUID-like ID or `null`; never cross project or branch scope
- `title`: required, 1–500 characters
- `summary`: optional, at most 500 characters, default `""`
- `node_type`: optional, default `idea`; exact values:

```json
["idea", "concept", "task", "question", "decision", "risk", "resource", "note", "module", "spec"]
```

Unless the request explicitly requires a project-level root, provide a parent and do not create an orphan node.

### 5.2 `update_node`

```json
{
  "op": "update_node",
  "node_id": "11111111-1111-4111-8111-111111111111",
  "expected_revision": 4,
  "fields": {
    "summary": "Added login security tests and acceptance criteria.",
    "workflow_status": "review",
    "confidence": 0.8
  }
}
```

Required fields: `node_id`, `expected_revision`, `fields`.

Allowed `fields` properties:

| Field | Exact constraint |
|---|---|
| `title` | string, 1–500 characters |
| `summary` | string, 0–500 characters |
| `description` | string, 0–16,384 characters |
| `rules_text` | string, 0–16,384 characters |
| `constraints_text` | string, 0–16,384 characters |
| `examples_text` | string, 0–16,384 characters |
| `questions_text` | string, 0–16,384 characters |
| `decision_notes` | string, 0–16,384 characters |
| `tags` | at most 50 strings; each at most 100 characters |
| `status` | `active`, `archived`, or `completed` |
| `maturity` | `seed`, `sprout`, `growing`, or `mature` |
| `priority` | integer from -100 through 100 |
| `confidence` | number from 0 through 1 |
| `workflow_status` | `draft`, `review`, `approved`, or `archived` |
| `file_paths` | at most 100 strings; each at most 1,024 characters |

Use the exact wire enums above even if GUI labels differ. Include only fields that must change; do not echo and overwrite the complete old node.

### 5.3 `create_edge`

```json
{
  "op": "create_edge",
  "id": "44444444-4444-4444-8444-444444444444",
  "from_node_id": "11111111-1111-4111-8111-111111111111",
  "to_node_id": "55555555-5555-4555-8555-555555555555",
  "expected_from_revision": 2,
  "expected_to_revision": 5,
  "relation_type": "depends_on",
  "weight": 1.0,
  "note": "Release work depends on completed tests."
}
```

Fields and constraints:

- `op`: exactly `create_edge`
- `id`: optional 36-character UUID-like ID
- `from_node_id`, `to_node_id`: required and in scope
- `expected_from_revision`, `expected_to_revision`: required integers ≥ 1
- `relation_type`: optional, default `child_of`; use only the exact values in Section 3.3
- `weight`: number from -1000 through 1000; default `1.0`
- `note`: at most 500 characters; default `""`

Validate direction by reading: “source node `<relation_type>` target node.” If that statement is false or unclear, do not write.

### 5.4 `create_content_block`

```json
{
  "op": "create_content_block",
  "id": "66666666-6666-4666-8666-666666666666",
  "node_id": "11111111-1111-4111-8111-111111111111",
  "expected_node_revision": 6,
  "block_type": "spec",
  "content": {
    "title": "Acceptance criteria",
    "body": "1. Valid login succeeds.\n2. Expired sessions return 401."
  },
  "order_index": 0
}
```

Fields and constraints:

- `op`: exactly `create_content_block`
- `id`: optional 36-character UUID-like ID
- `node_id`: required owner ID
- `expected_node_revision`: required integer ≥ 1
- `block_type`: optional, default `paragraph`; exact values:

```json
[
  "paragraph",
  "bullet_list",
  "rule_set",
  "example",
  "risk_note",
  "decision_log",
  "todo",
  "prompt_context",
  "code",
  "quote",
  "table",
  "text",
  "markdown",
  "note",
  "question",
  "task",
  "decision",
  "risk",
  "resource",
  "definition",
  "rules",
  "spec"
]
```

- `content`: object with at most 100 entries; key ≤ 100 characters; value must be a string ≤ 16,384 characters
- `order_index`: integer from 0 through 100000; default `0`

Read existing blocks before choosing an insertion index when ordering matters.

### 5.5 `create_branch`

```json
{
  "op": "create_branch",
  "id": "77777777-7777-4777-8777-777777777777",
  "source_node_id": "11111111-1111-4111-8111-111111111111",
  "expected_source_revision": 7,
  "name": "Option B: Passwordless login",
  "description": "Explore a passkey-only alternative."
}
```

Fields and constraints:

- `op`: exactly `create_branch`
- `id`: optional 36-character UUID-like ID
- `source_node_id`: required
- `expected_source_revision`: required integer ≥ 1
- `name`: 1–255 characters
- `description`: at most 4,000 characters; default `""`

Do not use this operation to add one ordinary child node.

## 6. Copy-Ready Workflows

### 6.1 Read-only analysis

```text
1. capabilities({})
2. list_projects({})
3. read_project({"project_id":"<PROJECT_UUID>"})
4. read_graph({"project_id":"<PROJECT_UUID>"})
5. get_context({"project_id":"<PROJECT_UUID>","target_id":"<TARGET_NODE_UUID>"})
6. Return an evidence-based analysis. Call no mutation tool.
```

Report the project name and ID, target node, observed project revision and snapshot, and the fact that GrowthMap was not modified.

### 6.2 Review-first proposal with two child nodes and one spec block

Replace every placeholder. Replace integer placeholders with JSON numbers, not quoted strings.

```json
{
  "project_id": "<PROJECT_UUID>",
  "idempotency_key": "proposal.auth-plan.20260831.001",
  "expected_project_revision": 12,
  "target_node_id": "<TARGET_NODE_UUID>",
  "title": "Complete the login test plan",
  "rationale": "The target lacks valid-login, expired-session, and explicit acceptance coverage.",
  "operations": [
    {
      "op": "create_node",
      "parent_id": "<TARGET_NODE_UUID>",
      "expected_parent_revision": 4,
      "title": "Valid login test",
      "summary": "Verify that valid credentials create a session.",
      "node_type": "task"
    },
    {
      "op": "create_node",
      "parent_id": "<TARGET_NODE_UUID>",
      "expected_parent_revision": 4,
      "title": "Expired session test",
      "summary": "Verify rejection of expired sessions with a 401 response.",
      "node_type": "task"
    },
    {
      "op": "create_content_block",
      "node_id": "<TARGET_NODE_UUID>",
      "expected_node_revision": 4,
      "block_type": "spec",
      "content": {
        "title": "Login acceptance criteria",
        "body": "Valid credentials succeed; invalid credentials fail; expired sessions return 401."
      },
      "order_index": 0
    }
  ]
}
```

When several operations in one batch reference the same existing node, use the same revision from the authoritative pre-write read. The server merges the touched-existing revision bump inside the transaction.

After success, report proposal ID, report `canonical_changed: false`, and wait for human approval.

### 6.3 Direct collaboration batch

```json
{
  "project_id": "<PROJECT_UUID>",
  "expected_project_revision": 12,
  "idempotency_key": "batch.auth-child.20260831.001",
  "operations": [
    {
      "op": "create_node",
      "parent_id": "<TARGET_NODE_UUID>",
      "expected_parent_revision": 4,
      "title": "Expired session test",
      "summary": "Verify that expired sessions cannot access protected resources.",
      "node_type": "task"
    }
  ]
}
```

Immediately after success:

1. Call `read_project`.
2. Call `read_graph` or `get_context` for the target.
3. Confirm the new node exists and matches the request.
4. Report the new project revision.

### 6.4 Same-batch forward reference

Generate a valid caller ID before submission. Reference a newly created entity at revision `1`.

```json
{
  "project_id": "<PROJECT_UUID>",
  "expected_project_revision": 12,
  "idempotency_key": "batch.forward-ref.20260831.001",
  "operations": [
    {
      "op": "create_node",
      "id": "11111111-1111-4111-8111-111111111111",
      "parent_id": "<PARENT_UUID>",
      "expected_parent_revision": 3,
      "title": "Login test specification",
      "node_type": "spec"
    },
    {
      "op": "create_content_block",
      "node_id": "11111111-1111-4111-8111-111111111111",
      "expected_node_revision": 1,
      "block_type": "spec",
      "content": {
        "title": "Scope",
        "body": "Cover successful, failed, and expired-session cases."
      },
      "order_index": 0
    }
  ]
}
```

Do not create cyclic same-batch dependencies. A cycle rejects the entire batch.

### 6.5 Progress event

```json
{
  "project_id": "<PROJECT_UUID>",
  "idempotency_key": "event.auth-tests.progress.002",
  "target_node_id": "<TARGET_NODE_UUID>",
  "event_type": "progress",
  "message": "Completed login test design; verifying the expired-session boundary.",
  "payload": {
    "completed": "test design",
    "current": "expired-session verification"
  }
}
```

### 6.6 External-work readback

```json
{
  "project_id": "<PROJECT_UUID>",
  "idempotency_key": "readback.auth-tests.20260831.001",
  "target_node_id": "<TARGET_NODE_UUID>",
  "summary": "Completed login tests; the focused suite passed.",
  "commit_refs": ["abc1234"],
  "files": [
    "src/auth/session.ts",
    "tests/auth/session.test.ts"
  ],
  "tests": [
    {
      "name": "auth focused suite",
      "status": "passed",
      "detail": "18 passed, 0 failed"
    }
  ],
  "decisions": ["Return 401 for every expired session."],
  "risks": [],
  "todos": ["Run the full desktop integration suite."],
  "evidence": [
    {
      "name": "focused test output",
      "status": "verified",
      "detail": "18 passed, 0 failed"
    }
  ]
}
```

## 7. Revision, CAS, and Idempotency

### 7.1 Capture revisions before writing

Capture at least:

- latest project revision
- each existing update target's node revision
- each create parent node revision
- both endpoint revisions for every new edge
- each content-block owner revision
- each branch source revision

### 7.2 Project CAS

Set `expected_project_revision` to the current authoritative project revision.

If two writers use the same revision concurrently:

- exactly one can succeed;
- the other receives `409 REVISION_CONFLICT`.

Never loop on a stale revision.

### 7.3 Entity CAS mapping

```yaml
update_node: expected_revision
create_node_with_parent: expected_parent_revision
create_edge:
  - expected_from_revision
  - expected_to_revision
create_content_block: expected_node_revision
create_branch: expected_source_revision
```

Missing required owner CAS fails validation.

### 7.4 Idempotency rules

Valid examples:

```text
proposal.auth-plan.20260831.001
batch:auth-plan:001
event_auth_progress_002
```

Invalid examples:

```text
short
contains spaces
contains/slash
```

Apply these rules:

1. Same grant + same key + byte-equivalent/semantically identical payload: expect the original receipt and no duplicate write.
2. Same key + changed payload: expect `409 IDEMPOTENCY_MISMATCH`.
3. If transport failure makes success unknown, retry the exact original payload with the exact original key.
4. If any content, revision, operation, or field changes, generate a new key.

## 8. Post-Write Verification

### For `propose`

1. Require a non-error tool response.
2. Confirm `status` is pending.
3. Confirm `canonical_changed` is `false`.
4. Report proposal ID and project revision.
5. State that human approval is required before the plan affects canon.

### For `apply_batch`

1. Require a non-error tool response.
2. Call `read_project` with the same `project_id`.
3. Confirm the project revision changed as expected; one successful transaction should increment it exactly once.
4. Call `read_graph` and/or `get_context` for every affected area.
5. Confirm created/updated entities, relationships, blocks, and branches match the intended operations.
6. Report only verified changes.
7. Mark missing, divergent, untested, or blocked outcomes explicitly.

Do not equate “request sent” with “write succeeded.”

## 9. Error Recovery Matrix

### `AUTH_REQUIRED` / `INVALID_TOKEN` — HTTP 401

Cause: missing bearer credential, unavailable credential, or invalid token.

Actions:

1. Stop the operation.
2. Do not ask the user to paste a token into chat.
3. Ask the user to confirm that GrowthMap Agent Access is enabled and reconnect/test the client.
4. Never place the token in a URL, log, readback, or MCP argument.

### `GRANT_INACTIVE` — HTTP 401

Cause: revoked or expired grant.

Action: stop all operations and request grant reactivation or extension.

### `LOCALHOST_ONLY` — HTTP 403

Cause: non-localhost Agent Port access.

Action: stop. Do not bypass the localhost restriction.

### `PERMISSION_DENIED` / `MODE_DENIED` — HTTP 403

Cause: active grant disallows the operation.

Actions:

1. If `apply_batch` is denied and review is acceptable, try `propose` once.
2. If `propose` is also denied, treat the grant as Read only.
3. Report the restriction; do not retry repeatedly or seek a bypass.

### `SCOPE_DENIED` / `PROJECT_MISMATCH` — HTTP 403

Cause: project or entity is outside grant scope.

Actions:

1. Re-read the visible graph.
2. Do not use an invisible ID supplied only in conversation.
3. Ask the user to adjust the grant if cross-scope access is required.

### `PROJECT_ID_REQUIRED` — HTTP 422

Cause: workspace operation omitted `project_id`.

Action: select an explicit visible project from `list_projects` and include its ID.

### Validation error — HTTP 422

Cause: schema mismatch, invalid enum, missing CAS, extra field, excessive size, wrong type, or malformed ID.

Actions:

1. Inspect runtime MCP tool schema.
2. Compare against Sections 4 and 5.
3. Correct the payload.
4. Use a new idempotency key because the payload changed.
5. Do not copy error text into new payload fields.

### `REVISION_CONFLICT` — HTTP 409

Execute exactly:

1. Discard the stale write payload.
2. Call `read_project` again.
3. Call `read_graph` and/or `get_context` again.
4. Evaluate whether intervening changes invalidate the plan.
5. Rebuild operations and all expected revisions.
6. Generate a new idempotency key.
7. Submit once more.
8. If it conflicts again, stop and report the contention. Do not race indefinitely.

### `IDEMPOTENCY_MISMATCH` — HTTP 409

Actions:

- If the original request remains correct, resend the exact original payload with the original key.
- If the intended request changed, use a new key.
- Never try to overwrite the old receipt.

### `CYCLIC_BATCH_DEPENDENCY` — HTTP 422

Cause: mutually cyclic same-batch references.

Action: redesign ordering/dependencies or split into two transactions; use a new key.

### `MALFORMED_SCOPE`

Cause: inconsistent canonical containment or branch scope prevents safe projection.

Action: stop mutation and ask the user to inspect graph structure. Do not infer missing entities.

### `CANONICAL_WRITE_CONFLICT`

Cause: a canonical conflict whose details cannot be safely exposed.

Action: re-read once. If the error persists, stop and report it; do not retry rapidly.

### `RATE_LIMITED` — HTTP 429

Cause: exceeding 120 requests per grant per minute.

Action: honor retry timing, reduce reads/events, and never use a tight retry loop.

### HTTP 404

Cause: absent resource or non-disclosure of an out-of-scope resource.

Action: relocate the target from the currently visible graph. Never probe guessed UUIDs.

## 10. Checklists

### 10.1 Pre-write checklist

```yaml
pre_write:
  capabilities_called: false
  explicit_project_selected_from_list_projects: false
  latest_project_revision_read: false
  target_graph_or_context_read: false
  all_ids_from_current_authoritative_reads: false
  all_entity_cas_values_present: false
  operations_within_grant_scope: false
  mutation_mode_decision_justified: false
  operation_count_between_1_and_50: false
  no_invented_delete_shell_repo_db_deployment_operation: false
  idempotency_key_unique_to_payload: false
  no_secret_token_or_sensitive_credential_in_payload: false
```

Set every item to `true` before writing. Otherwise stop or retrieve the missing prerequisite.

### 10.2 Post-write checklist

```yaml
post_write:
  tool_response_is_not_error: false
  proposal_canonical_changed_is_false_if_applicable: false
  proposal_reported_as_pending_if_applicable: false
  project_revision_reread_after_batch: false
  graph_or_context_reread_after_batch: false
  actual_result_verified: false
  request_submission_not_misreported_as_success: false
  meaningful_long_work_events_reported_if_permitted: false
  readback_contains_only_real_evidence: false
  incomplete_untested_or_blocked_items_disclosed: false
```

Set all applicable items to `true` before reporting completion.

## 11. Forbidden Actions

Never:

- invent GrowthMap MCP tools, operation names, parameters, or enum values;
- access GrowthMap SQLite directly;
- open the database from WSL, UNC paths, network drives, or synchronized folders;
- use current GUI selection as Agent project context;
- request that a user paste a bearer token into chat;
- place tokens in query strings, MCP arguments, logs, proposals, events, or readbacks;
- infer file read/write permission from `file_paths` or readback `files`;
- use readback to pretend canon changed;
- report a pending proposal as applied;
- bypass Read-only mode or localhost restrictions;
- omit CAS or guess revisions;
- retry stale payloads indefinitely after HTTP 409;
- reuse an idempotency key for changed content;
- fabricate commits, tests, evidence, or verification;
- create large numbers of nodes to avoid a required human decision;
- interpret Direct collaboration as arbitrary system access.

## 12. Response Templates

### 12.1 Read-only analysis complete

```text
Read GrowthMap project: <NAME> (<PROJECT_ID>)
Target node: <TITLE> (<NODE_ID>)
Observed state: project r<REVISION>, snapshot <DIGEST_PREFIX>

Conclusion: <CONCLUSION>
Risks: <RISKS>
Recommendation: <RECOMMENDATION>

No GrowthMap data was modified.
```

### 12.2 Proposal submitted

```text
Submitted a GrowthMap mutation proposal; canon has not changed.
Proposal ID: <PROPOSAL_ID>
Project revision: r<REVISION>
Operations: <CONCISE_OPERATION_LIST>

The proposal remains pending until human approval.
```

### 12.3 Direct batch verified

```text
Applied and re-read the GrowthMap mutation.
Project: <NAME> (<PROJECT_ID>)
Revision: r<OLD_REVISION> → r<NEW_REVISION>
Verified changes: <VERIFIED_CHANGES>
Verification source: <GRAPH_OR_CONTEXT_DETAILS>
Incomplete / risks: <NONE_OR_DETAILS>
```

### 12.4 Permission blocked

```text
GrowthMap rejected the write with <ERROR_CODE>.
Stopped retrying. Did not bypass authorization. Canon was not modified.
Required human choice: apply manually, enable Review first, or grant Direct collaboration.
```

### 12.5 Revision conflict stopped

```text
GrowthMap returned REVISION_CONFLICT after the allowed re-read/rebuild attempt.
Stopped to avoid racing another writer. No unverified success is claimed.
Latest observed project revision: r<REVISION>
Required next step: review the intervening changes before a new mutation attempt.
```

## 13. Protocol and Runtime Limits

```yaml
agent_port:
  network_scope: localhost_only
  version: "1.0"
request_max_bytes: 1048576
mcp_frame_max_bytes: 1048576
mcp_max_nesting_depth: 12
mcp_protocol_negotiation: "2025-11-25"
batch_operations:
  min: 1
  max: 50
rate_limit_per_grant_per_minute: 120
readback_canonical_payload_max_bytes: 262144
list_projects_max_results: 100
```

## 14. Product Boundaries

GrowthMap Agent Port is a graph API. It does not:

- execute an Agent;
- execute or provide an LLM provider;
- open a repository;
- read or write files;
- execute shell commands;
- deploy software;
- process payments;
- provide provider API keys;
- import, restore, or directly expose its database;
- provide canonical deletion or scenario merge/archive operations through the nine tools in this protocol.

If the external Agent environment independently provides repository, filesystem, shell, deployment, payment, or provider tools, apply that environment's separate authorization and safety policy. A GrowthMap grant never expands external permissions.

## 15. Compact Execution Algorithm

```text
BOOT
capabilities → list_projects → select explicit project_id
→ read_project → read_graph → get_context

DECIDE
analysis only → no write
unknown mode or Review first → propose
Direct collaboration + explicit direct request → apply_batch
Read only → stop before writing

BUILD
use latest project revision
use every required owner/entity revision
use 1–50 strict typed operations
use one idempotency key dedicated to the exact payload

SUBMIT
proposal → require pending + canonical_changed=false
batch → require atomic success

VERIFY
proposal → report pending, canon unchanged
batch → re-read project + affected graph/context, verify every claimed result

RECOVER
transport uncertainty → exact same payload + exact same key
revision conflict → re-read, rebuild, new key, retry once
permission denial → stop or downgrade apply_batch to propose when allowed
validation failure → inspect schema, correct payload, new key
rate limit → honor wait; no tight loop

CLOSE
report_event only for meaningful milestones and only when permitted
submit_readback only for real external evidence
never claim unverified success
```

## Appendix A — Exact MCP Tool Names

```json
[
  "capabilities",
  "list_projects",
  "read_project",
  "read_graph",
  "get_context",
  "propose",
  "apply_batch",
  "report_event",
  "submit_readback"
]
```

If the runtime list differs, stop and reconcile the protocol version. Never substitute a similar tool name.

## Appendix B — Exact Wire Enum Registry

```json
{
  "node_type": [
    "idea",
    "concept",
    "task",
    "question",
    "decision",
    "risk",
    "resource",
    "note",
    "module",
    "spec"
  ],
  "node_status": ["active", "archived", "completed"],
  "maturity": ["seed", "sprout", "growing", "mature"],
  "workflow_status": ["draft", "review", "approved", "archived"],
  "relation_type": [
    "child_of",
    "extends",
    "depends_on",
    "supports",
    "alternative_to",
    "refines",
    "references",
    "conflicts_with"
  ],
  "block_type": [
    "paragraph",
    "bullet_list",
    "rule_set",
    "example",
    "risk_note",
    "decision_log",
    "todo",
    "prompt_context",
    "code",
    "quote",
    "table",
    "text",
    "markdown",
    "note",
    "question",
    "task",
    "decision",
    "risk",
    "resource",
    "definition",
    "rules",
    "spec"
  ],
  "event_type": ["started", "progress", "blocked", "completed", "failed"]
}
```

## Personal v1 live synchronization boundary

Agent Access is a Windows-user, workspace-global master grant, not project-wide mutation authority. Every operation requires an explicit `project_id` and scoped intent. Prefer proposals for judgment-sensitive work; use Direct collaboration only after explicit user authorization. Canonical revisions/CAS are mutation truth: on conflict, re-read and reconcile. SSE journal events only indicate potential stale state and are not mutation truth or a cloud database. The installer is unsigned and updates are manual overwrite installs; project SQLite remains local and activation handles licensing-related data, never desktop project databases.
