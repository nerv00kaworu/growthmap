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

function deferred<T>() { let resolve!: (value:T)=>void; const promise=new Promise<T>(ok=>{resolve=ok}); return {promise,resolve}; }
test("project branch races are owned by exact current project both directions",async()=>{const ob=api.listBranches,os=api.getSubtree;const deep={id:"deep",name:"Deep",root_node_id:"dr",revision:1} as never,qa={id:"qa",name:"QA",root_node_id:"qr",revision:1} as never,demo={id:"3e92794e-9cf0-4b09-a82c-f254b17abfa7",name:"dEMO TEST"} as never;api.getSubtree=(async(id)=>({id,children:[],content_blocks:[]} as never)) as typeof api.getSubtree;try{let old=deferred<never[]>(),now=deferred<never[]>();api.listBranches=((id:string)=>id==="deep"?old.promise:now.promise) as typeof api.listBranches;const a=useStore.getState().selectProject(deep),b=useStore.getState().selectProject(qa);now.resolve([demo]);await b;old.resolve([]);await a;assert.equal(useStore.getState().branches[0]?.name,"dEMO TEST");old=deferred();now=deferred();api.listBranches=((id:string)=>id==="deep"?now.promise:old.promise) as typeof api.listBranches;const c=useStore.getState().selectProject(qa),d=useStore.getState().selectProject(deep);now.resolve([]);await d;old.resolve([demo]);await c;assert.deepEqual(useStore.getState().branches,[])}finally{api.listBranches=ob;api.getSubtree=os}});
test("selecting dEMO TEST reads scenario subtree",async()=>{const original=api.getBranchSubtree;let read="";api.getBranchSubtree=(async(id)=>{read=id;return {tree:{id:"branch-root",children:[],content_blocks:[]}} as never}) as typeof api.getBranchSubtree;try{const demo={id:"3e92794e-9cf0-4b09-a82c-f254b17abfa7",name:"dEMO TEST"} as never;await useStore.getState().selectBranch(demo);assert.equal(read,"3e92794e-9cf0-4b09-a82c-f254b17abfa7");assert.equal(useStore.getState().rootNode?.id,"branch-root")}finally{api.getBranchSubtree=original}});
test("deferred dEMO subtree cannot overwrite a newly selected project",async()=>{const ob=api.listBranches,os=api.getSubtree,obt=api.getBranchSubtree;const deep={id:"deep-subtree",name:"Deep",root_node_id:"deep-root",revision:1} as never,qa={id:"qa-subtree",name:"QA",root_node_id:"qa-root",revision:1} as never,demoId="3e92794e-9cf0-4b09-a82c-f254b17abfa7",demo={id:demoId,name:"dEMO TEST"} as never,pending=deferred<{branch:never;tree:never}>();api.listBranches=(async()=>[]) as typeof api.listBranches;api.getSubtree=(async(id)=>({id,children:[],content_blocks:[]} as never)) as typeof api.getSubtree;api.getBranchSubtree=((id:string)=>{assert.equal(id,demoId);return pending.promise}) as typeof api.getBranchSubtree;try{await useStore.getState().selectProject(deep);const old=useStore.getState().selectBranch(demo);await useStore.getState().selectProject(qa);assert.equal(useStore.getState().rootNode?.id,"qa-root");pending.resolve({branch:demo,tree:{id:"stale-demo-root",children:[],content_blocks:[]} as never});await old;assert.equal(useStore.getState().currentProject?.id,"qa-subtree");assert.equal(useStore.getState().currentBranch,null);assert.equal(useStore.getState().rootNode?.id,"qa-root");assert.equal(useStore.getState().branchLoading,false)}finally{api.listBranches=ob;api.getSubtree=os;api.getBranchSubtree=obt}});
