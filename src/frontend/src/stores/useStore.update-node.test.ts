import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, api } from "@/lib/api";
import { useStore } from "./useStore";

function makeProject() { return { id: "p", name: "p", root_node_id: "root", revision: 7 }; }
function makeRoot() { return { id: "root", project_id: "p", title: "before", summary: "", revision: 3,
  children: [], content_blocks: [], meta: {} }; }
function reset() {
  const project = makeProject();
  const root = makeRoot();
  useStore.setState({ currentProject: project, projects: [{ ...project }], rootNode: root,
    selectedNodeId: "root", selectedNode: root, conflict: null, error: null, undoStack: [] } as never);
  assert.equal(useStore.getState().currentProject?.revision, 7);
}

test("updateNode consumes authoritative project revision", async () => {
  const original = api.updateNode; reset();
  api.updateNode = (async () => ({ ...makeRoot(), title: "saved", revision: 4,
    authoritative_project_revision: 42 } as never)) as typeof api.updateNode;
  try { await useStore.getState().updateNode("root", { title: "saved" });
    assert.equal(useStore.getState().currentProject?.revision, 42);
    assert.equal(useStore.getState().rootNode?.title, "saved");
  } finally { api.updateNode = original; }
});

test("updateNode has explicit legacy +1 fallback", async () => {
  const original = api.updateNode; reset();
  api.updateNode = (async () => ({ ...makeRoot(), title: "legacy", revision: 4 } as never)) as typeof api.updateNode;
  try { await useStore.getState().updateNode("root", { title: "legacy" });
    assert.equal(useStore.getState().currentProject?.revision, 8);
  } finally { api.updateNode = original; }
});

test("updateNode conflict does not mutate canonical cache", async () => {
  const original = api.updateNode; reset();
  api.updateNode = (async () => { throw new ApiError(409, "REVISION_CONFLICT", "stale"); }) as typeof api.updateNode;
  try { await assert.rejects(useStore.getState().updateNode("root", { title: "never" }), ApiError);
    assert.equal(useStore.getState().currentProject?.revision, 7);
    assert.equal(useStore.getState().rootNode?.title, "before");
  } finally { api.updateNode = original; }
});
