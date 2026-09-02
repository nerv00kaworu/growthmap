import test from "node:test";
import assert from "node:assert/strict";
import { createSubtreeWidthCache, decorateSelection, layoutTreeToFlow, syncFlowState } from "./mindmap-layout";
import type { GNode } from "@/lib/types";

const node = (id: string, children: GNode[] = []): GNode => ({
  id, project_id: "p", title: id, summary: "", node_type: "idea", status: "active", maturity: "seed",
  priority: 0, confidence: .5, description: "", rules_text: "", constraints_text: "", examples_text: "",
  questions_text: "", decision_notes: "", workflow_status: "draft", tags: [], file_paths: [], created_by: "",
  last_edited_by: "", position_x: 0, position_y: 0, meta: {}, content_blocks: [], created_at: "", updated_at: "",
  revision: 1, branch_id: null, children,
});
const root = node("root", [node("a", [node("a1"), node("a2")]), node("b", [node("b1")])]);
const options = { highlightedIds: [], heatmapMode: false, focusNodeId: null };

test("subtree widths are post-order cached once per node", () => {
  const got = createSubtreeWidthCache(root);
  assert.equal(got.computations, 6); assert.equal(got.widths.size, 6);
  assert.equal(got.widths.get("a"), 480); assert.equal(got.widths.get("root"), 740);
});
test("selection-only state/effect update preserves structural layout and edges", () => {
  let layoutCalls = 0;
  const structural = layoutTreeToFlow(root, { ...options, report: () => layoutCalls++ });
  const initialPositions = structural.nodes.map((node) => ({ id: node.id, position: node.position }));
  const initialEdges = structural.edges;
  const state: { nodes: typeof structural.nodes; edges: typeof structural.edges } = { nodes: [], edges: [] };
  const setNodes = (nodes: typeof structural.nodes) => { state.nodes = nodes; };
  const setEdges = (edges: typeof structural.edges) => { state.edges = edges; };

  // This mirrors MindMap's useMemo selection decoration followed by its state-sync effect.
  syncFlowState(setNodes, setEdges, decorateSelection(structural.nodes, null), structural.edges);
  syncFlowState(setNodes, setEdges, decorateSelection(structural.nodes, "a1"), structural.edges);

  assert.equal(layoutCalls, 1, "selectedNodeId-only change must not invoke structural layout");
  assert.deepEqual(state.nodes.map((node) => ({ id: node.id, position: node.position })), initialPositions);
  assert.strictEqual(state.edges, initialEdges, "selection-only update must retain the existing edges");
  assert.equal(state.nodes.find((node) => node.id === "a1")?.data.isSelected, true);
  assert.equal(state.nodes.find((node) => node.id === "a")?.data.isSelected, false);
});
test("representative tree positions and edges stay stable", () => {
  const got = layoutTreeToFlow(root, options);
  assert.deepEqual(got.edges.map(e => [e.source, e.target]), [["root", "a"], ["a", "a1"], ["a", "a2"], ["root", "b"], ["b", "b1"]]);
  assert.deepEqual(got.nodes.map(n => [n.id, n.position.x, n.position.y]), [["root", 400, 0], ["a", 270, 150], ["a1", 140, 300], ["a2", 400, 300], ["b", 660, 150], ["b1", 660, 300]]);
});
test("focus preserves the legacy four-edge descendant visibility", () => {
  const deep = node("root", [node("focus", [node("d1", [node("d2", [node("d3", [node("d4", [node("d5")])])])])]), node("sibling")]);
  const got = layoutTreeToFlow(deep, { focusNodeId: "focus" });
  assert.deepEqual(got.nodes.map(n => n.id), ["root", "focus", "d1", "d2", "d3", "d4", "sibling"]);
  assert.deepEqual(got.edges.map(e => [e.source, e.target]), [["root", "focus"], ["focus", "d1"], ["d1", "d2"], ["d2", "d3"], ["d3", "d4"], ["root", "sibling"]]);
});
test("graph filtering and relation edges preserve extracted behavior", () => {
  const got = layoutTreeToFlow(root, { graphMode: true, graphVisibleIds: new Set(["root", "a", "a1"]), extraEdges: [{ id: "keep", from: "root", to: "a1", relation: "depends_on" }, { id: "hidden", from: "a", to: "b1", relation: "supports" }], relationFilter: new Set(["depends_on"]) });
  assert.deepEqual(got.nodes.map(n => n.id), ["root", "a", "a1"]);
  assert.deepEqual(got.edges.map(e => e.id), ["root-a", "a-a1", "rel-keep"]);
  assert.deepEqual(got.nodes.map(n => [n.id, n.position]), [["root", { x: 300, y: 0 }], ["a", { x: 300, y: 180 }], ["a1", { x: 300, y: 360 }]]);
});
