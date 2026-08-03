# GrowthMap Product Core v1 (Normative)

**Status:** normative for Core Collaboration v1. Where older documents conflict, this document wins.

GrowthMap is a shared project-growth platform. Humans use the GUI to create and edit projects, nodes, relations, branches, and AI-assisted expansion/deepening. Any external AI agent may operate that same graph through a provider/model-neutral Agent Port: read scoped context, propose review bundles, make explicitly authorized direct atomic changes, report progress, and write implementation evidence back. Mature graph context may guide source implementation, but GrowthMap itself does not execute an agent or grant filesystem/repository access.

## Invariants

1. The node graph is canonical. REST/JSON is protocol truth; GUI, CLI, and MCP are clients of the same semantics.
2. The Agent Port never binds to Codex, OpenClaw, Claude, or any provider/model and stores no agent API keys.
3. Human and agent graph changes use compatible revision semantics. Every canonical mutation advances the monotonic project revision; mutable entities touched by v1 advance their own revisions. Expected-revision mismatches fail atomically with deterministic HTTP 409.
4. Agent authority is an explicit finite grant with one permission (`read`, `propose`, `write`) and project-wide, exact-node, or branch-root-descendant scope. Scope is checked server-side for every referenced object.
5. Proposals are review artifacts and cannot change canon until a human approves. Write grants may apply direct batches without review, but immutable receipt/action history attributes the agent.
6. Tokens are one-time disclosure secrets. The database stores a stable random prefix plus scrypt hash/salt only. Tokens are never accepted in query strings, logs, exports, receipt payloads, CLI argv, or MCP messages.
7. The local port is localhost-only and bounded. It grants graph API operations only—not files, repositories, commands, provider execution, deployment, credentials, or payments.

## V1 product surface

- Capability discovery and scoped project/graph/context reads.
- Human grant creation/revocation and review/activity panel alongside Agent Sessions.
- Proposal bundles, human approve/reject, direct atomic batch operations, events, and implementation readbacks.
- Strict idempotency and immutable receipts.
- Thin `growthmap-agent` JSON CLI and MCP stdio adapter over REST.

## Bounded deferrals

V1 shows operation JSON and revision state as the honest review diff. General inverse-operation undo for arbitrary agent batches and a visual field-by-field graph diff are deferred; action receipts remain durable and attributable. Agent Port does not clone repositories or execute implementation code.
