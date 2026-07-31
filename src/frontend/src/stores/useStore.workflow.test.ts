import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, api } from "@/lib/api";
import { useStore } from "./useStore";

const project = { id: "p", name: "p", root_node_id: "root", revision: 7 } as never;
const root = { id: "root", project_id: "p", title: "root", revision: 3, children: [], content_blocks: [], meta: {} } as never;

function reset(extra: Record<string, unknown> = {}) {
  useStore.setState({ currentProject: project, projects: [project], rootNode: root, selectedNodeId: null,
    expandTargetNodeId: "root", conflict: null, error: null, ...extra } as never);
}

test("real acceptAllSuggestions orchestration serializes requests with propagated revisions", async () => {
  const originalCreate = api.createNode;
  const originalSubtree = api.getSubtree;
  const originalConfirm = globalThis.confirm;
  const requests: Array<Record<string, unknown>> = [];
  let projectRevision = 7, parentRevision = 3;
  globalThis.confirm = () => true;
  api.createNode = (async (_projectId, body) => {
    requests.push({ ...body, expected_project_revision: projectRevision, expected_parent_revision: parentRevision });
    projectRevision += 1; parentRevision += 1;
    return { id: `n${requests.length}`, project_id: "p", title: body.title, revision: 1, children: [], content_blocks: [],
      authoritative_project_revision: projectRevision, authoritative_parent_id: "root", authoritative_parent_revision: parentRevision } as never;
  }) as typeof api.createNode;
  api.getSubtree = (async () => root) as typeof api.getSubtree;
  try {
    reset({ expandSuggestions: [
      { title: "one", summary: "", node_type: "idea" },
      { title: "two", summary: "", node_type: "idea" },
    ] });
    await useStore.getState().acceptAllSuggestions();
    assert.deepEqual(requests.map(r => [r.title, r.expected_project_revision, r.expected_parent_revision]),
      [["one", 7, 3], ["two", 8, 4]]);
    assert.equal(useStore.getState().expandSuggestions, null);
  } finally { api.createNode = originalCreate; api.getSubtree = originalSubtree; globalThis.confirm = originalConfirm; }
});

test("real deepen summary conflict does not replay, refreshes once, and preserves result", async () => {
  const originalUpdate = api.updateNode;
  const originalSubtree = api.getSubtree;
  let mutations = 0, refreshes = 0;
  api.updateNode = (async () => { mutations += 1; throw new ApiError(409, "REVISION_CONFLICT", "stale"); }) as typeof api.updateNode;
  api.getSubtree = (async () => { refreshes += 1; return root; }) as typeof api.getSubtree;
  try {
    reset({ deepenResult: { target_node_id: "root", enriched_summary: "keep summary", content_blocks: [] } });
    await useStore.getState().acceptDeepenSummary();
    assert.equal(mutations, 1); assert.equal(refreshes, 1);
    assert.equal(useStore.getState().conflict?.visible, true);
    assert.equal(useStore.getState().conflict?.suggestionInput, "keep summary");
    assert.equal(useStore.getState().deepenResult?.enriched_summary, "keep summary");
  } finally { api.updateNode = originalUpdate; api.getSubtree = originalSubtree; }
});

test("real deepen block conflict does not replay, refreshes once, and preserves block", async () => {
  const originalCreate = api.createBlock;
  const originalSubtree = api.getSubtree;
  let mutations = 0, refreshes = 0;
  api.createBlock = (async () => { mutations += 1; throw new ApiError(409, "REVISION_CONFLICT", "stale"); }) as typeof api.createBlock;
  api.getSubtree = (async () => { refreshes += 1; return root; }) as typeof api.getSubtree;
  try {
    reset({ deepenResult: { target_node_id: "root", enriched_summary: "summary",
      content_blocks: [{ title: "keep title", body: "keep body", block_type: "paragraph" }] } });
    await useStore.getState().acceptDeepenBlock(0);
    assert.equal(mutations, 1); assert.equal(refreshes, 1);
    assert.equal(useStore.getState().conflict?.visible, true);
    assert.match(useStore.getState().conflict?.suggestionInput ?? "", /keep title/);
    assert.equal(useStore.getState().deepenResult?.content_blocks.length, 1);
  } finally { api.createBlock = originalCreate; api.getSubtree = originalSubtree; }
});

test("promote mainline caller does not consume a malformed authoritative result", async () => {
  const originalList = api.listEdges;
  const originalPromote = api.promoteChildMainline;
  const rootRow = root as unknown as Record<string, unknown>;
  const before = { ...rootRow, children: [
    { ...rootRow, id: "old", title: "old", is_mainline: true },
    { ...rootRow, id: "new", title: "new", is_mainline: false },
  ] } as never;
  api.listEdges = (async () => []) as typeof api.listEdges;
  api.promoteChildMainline = (async () => { throw new (await import("@/lib/api")).MalformedAuthoritativeResponseError("promote_mainline"); }) as typeof api.promoteChildMainline;
  try {
    reset({ rootNode: before });
    await assert.rejects(useStore.getState().promoteMainlineChild("root", "new"), /Malformed authoritative response/);
    assert.equal(useStore.getState().currentProject?.revision, 7);
    assert.equal(useStore.getState().rootNode, before);
    assert.equal(useStore.getState().rootNode?.children?.[0].is_mainline, true);
    assert.equal(useStore.getState().rootNode?.children?.[1].is_mainline, false);
  } finally { api.listEdges = originalList; api.promoteChildMainline = originalPromote; }
});
