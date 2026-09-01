/* Direct named matrix for the fail-closed canonical delta boundary. */
import test from "node:test";
import assert from "node:assert/strict";
import { applyCanonicalDelta } from "./canonical-sync";
import { makeCanonicalFixture } from "./canonical-sync.test-fixture";

test("canonical delta direct matrix: scalar existing and blocks are atomic", () => {
  const { owner, snapshot, delta } = makeCanonicalFixture();
  delta.nodes = [{ ...snapshot.root.children![0], title: "patched" }]; delta.edges = [];
  assert.equal(applyCanonicalDelta(owner, snapshot, delta)?.root.children![0].title, "patched");
  const bad = makeCanonicalFixture(); bad.delta.content_blocks.push({ id: "missing", node_id: "no-such", block_type: "x", content: {}, order_index: 1, revision: 1 } as never);
  const before = JSON.stringify(bad.snapshot); const input = JSON.stringify(bad.delta);
  assert.equal(applyCanonicalDelta(bad.owner, bad.snapshot, bad.delta), null);
  assert.equal(JSON.stringify(bad.snapshot), before); assert.equal(JSON.stringify(bad.delta), input);
});

test("canonical delta direct matrix: missing/foreign parent, reparent, duplicate, self, cycle and root reject", () => {
  for (const kind of ["missing-parent", "foreign-parent", "existing-child-reparent", "duplicate-parent", "self", "cycle", "root"]) {
    const { owner, snapshot, delta } = makeCanonicalFixture();
    if (kind === "missing-parent" || kind === "foreign-parent") delta.edges[0].from_node_id = "missing";
    if (kind === "existing-child-reparent") delta.edges[0].to_node_id = snapshot.root.children![0].id;
    if (kind === "duplicate-parent") delta.edges.push({ ...delta.edges[0], id: "duplicate", to_node_id: "other" });
    if (kind === "self") delta.edges[0].to_node_id = delta.edges[0].from_node_id;
    if (kind === "cycle") { delta.nodes.push({ ...snapshot.root.children![0], id: "cycle-parent" }); delta.edges[0].from_node_id = "cycle-parent"; delta.edges.push({ ...delta.edges[0], id: "cycle-edge", from_node_id: "new-child", to_node_id: "cycle-parent" }); }
    if (kind === "root") delta.nodes[0] = { ...delta.nodes[0], id: snapshot.root.id };
    assert.equal(applyCanonicalDelta(owner, snapshot, delta), null, kind);
  }
});

test("canonical delta direct matrix: branch stale full gap truncated overflow reject", () => {
  for (const field of ["gap", "full_refresh_required", "truncated"] as const) {
    const { owner, snapshot, delta } = makeCanonicalFixture(); delta[field] = true; assert.equal(applyCanonicalDelta(owner, snapshot, delta), null, field);
  }
  const x = makeCanonicalFixture(); x.delta.current_revision = Number.MAX_SAFE_INTEGER + 1; assert.equal(applyCanonicalDelta(x.owner, x.snapshot, x.delta), null);
  const stale = makeCanonicalFixture(); stale.owner.loadedRevision = 2; assert.equal(applyCanonicalDelta(stale.owner, stale.snapshot, stale.delta), null);
  const branch = makeCanonicalFixture(); branch.owner.branchId = "branch"; assert.equal(applyCanonicalDelta(branch.owner, branch.snapshot, branch.delta), null);
});
