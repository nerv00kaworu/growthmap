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
  api.createNode = (async (_projectId: string, body: Parameters<typeof api.createNode>[1]) => {
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
  api.updateNode = (async () => { mutations += 1; throw new ApiError(409, "REVISION_CONFLICT", "stale"); }) as unknown as typeof api.updateNode;
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

test("undo of a newly created child performs durable inverse before publishing", async () => {
  const originalCreate=api.createNode, originalDelete=api.deleteNode, originalSubtree=api.getSubtree;
  const calls: unknown[][]=[];
  api.createNode=(async()=>({...(root as object),id:"made",title:"made",revision:1,authoritative_project_revision:8,authoritative_parent_id:"root",authoritative_parent_revision:4})) as unknown as typeof api.createNode;
  api.deleteNode=(async(...args: unknown[])=>{calls.push(args)}) as typeof api.deleteNode;
  api.getSubtree=(async()=>root) as typeof api.getSubtree;
  try { reset({undoStack:[]}); await useStore.getState().addChildNode("root","made"); assert.equal(useStore.getState().undoStack.length,1); await useStore.getState().undo(); assert.deepEqual(calls,[["made",8,1]]); assert.equal(useStore.getState().undoStack.length,0); }
  finally {api.createNode=originalCreate;api.deleteNode=originalDelete;api.getSubtree=originalSubtree;}
});

test("failed durable undo keeps entry and reloads coherent durable state", async () => {
  const originalDelete=api.deleteNode, originalSubtree=api.getSubtree; let reads=0;
  api.deleteNode=(async()=>{throw new Error("refused")}) as typeof api.deleteNode; api.getSubtree=(async()=>{reads++;return root}) as typeof api.getSubtree;
  const inverse={rootNode:root,description:"create",projectId:"p",branchId:null,inverse:{kind:"delete-created-node",nodeId:"made",nodeRevision:1,projectRevision:8}} as never;
  try {reset({undoStack:[inverse]});await useStore.getState().undo();assert.equal(useStore.getState().undoStack.length,1);assert.equal(reads,1);assert.match(useStore.getState().error??"",/refused/);}
  finally {api.deleteNode=originalDelete;api.getSubtree=originalSubtree;}
});

test("unsupported committed mutations clear misleading undo entries", async()=>{
 const originalUpdate=api.updateNode; const inverse={rootNode:root,description:"create",projectId:"p",branchId:null,inverse:{kind:"delete-created-node",nodeId:"old",nodeRevision:1,projectRevision:7}} as never;
 api.updateNode=(async()=>({...(root as object),title:"saved"})) as unknown as typeof api.updateNode;
 try{reset({undoStack:[inverse]});await useStore.getState().updateNode("root",{title:"saved"});assert.equal(useStore.getState().undoStack.length,0)}finally{api.updateNode=originalUpdate;}
});
