import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, api, createApiClient } from "@/lib/api";
import type { GNode, Project } from "@/lib/types";
import { useStore } from "./useStore";

const project = { id: "p", name: "p", description: "", goal: "", root_node_id: "root", status: "active", settings: {}, created_at: "", updated_at: "", revision: 7 } satisfies Project;
const root = { id: "root", project_id: "p", title: "root", summary: "", node_type: "idea", status: "active", maturity: "seed", priority: 0, confidence: 0.5, description: "", rules_text: "", constraints_text: "", examples_text: "", questions_text: "", decision_notes: "", workflow_status: "draft", tags: [], file_paths: [], created_by: "human", last_edited_by: "human", position_x: 0, position_y: 0, created_at: "", updated_at: "", revision: 3, children: [], content_blocks: [], meta: {} } satisfies GNode;

function reset(extra: Record<string, unknown> = {}) {
  useStore.setState({ currentProject: project, projects: [project], rootNode: root, selectedNodeId: null,
    expandTargetNodeId: "root", conflict: null, error: null, ...extra } as never);
}

const productionApiMethods = { ...api };
function useFreshApiClient(): () => void {
  Object.assign(api, createApiClient());
  return () => Object.assign(api, productionApiMethods);
}

test("production api omits destructive revision-cache reset and clients isolate authority", () => {
  assert.equal("resetRevisionCacheForTests" in api, false);
  const first = createApiClient();
  const second = createApiClient();
  first.rememberResponse(project);
  assert.throws(() => second.createNode("p", { title: "x", parent_id: "root" }), /Parent revision unavailable/);
});

test("real acceptAllSuggestions orchestration serializes requests with propagated revisions", async () => {
  const originalCreate = api.createNode;
  const originalSubtree = api.getSubtree;
  const originalProject = api.getProject;
  const originalConfirm = globalThis.confirm;
  const requests: Array<Record<string, unknown>> = [];
  let projectRevision = 7, parentRevision = 3;
  globalThis.confirm = () => true;
  api.createNode = (async (_projectId, body) => {
    requests.push({ ...body, expected_project_revision: projectRevision, expected_parent_revision: parentRevision });
    projectRevision += 1; parentRevision += 1;
    return { id: `n${requests.length}`, project_id: "p", title: body.title, revision: 1, children: [], content_blocks: [],
      branch_id:null,authoritative_project_revision: projectRevision, authoritative_parent_id: "root", authoritative_parent_revision: parentRevision } as never;
  }) as typeof api.createNode;
  api.getSubtree = (async () => root) as typeof api.getSubtree;
  api.getProject = (async () => ({ ...project, revision: projectRevision } as never)) as typeof api.getProject;
  try {
    reset({ expandSuggestions: [
      { title: "one", summary: "", node_type: "idea" },
      { title: "two", summary: "", node_type: "idea" },
    ] });
    await useStore.getState().acceptAllSuggestions();
    assert.deepEqual(requests.map(r => [r.title, r.expected_project_revision, r.expected_parent_revision]),
      [["one", 7, 3], ["two", 8, 4]]);
    assert.equal(useStore.getState().expandSuggestions, null);
  } finally { api.createNode = originalCreate; api.getSubtree = originalSubtree; api.getProject = originalProject; globalThis.confirm = originalConfirm; }
});

test("real deepen summary conflict refreshes project and tree, then the human retry succeeds", async () => {
  const originalUpdate = api.updateNode, originalSubtree = api.getSubtree, originalProject = api.getProject;
  let mutations = 0, refreshes = 0;
  const freshProject: Project = { ...project, revision: 8 };
  const freshRoot: GNode = { ...root, revision: 4 };
  api.updateNode = (async () => {
    mutations += 1;
    if (mutations === 1) throw new ApiError(409, "REVISION_CONFLICT", "stale");
    return { ...freshRoot, summary: "keep summary", revision: 5 } as never;
  }) as typeof api.updateNode;
  api.getProject = (async () => { refreshes += 1; return freshProject; }) as typeof api.getProject;
  api.getSubtree = (async () => mutations > 1 ? ({ ...freshRoot, summary: "keep summary", revision: 5 } as never) : freshRoot) as typeof api.getSubtree;
  try {
    reset({ deepenResult: { target_node_id: "root", enriched_summary: "keep summary", content_blocks: [] } });
    await useStore.getState().acceptDeepenSummary();
    assert.equal(mutations, 1); assert.equal(refreshes, 2);
    assert.equal(useStore.getState().currentProject?.revision, 8);
    assert.equal(useStore.getState().rootNode?.revision, 4);
    assert.equal(useStore.getState().conflict?.suggestionInput, "keep summary");
    useStore.setState({ conflict: null, error: null });
    await useStore.getState().acceptDeepenSummary();
    assert.equal(mutations, 2);
    assert.equal(useStore.getState().rootNode?.summary, "keep summary");
  } finally { api.updateNode = originalUpdate; api.getSubtree = originalSubtree; api.getProject = originalProject; }
});

test("real deepen block conflict refreshes project and node revisions and preserves the block", async () => {
  const originalCreate = api.createBlock, originalSubtree = api.getSubtree, originalProject = api.getProject;
  let mutations = 0, refreshes = 0;
  api.createBlock = (async () => { mutations += 1; throw new ApiError(409, "REVISION_CONFLICT", "stale"); }) as typeof api.createBlock;
  api.getProject = (async () => { refreshes += 1; return { ...project, revision: 8 } as never; }) as typeof api.getProject;
  api.getSubtree = (async () => ({ ...root, revision: 4 } as never)) as typeof api.getSubtree;
  try {
    reset({ deepenResult: { target_node_id: "root", enriched_summary: "summary",
      content_blocks: [{ title: "keep title", body: "keep body", block_type: "paragraph" }] } });
    await useStore.getState().acceptDeepenBlock(0);
    assert.equal(mutations, 1); assert.equal(refreshes, 2);
    assert.equal(useStore.getState().currentProject?.revision, 8);
    assert.equal(useStore.getState().rootNode?.revision, 4);
    assert.match(useStore.getState().conflict?.suggestionInput ?? "", /keep title/);
    assert.equal(useStore.getState().deepenResult?.content_blocks.length, 1);
  } finally { api.createBlock = originalCreate; api.getSubtree = originalSubtree; api.getProject = originalProject; }
});

function deferred<T>() { let resolve!: (value:T)=>void, reject!: (error:Error)=>void; const promise=new Promise<T>((ok,fail)=>{resolve=ok;reject=fail}); return {promise,resolve,reject}; }

async function switchAtoBtoA() {
  const b = { ...project, id: "b", root_node_id: "b-root" } as Project;
  await useStore.getState().selectProject(b);
  await useStore.getState().selectProject(project);
}

test("node mutation success and rejection after A to B to A publish no stale state", async () => {
  const ou = api.updateNode, os = api.getSubtree, ol = api.listBranches;
  const success = deferred<GNode>();
  api.getSubtree = (async (id) => ({ ...root, id, project_id: id === "b-root" ? "b" : "p", title: "fresh" } as GNode)) as typeof api.getSubtree;
  api.listBranches = (async () => []) as typeof api.listBranches;
  try {
    reset({ toast: null });
    api.updateNode = (() => success.promise) as typeof api.updateNode;
    const oldSuccess = useStore.getState().updateNode("root", { title: "stale-success" });
    await switchAtoBtoA();
    success.resolve({ ...root, title: "stale-success" });
    await oldSuccess;
    assert.equal(useStore.getState().rootNode?.title, "fresh");
    assert.equal(useStore.getState().currentProject?.revision, 7);

    const failure = deferred<GNode>();
    api.updateNode = (() => failure.promise) as typeof api.updateNode;
    const oldFailure = useStore.getState().updateNode("root", { title: "stale-failure" });
    await switchAtoBtoA();
    failure.reject(new Error("old failure"));
    await oldFailure;
    assert.equal(useStore.getState().error, null);
  } finally { api.updateNode = ou; api.getSubtree = os; api.listBranches = ol; }
});

test("branch mutation success and rejection after switch publish no branch, toast, or error", async () => {
  const oc = api.createBranch, os = api.getSubtree, ol = api.listBranches;
  api.getSubtree = (async (id) => ({ ...root, id } as GNode)) as typeof api.getSubtree;
  api.listBranches = (async () => []) as typeof api.listBranches;
  try {
    reset({ branches: [], toast: null });
    const success = deferred<never>();
    api.createBranch = (() => success.promise) as typeof api.createBranch;
    const oldSuccess = useStore.getState().createBranch("root", "old");
    await switchAtoBtoA();
    success.resolve({ id: "old-branch", name: "old", revision: 1 } as never);
    await oldSuccess;
    assert.deepEqual(useStore.getState().branches, []);
    assert.equal(useStore.getState().toast, null);

    const failure = deferred<never>();
    api.createBranch = (() => failure.promise) as typeof api.createBranch;
    const oldFailure = useStore.getState().createBranch("root", "old-failure");
    await switchAtoBtoA();
    failure.reject(new Error("old branch failure"));
    await oldFailure;
    assert.equal(useStore.getState().error, null);
  } finally { api.createBranch = oc; api.getSubtree = os; api.listBranches = ol; }
});

test("merge root readback is fenced across A to B to A", async () => {
  const om = api.mergeBranch, os = api.getSubtree, ol = api.listBranches;
  const readback = deferred<GNode>();
  let subtreeCalls = 0;
  api.mergeBranch = (async () => ({ ok: true })) as typeof api.mergeBranch;
  api.listBranches = (async () => []) as typeof api.listBranches;
  api.getSubtree = (async (id) => { subtreeCalls += 1; return subtreeCalls === 1 ? readback.promise : ({ ...root, id, title: "fresh" } as GNode); }) as typeof api.getSubtree;
  try {
    const branch = { id: "branch", name: "branch", revision: 2 } as never;
    reset({ branches: [branch], currentBranch: null, toast: null });
    const old = useStore.getState().mergeBranch("branch", "root");
    await Promise.resolve();
    await switchAtoBtoA();
    readback.resolve({ ...root, title: "stale merge root" });
    await old;
    assert.equal(useStore.getState().rootNode?.title, "fresh");
    assert.equal(useStore.getState().toast, null);
  } finally { api.mergeBranch = om; api.getSubtree = os; api.listBranches = ol; }
});

test("deepen block readback after A to B to A publishes no stale success toast", async () => {
  const oc = api.createBlock, op = api.getProject, os = api.getSubtree, ol = api.listBranches;
  const first = deferred<Project>();
  api.createBlock = (async () => ({ id: "block", node_id: "root", block_type: "paragraph", content: {}, order_index: 0 })) as typeof api.createBlock;
  api.getProject = (() => first.promise) as typeof api.getProject;
  api.getSubtree = (async (id) => ({ ...root, id } as GNode)) as typeof api.getSubtree;
  api.listBranches = (async () => []) as typeof api.listBranches;
  try {
    reset({ deepenResult: { target_node_id: "root", enriched_summary: "", content_blocks: [{ title: "block", body: "body", block_type: "paragraph" }] }, toast: null });
    const old = useStore.getState().acceptDeepenBlock(0);
    await Promise.resolve(); await Promise.resolve();
    await switchAtoBtoA();
    first.resolve(project);
    await old;
    assert.equal(useStore.getState().toast, null);
  } finally { api.createBlock = oc; api.getProject = op; api.getSubtree = os; api.listBranches = ol; }
});

test("deepen summary readback stale silent return and first-get rejection publish no toast", async () => {
  const ou = api.updateNode, op = api.getProject, os = api.getSubtree, ol = api.listBranches;
  api.updateNode = (async () => ({ ...root, summary: "saved" } as GNode)) as typeof api.updateNode;
  api.getSubtree = (async (id) => ({ ...root, id } as GNode)) as typeof api.getSubtree;
  api.listBranches = (async () => []) as typeof api.listBranches;
  try {
    reset({ deepenResult: { target_node_id: "root", enriched_summary: "saved", content_blocks: [] }, toast: null });
    const first = deferred<Project>();
    api.getProject = (() => first.promise) as typeof api.getProject;
    const staleReturn = useStore.getState().acceptDeepenSummary();
    await Promise.resolve(); await Promise.resolve();
    await switchAtoBtoA();
    first.resolve(project);
    await staleReturn;
    assert.equal(useStore.getState().toast, null);

    reset({ deepenResult: { target_node_id: "root", enriched_summary: "saved", content_blocks: [] }, toast: null });
    const rejected = deferred<Project>();
    api.getProject = (() => rejected.promise) as typeof api.getProject;
    const staleReject = useStore.getState().acceptDeepenSummary();
    await Promise.resolve(); await Promise.resolve();
    await switchAtoBtoA();
    rejected.reject(new Error("first get failed"));
    await staleReject;
    assert.equal(useStore.getState().toast, null);
  } finally { api.updateNode = ou; api.getProject = op; api.getSubtree = os; api.listBranches = ol; }
});
test("project branch races are owned by exact current project both directions",async()=>{const ob=api.listBranches,os=api.getSubtree;const deep={id:"deep",name:"Deep",root_node_id:"dr",revision:1,selectionRevision:1} as never,qa={id:"qa",name:"QA",root_node_id:"qr",revision:1,selectionRevision:1} as never,demo={id:"3e92794e-9cf0-4b09-a82c-f254b17abfa7",name:"dEMO TEST"} as never;api.getSubtree=(async(id)=>({id,children:[],content_blocks:[]} as never)) as typeof api.getSubtree;try{let old=deferred<never[]>(),now=deferred<never[]>();api.listBranches=((id:string)=>id==="deep"?old.promise:now.promise) as typeof api.listBranches;const a=useStore.getState().selectProject(deep),b=useStore.getState().selectProject(qa);now.resolve([demo]);await b;old.resolve([]);await a;assert.equal(useStore.getState().branches[0]?.name,"dEMO TEST");old=deferred();now=deferred();api.listBranches=((id:string)=>id==="deep"?now.promise:old.promise) as typeof api.listBranches;const c=useStore.getState().selectProject(qa),d=useStore.getState().selectProject(deep);now.resolve([]);await d;old.resolve([demo]);await c;assert.deepEqual(useStore.getState().branches,[])}finally{api.listBranches=ob;api.getSubtree=os}});
test("selecting dEMO TEST reads scenario subtree",async()=>{const original=api.getBranchSubtree;let read="";api.getBranchSubtree=(async(id)=>{read=id;return {tree:{id:"branch-root",children:[],content_blocks:[]}} as never}) as typeof api.getBranchSubtree;try{const demo={id:"3e92794e-9cf0-4b09-a82c-f254b17abfa7",name:"dEMO TEST"} as never;await useStore.getState().selectBranch(demo);assert.equal(read,"3e92794e-9cf0-4b09-a82c-f254b17abfa7");assert.equal(useStore.getState().rootNode?.id,"branch-root")}finally{api.getBranchSubtree=original}});
test("deferred dEMO subtree cannot overwrite a newly selected project",async()=>{const ob=api.listBranches,os=api.getSubtree,obt=api.getBranchSubtree;const deep={id:"deep-subtree",name:"Deep",root_node_id:"deep-root",revision:1,selectionRevision:1} as never,qa={id:"qa-subtree",name:"QA",root_node_id:"qa-root",revision:1,selectionRevision:1} as never,demoId="3e92794e-9cf0-4b09-a82c-f254b17abfa7",demo={id:demoId,name:"dEMO TEST"} as never,pending=deferred<{branch:never;tree:never}>();api.listBranches=(async()=>[]) as typeof api.listBranches;api.getSubtree=(async(id)=>({id,children:[],content_blocks:[]} as never)) as typeof api.getSubtree;api.getBranchSubtree=((id:string)=>{assert.equal(id,demoId);return pending.promise}) as typeof api.getBranchSubtree;try{await useStore.getState().selectProject(deep);const old=useStore.getState().selectBranch(demo);await useStore.getState().selectProject(qa);assert.equal(useStore.getState().rootNode?.id,"qa-root");pending.resolve({branch:demo,tree:{id:"stale-demo-root",children:[],content_blocks:[]} as never});await old;assert.equal(useStore.getState().currentProject?.id,"qa-subtree");assert.equal(useStore.getState().currentBranch,null);assert.equal(useStore.getState().rootNode?.id,"qa-root");assert.equal(useStore.getState().branchLoading,false)}finally{api.listBranches=ob;api.getSubtree=os;api.getBranchSubtree=obt}});

test("superseded same-owner refresh cannot overwrite newer state after A to B to A", async () => {
  const op = api.getProject, os = api.getSubtree;
  const firstTree = deferred<GNode>();
  let projectCalls = 0, treeCalls = 0;
  api.getProject = (async () => { projectCalls += 1; return { ...project, revision: projectCalls === 1 ? 8 : 12 } as Project; }) as typeof api.getProject;
  api.getSubtree = (async () => { treeCalls += 1; return treeCalls === 1 ? firstTree.promise : ({ ...root, revision: 9, title: "new" } as GNode); }) as typeof api.getSubtree;
  try {
    reset();
    const old = useStore.getState().refreshTree();
    await Promise.resolve();
    useStore.setState({ currentProject: { ...project, id: "b" } as Project });
    useStore.setState({ currentProject: project });
    const newer = useStore.getState().refreshTree();
    await newer;
    firstTree.resolve({ ...root, revision: 4, title: "old" });
    await old;
    assert.equal(useStore.getState().currentProject?.revision, 12);
    assert.equal(useStore.getState().rootNode?.title, "new");
  } finally { api.getProject = op; api.getSubtree = os; }
});

test("successful block create retires draft even when authoritative reload fails", async () => {
  const oc = api.createBlock, op = api.getProject, os = api.getSubtree;
  let creates = 0;
  api.createBlock = (async () => { creates += 1; return { id: "block-1", node_id: "root", block_type: "paragraph", content: { title: "once", body: "body" }, order_index: 0, revision: 1 } as never; }) as typeof api.createBlock;
  api.getProject = (async () => { throw new Error("readback failed"); }) as typeof api.getProject;
  api.getSubtree = (async () => root) as typeof api.getSubtree;
  try {
    reset({ deepenResult: { target_node_id: "root", enriched_summary: "summary", content_blocks: [{ title: "once", body: "body", block_type: "paragraph" }] } });
    await useStore.getState().acceptDeepenBlock(0);
    assert.equal(creates, 1);
    assert.equal(useStore.getState().deepenResult, null);
    assert.equal(useStore.getState().rootNode?.content_blocks.length, 1);
    await useStore.getState().acceptDeepenBlock(0);
    assert.equal(creates, 1);
  } finally { api.createBlock = oc; api.getProject = op; api.getSubtree = os; }
});

test("aggregate deepen keeps one immutable owner across A to B to A and sends no block", async () => {
  const ou=api.updateNode, oc=api.createBlock, os=api.getSubtree, op=api.getProject, ol=api.listBranches;
  const summary=deferred<GNode>(); let summaries=0, blocks=0;
  api.updateNode=(()=>{summaries+=1; return summary.promise}) as typeof api.updateNode;
  api.createBlock=(async()=>{blocks+=1; return {} as never}) as typeof api.createBlock;
  api.getSubtree=(async(id)=>({...root,id,project_id:id==="b-root"?"b":"p",title:"fresh"} as GNode)) as typeof api.getSubtree;
  api.getProject=(async()=>project) as typeof api.getProject; api.listBranches=(async()=>[]) as typeof api.listBranches;
  try {
    reset({deepenResult:{target_node_id:"root",enriched_summary:"A summary",content_blocks:[{title:"A block",body:"body",block_type:"paragraph"}]},toast:null,undoStack:[]});
    const old=useStore.getState().acceptDeepen(); await Promise.resolve();
    await switchAtoBtoA(); summary.resolve({...root,summary:"A summary"}); await old;
    assert.equal(summaries,1); assert.equal(blocks,0); assert.equal(useStore.getState().toast,null);
    assert.equal(useStore.getState().deepenResult,null); assert.deepEqual(useStore.getState().undoStack,[]);
  } finally {api.updateNode=ou;api.createBlock=oc;api.getSubtree=os;api.getProject=op;api.listBranches=ol;}
});

test("branch selection clears pending update delete reparent undo and undo stays inert", async () => {
  const ou=api.updateNode, od=api.deleteNode, obt=api.getBranchSubtree, of=globalThis.fetch;
  const child={...root,id:"child",title:"child",revision:2,children:[]} as GNode;
  const parent={...root,id:"parent",title:"parent",revision:2,children:[]} as GNode;
  const tree={...root,children:[child,parent]} as GNode;
  const branch={id:"other",project_id:"p",source_node_id:"root",name:"other",status:"active",created_at:"",updated_at:"",revision:1,selectionRevision:1} as never;
  api.getBranchSubtree=(async()=>({branch,tree:{...tree,title:"branch tree"}} as never)) as typeof api.getBranchSubtree;
  try {
    for (const kind of ["update","delete","reparent"] as const) {
      reset({rootNode:tree,branches:[branch],undoStack:[],toast:null,currentBranch:null}); const pending=deferred<never>();
      if(kind==="update") api.updateNode=(()=>pending.promise) as typeof api.updateNode;
      if(kind==="delete") api.deleteNode=(()=>pending.promise) as typeof api.deleteNode;
      if(kind==="reparent") globalThis.fetch=(()=>pending.promise) as typeof fetch;
      const operation=kind==="update"?useStore.getState().updateNode("child",{title:"old"}):kind==="delete"?useStore.getState().deleteNode("child"):useStore.getState().reparentNode("child","parent");
      assert.equal(useStore.getState().undoStack.length,0); await useStore.getState().selectBranch(branch); assert.deepEqual(useStore.getState().undoStack,[]);
      if(kind==="reparent") pending.resolve({ok:true,status:200,text:async()=>""} as never); else pending.resolve(kind==="update"?({...child,title:"old"} as never):undefined as never);
      await operation; useStore.getState().undo(); assert.equal(useStore.getState().rootNode?.title,"branch tree"); assert.equal(useStore.getState().toast,null); assert.deepEqual(useStore.getState().undoStack,[]);
    }
  } finally {api.updateNode=ou;api.deleteNode=od;api.getBranchSubtree=obt;globalThis.fetch=of;}
});

test("accept all final refresh rejection reports committed save without duplicate encouragement", async()=>{
  const oc=api.createNode,op=api.getProject,os=api.getSubtree,confirm0=globalThis.confirm; let creates=0;
  globalThis.confirm=()=>true; api.createNode=(async(_p,b)=>{creates+=1;return {...root,id:"made",title:b.title,branch_id:null,authoritative_project_revision:8,authoritative_parent_id:"root",authoritative_parent_revision:4} as never}) as typeof api.createNode;
  api.getProject=(async()=>{throw new Error("readback")}) as typeof api.getProject; api.getSubtree=(async()=>root) as typeof api.getSubtree;
  try {reset({expandSuggestions:[{title:"one",summary:"",node_type:"idea"}],undoStack:[],toast:null}); await useStore.getState().acceptAllSuggestions();
    assert.equal(creates,1);assert.equal(useStore.getState().expandSuggestions,null);assert.deepEqual(useStore.getState().undoStack,[]);assert.equal(useStore.getState().error,null);assert.match(useStore.getState().toast??"",/saved|儲存|保存/);
    await useStore.getState().acceptAllSuggestions();assert.equal(creates,1);
  } finally {api.createNode=oc;api.getProject=op;api.getSubtree=os;globalThis.confirm=confirm0;}
});

test("reparent committed write plus readback failure is success with reload and one POST",async()=>{
 const of=globalThis.fetch,op=api.getProject;let posts=0;const child={...root,id:"child",revision:2,children:[]} as GNode,parent={...root,id:"parent",revision:2,children:[]} as GNode,tree={...root,children:[child,parent]} as GNode;
 globalThis.fetch=(async()=>{posts+=1;return {ok:true,status:200,text:async()=>""} as Response}) as typeof fetch;api.getProject=(async()=>{throw new Error("readback")}) as typeof api.getProject;
 try{reset({rootNode:tree,undoStack:[],toast:null});await useStore.getState().reparentNode("child","parent");assert.equal(posts,1);assert.equal(useStore.getState().error,null);assert.deepEqual(useStore.getState().undoStack,[]);assert.match(useStore.getState().toast??"",/moved|移動|移动/);useStore.getState().undo();assert.equal(posts,1)}finally{globalThis.fetch=of;api.getProject=op;}
});

test("delete promote archive deferred settlements stay owned with one dispatch",async()=>{
 const od=api.deleteNode,om=api.promoteChildMainline,oa=api.archiveBranch,os=api.getSubtree,ol=api.listBranches;api.getSubtree=(async(id)=>({...root,id,project_id:id==="b-root"?"b":"p",title:"fresh",children:[]} as GNode)) as typeof api.getSubtree;api.listBranches=(async()=>[]) as typeof api.listBranches;const child={...root,id:"child",revision:2,meta:{edge_revision:3},children:[]} as GNode,tree={...root,children:[child]} as GNode;
 try{for(const kind of ["delete","promote","archive"] as const)for(const disposition of ["success","reject"] as const){const pending=deferred<never>();let calls=0;const branch={id:"arch",project_id:"p",source_node_id:"root",name:"arch",status:"active",created_at:"",updated_at:"",revision:2,selectionRevision:2} as never;api.deleteNode=(()=>{calls++;return pending.promise}) as typeof api.deleteNode;api.promoteChildMainline=(()=>{calls++;return pending.promise}) as typeof api.promoteChildMainline;api.archiveBranch=(()=>{calls++;return pending.promise}) as typeof api.archiveBranch;reset({rootNode:tree,branches:[branch],currentBranch:null,selectedNodeId:"child",selectedNode:child,loading:false,branchLoading:false,error:null,conflict:null,toast:null,undoStack:[]});const operation=kind==="delete"?useStore.getState().deleteNode("child"):kind==="promote"?useStore.getState().promoteMainlineChild("root","child"):useStore.getState().archiveBranch("arch");await switchAtoBtoA();if(disposition==="success") pending.resolve(undefined as never); else pending.reject(new Error("old"));await operation;const state=useStore.getState();assert.equal(calls,1);assert.equal(state.currentProject?.id,"p");assert.equal(state.rootNode?.title,"fresh");assert.deepEqual(state.branches,[]);assert.equal(state.currentBranch,null);assert.equal(state.selectedNodeId,null);assert.equal(state.selectedNode,null);assert.equal(state.loading,false);assert.equal(state.branchLoading,false);assert.equal(state.error,null);assert.equal(state.conflict,null);assert.equal(state.toast,null);assert.deepEqual(state.undoStack,[])}}finally{api.deleteNode=od;api.promoteChildMainline=om;api.archiveBranch=oa;api.getSubtree=os;api.listBranches=ol;}
});

test("merge readback rejection after switch leaves complete destination state and one POST",async()=>{
 const om=api.mergeBranch,os=api.getSubtree,ol=api.listBranches;const read=deferred<GNode>();let posts=0,calls=0;api.mergeBranch=(async()=>{posts++;return {ok:true}}) as typeof api.mergeBranch;api.listBranches=(async()=>[]) as typeof api.listBranches;api.getSubtree=((id:string)=>{calls++;return calls===1?read.promise:Promise.resolve({...root,id,title:"fresh"} as GNode)}) as typeof api.getSubtree;
 try{const branch={id:"branch",project_id:"p",source_node_id:"root",name:"branch",status:"active",created_at:"",updated_at:"",revision:2,selectionRevision:2} as never;reset({branches:[branch],currentBranch:null,selectedNodeId:"root",selectedNode:root,loading:false,branchLoading:false,error:null,conflict:null,toast:null,undoStack:[]});const old=useStore.getState().mergeBranch("branch","root");await Promise.resolve();await switchAtoBtoA();read.reject(new Error("old readback"));await old;const state=useStore.getState();assert.equal(posts,1);assert.equal(state.rootNode?.title,"fresh");assert.deepEqual(state.branches,[]);assert.equal(state.currentBranch,null);assert.equal(state.selectedNodeId,null);assert.equal(state.selectedNode,null);assert.equal(state.loading,false);assert.equal(state.branchLoading,false);assert.equal(state.error,null);assert.equal(state.conflict,null);assert.equal(state.toast,null);assert.deepEqual(state.undoStack,[])}finally{api.mergeBranch=om;api.getSubtree=os;api.listBranches=ol;}
});

test("AI producers are owner and request generation fenced across switches and overlap",async()=>{
 const oe=api.expand,od=api.deepen,os=api.getSubtree,ol=api.listBranches,obt=api.getBranchSubtree;
 api.getSubtree=(async(id)=>({...root,id,project_id:id==="b-root"?"b":"p"} as GNode)) as typeof api.getSubtree;api.listBranches=(async()=>[]) as typeof api.listBranches;api.getBranchSubtree=(async(id)=>({branch:{id},tree:{...root,title:"branch"}} as never)) as typeof api.getBranchSubtree;
 try{for(const kind of ["expand","deepen"] as const)for(const disposition of ["success","reject"] as const){reset({aiLoading:false,expandSuggestions:null,expandTargetNodeId:null,deepenResult:null,error:null});const old=deferred<never>();if(kind==="expand")api.expand=(()=>old.promise) as typeof api.expand;else api.deepen=(()=>old.promise) as typeof api.deepen;const operation=kind==="expand"?useStore.getState().expandNode("root",{providerId:"mock",providerType:"mock",model:"demo",revision:1,selectionRevision:1}):useStore.getState().deepenNode("root",{providerId:"mock",providerType:"mock",model:"demo",revision:1,selectionRevision:1});await switchAtoBtoA();if(disposition==="success")old.resolve(kind==="expand"?{suggestions:[{title:"old",summary:"",node_type:"idea"}]} as never:{enriched_summary:"old",content_blocks:[]} as never);else old.reject(new Error("old error"));await operation;const state=useStore.getState();assert.equal(state.aiLoading,false);assert.equal(state.expandSuggestions,null);assert.equal(state.expandTargetNodeId,null);assert.equal(state.deepenResult,null);assert.equal(state.error,null)}reset();const first=deferred<never>(),second=deferred<never>();let call=0;api.expand=(()=>++call===1?first.promise:second.promise) as typeof api.expand;const a=useStore.getState().expandNode("root",{providerId:"mock",providerType:"mock",model:"demo",revision:1,selectionRevision:1}),b=useStore.getState().expandNode("root",{providerId:"mock",providerType:"mock",model:"demo",revision:1,selectionRevision:1});first.resolve({suggestions:[{title:"old",summary:"",node_type:"idea"}]} as never);await a;assert.equal(useStore.getState().aiLoading,true);second.resolve({suggestions:[{title:"new",summary:"",node_type:"idea"}]} as never);await b;assert.equal(useStore.getState().expandSuggestions?.[0].title,"new");assert.equal(useStore.getState().aiLoading,false);const branch={id:"x",project_id:"p",source_node_id:"root",name:"x",revision:1,selectionRevision:1} as never;reset({branches:[branch]});const pending=deferred<never>();api.deepen=(()=>pending.promise) as typeof api.deepen;const oldBranch=useStore.getState().deepenNode("root",{providerId:"mock",providerType:"mock",model:"demo",revision:1,selectionRevision:1});await useStore.getState().selectBranch(branch);pending.resolve({enriched_summary:"old",content_blocks:[]} as never);await oldBranch;assert.equal(useStore.getState().deepenResult,null)}finally{api.expand=oe;api.deepen=od;api.getSubtree=os;api.listBranches=ol;api.getBranchSubtree=obt;}
});

test("AI authority revision transition fences delayed expand success and error",async()=>{
 const original=api.expand;
 try{for(const reject of [false,true]){const pending=deferred<never>();api.expand=(()=>pending.promise) as typeof api.expand;reset({aiLoading:false,aiError:null,expandSuggestions:null,deepenResult:null});const operation=useStore.getState().expandNode("root",{providerId:"a",providerType:"mock",model:"demo",revision:1,selectionRevision:1});useStore.getState().invalidateAISelection();if(reject)pending.reject(new Error("old"));else pending.resolve({suggestions:[{title:"old",summary:"",node_type:"idea"}]} as never);await operation;assert.equal(useStore.getState().expandSuggestions,null);assert.equal(useStore.getState().aiError,null);assert.equal(useStore.getState().aiLoading,false)}}finally{api.expand=original;}
});

test("AI authority revision transition fences delayed deepen success and error",async()=>{
 const original=api.deepen;
 try{for(const reject of [false,true]){const pending=deferred<never>();api.deepen=(()=>pending.promise) as typeof api.deepen;reset({aiLoading:false,aiError:null,expandSuggestions:null,deepenResult:null});const operation=useStore.getState().deepenNode("root",{providerId:"a",providerType:"mock",model:"demo",revision:1,selectionRevision:1});useStore.getState().invalidateAISelection();if(reject)pending.reject(new Error("old"));else pending.resolve({enriched_summary:"old",content_blocks:[]} as never);await operation;assert.equal(useStore.getState().deepenResult,null);assert.equal(useStore.getState().aiError,null);assert.equal(useStore.getState().aiLoading,false)}}finally{api.deepen=original;}
});

test("AI authority A-B-A invalidation fences old expand and deepen publication",async()=>{
 const originalExpand=api.expand,originalDeepen=api.deepen;
 try{for(const kind of ["expand","deepen"] as const){const pending=deferred<never>();if(kind==="expand")api.expand=(()=>pending.promise) as typeof api.expand;else api.deepen=(()=>pending.promise) as typeof api.deepen;reset({aiLoading:false,aiError:null,expandSuggestions:null,deepenResult:null});const identity={providerId:"a",providerType:"mock",model:"demo",revision:1,selectionRevision:1} as const;const operation=kind==="expand"?useStore.getState().expandNode("root",identity):useStore.getState().deepenNode("root",identity);useStore.getState().invalidateAISelection();useStore.getState().invalidateAISelection();pending.resolve(kind==="expand"?{suggestions:[{title:"old",summary:"",node_type:"idea"}]} as never:{enriched_summary:"old",content_blocks:[]} as never);await operation;assert.equal(useStore.getState().expandSuggestions,null);assert.equal(useStore.getState().deepenResult,null);assert.equal(useStore.getState().aiLoading,false)}}finally{api.expand=originalExpand;api.deepen=originalDeepen;}
});

test("same AI authority identity still publishes normal expand and deepen results",async()=>{
 const originalExpand=api.expand,originalDeepen=api.deepen;api.expand=(async()=>({suggestions:[{title:"new",summary:"",node_type:"idea"}],context_used:{}})) as typeof api.expand;api.deepen=(async()=>({enriched_summary:"new",content_blocks:[],context_used:{}})) as typeof api.deepen;
 try{reset({aiLoading:false,aiError:null,expandSuggestions:null,deepenResult:null});const identity={providerId:"a",providerType:"mock",model:"demo",revision:1,selectionRevision:2} as const;await useStore.getState().expandNode("root",identity);assert.equal(useStore.getState().expandSuggestions?.[0].title,"new");await useStore.getState().deepenNode("root",identity);assert.equal(useStore.getState().deepenResult?.enriched_summary,"new");assert.equal(useStore.getState().aiLoading,false)}finally{api.expand=originalExpand;api.deepen=originalDeepen;}
});

test("stale AI draft target membership fails closed with zero acceptance writes",async()=>{const oc=api.createNode,ou=api.updateNode,c0=globalThis.confirm;let writes=0;globalThis.confirm=()=>true;api.createNode=(async()=>{writes++;return {} as never}) as typeof api.createNode;api.updateNode=(async()=>{writes++;return {} as never}) as typeof api.updateNode;try{reset({expandTargetNodeId:"missing",expandSuggestions:[{title:"old",summary:"",node_type:"idea"}],deepenResult:{target_node_id:"missing",enriched_summary:"old",content_blocks:[]}});await useStore.getState().acceptSuggestion(0);await useStore.getState().acceptAllSuggestions();await useStore.getState().acceptDeepen();assert.equal(writes,0)}finally{api.createNode=oc;api.updateNode=ou;globalThis.confirm=c0;}});

test("accept all retires each committed suggestion before later failure or conflict",async()=>{const oc=api.createNode,op=api.getProject,os=api.getSubtree,c0=globalThis.confirm;globalThis.confirm=()=>true;api.getProject=(async()=>project) as typeof api.getProject;api.getSubtree=(async()=>root) as typeof api.getSubtree;try{for(const conflict of [false,true]){let calls=0;api.createNode=(async(_p,b)=>{calls++;if(calls===2){if(conflict)throw new ApiError(409,"REVISION_CONFLICT","stale");throw new Error("later failed")}return {...root,id:"made-1",title:b.title,branch_id:null,authoritative_project_revision:8,authoritative_parent_id:"root",authoritative_parent_revision:4} as never}) as typeof api.createNode;reset({expandSuggestions:[{title:"same",summary:"first",node_type:"idea"},{title:"same",summary:"second",node_type:"idea"}],undoStack:[],toast:null});await useStore.getState().acceptAllSuggestions();assert.equal(calls,2);assert.equal(useStore.getState().expandSuggestions?.length,1);assert.equal(useStore.getState().expandSuggestions?.[0].summary,"second");assert.deepEqual(useStore.getState().undoStack,[]);await useStore.getState().acceptAllSuggestions().catch(()=>undefined);assert.equal(calls,3)}}finally{api.createNode=oc;api.getProject=op;api.getSubtree=os;globalThis.confirm=c0;}});

test("duplicate deepen blocks retire exactly one token and preserve one draft after later conflict",async()=>{const oc=api.createBlock,ou=api.updateNode,op=api.getProject,os=api.getSubtree;let creates=0;api.updateNode=(async()=>({...root,summary:"summary"})) as typeof api.updateNode;api.createBlock=(async()=>{creates++;if(creates===2)throw new ApiError(409,"REVISION_CONFLICT","later conflict");return {id:`block-${creates}`,node_id:"root",block_type:"paragraph",content:{title:"same",body:"same"},order_index:creates,revision:1,selectionRevision:1} as never}) as typeof api.createBlock;api.getProject=(async()=>project) as typeof api.getProject;api.getSubtree=(async()=>root) as typeof api.getSubtree;try{const identical={title:"same",body:"same",block_type:"paragraph"};reset({deepenResult:{target_node_id:"root",enriched_summary:"summary",content_blocks:[identical,identical]},undoStack:[],toast:null});await useStore.getState().acceptDeepen();assert.equal(creates,2);assert.deepEqual(useStore.getState().deepenResult?.content_blocks,[identical]);assert.deepEqual(useStore.getState().undoStack,[]);assert.match(useStore.getState().toast??"",/Some AI content blocks|部分 AI/)}finally{api.createBlock=oc;api.updateNode=ou;api.getProject=op;api.getSubtree=os;}});

const response=(value:unknown)=>new Response(JSON.stringify(value),{status:200,headers:{"Content-Type":"application/json"}});

test("real cache losing loadProjects stale-high keeps expected project 7 parent 3",async()=>{const of=globalThis.fetch,restoreApi=useFreshApiClient();api.rememberResponse(project);api.rememberResponse(root);const old=deferred<Response>();let lists=0,posted:Record<string,unknown>={};globalThis.fetch=(async(input,init)=>{const url=String(input);if(url.endsWith("/projects")&&!init?.method)return ++lists===1?old.promise:response([project]);if(url.endsWith("/projects/p/nodes")){posted=JSON.parse(String(init?.body));return response({...root,id:"made",branch_id:null,authoritative_project_revision:8,authoritative_parent_id:"root",authoritative_parent_revision:4})}throw Error(url)}) as typeof fetch;try{reset({projects:[project],error:null});const losing=useStore.getState().loadProjects(),winning=useStore.getState().loadProjects();await winning;old.resolve(response([{...project,revision:99}]));await losing;await api.createNode("p",{title:"x",parent_id:"root"});assert.deepEqual([posted.expected_project_revision,posted.expected_parent_revision],[7,3]);assert.equal(useStore.getState().projects[0].revision,7)}finally{globalThis.fetch=of;restoreApi();}});

test("real cache losing project subtree stale-high cannot alter current owner mutation",async()=>{const of=globalThis.fetch,restoreApi=useFreshApiClient();const a={...project,id:"a",root_node_id:"a-root"},b={...project,id:"b",root_node_id:"b-root",revision:11};const at={...root,id:"a-root",project_id:"a"},bt={...root,id:"b-root",project_id:"b",revision:5};const old=deferred<Response>();let posted:Record<string,unknown>={};globalThis.fetch=(async(input,init)=>{const url=String(input);if(url.endsWith("/nodes/a-root/subtree"))return old.promise;if(url.endsWith("/projects/a/branches")||url.endsWith("/projects/b/branches"))return response([]);if(url.endsWith("/nodes/b-root/subtree"))return response(bt);if(url.endsWith("/projects/b/nodes")){posted=JSON.parse(String(init?.body));return response({...bt,id:"made",branch_id:null,authoritative_project_revision:12,authoritative_parent_id:"b-root",authoritative_parent_revision:6})}throw Error(url)}) as typeof fetch;try{reset({currentProject:a,projects:[a,b],rootNode:at});const losing=useStore.getState().selectProject(a);await Promise.resolve();await useStore.getState().selectProject(b);old.resolve(response({...at,revision:99}));await losing;await api.createNode("b",{title:"x",parent_id:"b-root"});assert.deepEqual([posted.expected_project_revision,posted.expected_parent_revision],[11,5])}finally{globalThis.fetch=of;restoreApi();}});

test("real cache losing branch list stale-high cannot replace winning branch revision",async()=>{const of=globalThis.fetch,restoreApi=useFreshApiClient();api.rememberResponse(project);api.rememberResponse(root);const old=deferred<Response>();const branch={id:"branch",project_id:"p",source_node_id:"root",name:"branch",status:"active",created_at:"",updated_at:"",revision:4};let calls=0,posted:Record<string,unknown>={};globalThis.fetch=(async(input,init)=>{const url=String(input);if(url.endsWith("/projects/p/branches"))return ++calls===1?old.promise:response([branch]);if(url.endsWith("/branches/branch/merge")){posted=JSON.parse(String(init?.body));return response({ok:true})}if(url.endsWith("/nodes/root/subtree"))return response(root);throw Error(url)}) as typeof fetch;try{reset({branches:[],currentBranch:null});const losing=useStore.getState().loadBranches("p"),winning=useStore.getState().loadBranches("p");await winning;old.resolve(response([{...branch,revision:99}]));await losing;await useStore.getState().mergeBranch("branch","root");assert.deepEqual([posted.expected_project_revision,posted.expected_revision,posted.expected_target_revision],[7,4,3])}finally{globalThis.fetch=of;restoreApi();}});

test("real cache losing branch subtree high node revision cannot poison next block",async()=>{const of=globalThis.fetch,restoreApi=useFreshApiClient();api.rememberResponse(project);api.rememberResponse(root);const one={id:"one",project_id:"p",source_node_id:"root",name:"one",revision:4},two={...one,id:"two",revision:2,selectionRevision:2};const old=deferred<Response>();let posted:Record<string,unknown>={};globalThis.fetch=(async(input,init)=>{const url=String(input);if(url.endsWith("/branches/one/subtree"))return old.promise;if(url.endsWith("/branches/two/subtree"))return response({branch:two,tree:{...root,revision:5}});if(url.endsWith("/nodes/root/blocks")){posted=JSON.parse(String(init?.body));return response({id:"block",node_id:"root",block_type:"paragraph",content:{},order_index:0,revision:1,selectionRevision:1})}throw Error(url)}) as typeof fetch;try{reset({branches:[one,two],currentBranch:null});const losing=useStore.getState().selectBranch(one as never);await Promise.resolve();await useStore.getState().selectBranch(two as never);old.resolve(response({branch:{...one,revision:99},tree:{...root,revision:99}}));await losing;await api.createBlock("root",{block_type:"paragraph",content:{body:"x"}});assert.deepEqual([posted.expected_project_revision,posted.expected_node_revision],[7,5])}finally{globalThis.fetch=of;restoreApi();}});


test("durable child undo uses exact authority before refresh and retires", async () => {
 const oc=api.createNode,od=api.deleteNode,op=api.getProject,os=api.getSubtree;const events:string[]=[];let args:unknown[]=[];
 const child={...root,id:"child",title:"child",revision:5,branch_id:null,authoritative_project_revision:8,authoritative_parent_id:"root",authoritative_parent_revision:4} as GNode;let deleted=false;
 api.createNode=(async()=>{events.push("create");return child}) as typeof api.createNode;api.deleteNode=(async(...x)=>{events.push("delete");args=x;deleted=true}) as typeof api.deleteNode;api.getProject=(async()=>{events.push("refresh");return {...project,revision:deleted?9:8}}) as typeof api.getProject;api.getSubtree=(async()=>deleted?root:{...root,children:[child]}) as typeof api.getSubtree;
 try{reset({undoStack:[],currentBranch:null});await useStore.getState().addChildNode("root","child");assert.deepEqual(useStore.getState().undoStack[0].inverse,{kind:"delete-created-node",nodeId:"child",nodeRevision:5,projectRevision:8});await useStore.getState().undo();assert.deepEqual(args,["child",8,5]);assert.ok(events.lastIndexOf("delete")<events.lastIndexOf("refresh"));assert.deepEqual(useStore.getState().undoStack,[]);assert.equal(useStore.getState().rootNode?.children.length,0)}finally{api.createNode=oc;api.deleteNode=od;api.getProject=op;api.getSubtree=os;}
});

test("unsafe child create authority never publishes inverse",async()=>{const oc=api.createNode;try{for(const bad of [{...root,id:"x",revision:2,authoritative_parent_id:"root"},{...root,id:"x",revision:2,branch_id:null,authoritative_project_revision:8,authoritative_parent_id:"wrong"},{...root,id:"x",project_id:"wrong",revision:2,branch_id:null,authoritative_project_revision:8,authoritative_parent_id:"root"}]){reset({undoStack:[],currentBranch:null});api.createNode=(async()=>bad as never) as typeof api.createNode;await useStore.getState().addChildNode("root","x");assert.deepEqual(useStore.getState().undoStack,[])}}finally{api.createNode=oc;}});

test("hostile create authority accessors, inheritance, and proxy traps retain readback with zero inverse",async()=>{
 const oc=api.createNode,op=api.getProject,os=api.getSubtree;
 const keys=["id","project_id","branch_id","authoritative_parent_id","authoritative_project_revision","authoritative_parent_revision","revision"] as const;
 const values:Record<string,unknown>={id:"made",project_id:"p",branch_id:null,authoritative_parent_id:"root",authoritative_project_revision:8,authoritative_parent_revision:4,revision:2};
 const made={...root,id:"made",revision:2} as GNode;
 api.getProject=(async()=>({...project,revision:8})) as typeof api.getProject;
 api.getSubtree=(async()=>({...root,children:[made]})) as typeof api.getSubtree;
 const run=async(response:object)=>{reset({undoStack:[],currentBranch:null,toast:null});api.createNode=(async()=>response as never) as typeof api.createNode;await useStore.getState().addChildNode("root","made");assert.deepEqual(useStore.getState().undoStack,[]);assert.equal(useStore.getState().rootNode?.children[0]?.id,"made")};
 try{
  for(const hostileKey of keys){let reads=0;const response:Record<string,unknown>={};for(const key of keys)Object.defineProperty(response,key,key===hostileKey?{enumerable:true,get(){reads++;return reads===1?values[key]:"victim"}}:{enumerable:true,value:values[key]});await run(response);assert.equal(reads,0)}
  await run(Object.create(Object.fromEntries(keys.map(key=>[key,values[key]]))) as object);
  await run(new Proxy({}, {getOwnPropertyDescriptor(){throw Error("descriptor trap")}}));
  let traps=0;await run(new Proxy({}, {getOwnPropertyDescriptor(_target,key){traps++;const name=String(key);return traps===2?{configurable:true,enumerable:true,get(){return values[name]}}:{configurable:true,enumerable:true,writable:true,value:values[name]}}}));assert.equal(traps,2);
 }finally{api.createNode=oc;api.getProject=op;api.getSubtree=os;}
});

test("plain create authority is extracted once and mints exact proven inverse",async()=>{
 const oc=api.createNode,op=api.getProject,os=api.getSubtree;
 const values:Record<string,unknown>={id:"made",project_id:"p",branch_id:null,authoritative_parent_id:"root",authoritative_project_revision:8,authoritative_parent_revision:4,revision:2};
 const counts:Record<string,number>={};const response=new Proxy({}, {getOwnPropertyDescriptor(_target,key){const name=String(key);counts[name]=(counts[name]??0)+1;return {configurable:true,enumerable:true,writable:true,value:values[name]}}});
 const made={...root,id:"made",revision:2} as GNode;
 api.createNode=(async()=>response as never) as typeof api.createNode;api.getProject=(async()=>({...project,revision:8})) as typeof api.getProject;api.getSubtree=(async()=>({...root,children:[made]})) as typeof api.getSubtree;
 try{reset({undoStack:[],currentBranch:null});await useStore.getState().addChildNode("root","made");assert.deepEqual(counts,{id:1,project_id:1,branch_id:1,authoritative_parent_id:1,authoritative_project_revision:1,authoritative_parent_revision:1,revision:1});assert.deepEqual(useStore.getState().undoStack[0]?.inverse,{kind:"delete-created-node",nodeId:"made",nodeRevision:2,projectRevision:8})}finally{api.createNode=oc;api.getProject=op;api.getSubtree=os;}
});

test("undo failure retains inverse; committed delete with refresh failure retires and removes local child",async()=>{const oc=api.createNode,od=api.deleteNode,op=api.getProject,os=api.getSubtree;const made={...root,id:"made",revision:2,branch_id:null,authoritative_project_revision:8,authoritative_parent_id:"root",authoritative_parent_revision:4} as GNode;try{api.createNode=(async()=>made) as typeof api.createNode;api.getProject=(async()=>({...project,revision:8})) as typeof api.getProject;api.getSubtree=(async()=>({...root,children:[made]})) as typeof api.getSubtree;reset({undoStack:[],currentBranch:null});await useStore.getState().addChildNode("root","made");api.deleteNode=(async()=>{throw Error("delete failed")}) as typeof api.deleteNode;await useStore.getState().undo();assert.equal(useStore.getState().undoStack.length,1);assert.equal(useStore.getState().rootNode?.children[0]?.id,"made");let deletes=0;api.deleteNode=(async()=>{deletes++}) as typeof api.deleteNode;api.getProject=(async()=>{throw Error("readback")}) as typeof api.getProject;await useStore.getState().undo();assert.equal(deletes,1);assert.deepEqual(useStore.getState().undoStack,[]);assert.equal(useStore.getState().rootNode?.children.length,0);await useStore.getState().undo();assert.equal(deletes,1);assert.match(useStore.getState().toast??"",/reload|Reload|重新載入|重新加载/)}finally{api.createNode=oc;api.deleteNode=od;api.getProject=op;api.getSubtree=os;}});

test("concurrent undo reserves one entry and never dispatches the next", async () => {
 const oc=api.createNode,od=api.deleteNode,op=api.getProject,os=api.getSubtree,gate=deferred<void>();let deletes=0;
 const made:GNode[]=[];api.getProject=(async()=>({...project,revision:10})) as typeof api.getProject;api.getSubtree=(async()=>({...root,children:[...made]})) as typeof api.getSubtree;
 try{reset({undoStack:[],currentBranch:null});for(const [id,rev] of [["one",8],["two",9]] as const){api.createNode=(async()=>{const child={...root,id,revision:2,branch_id:null,authoritative_project_revision:rev,authoritative_parent_id:"root",authoritative_parent_revision:4} as GNode;made.push(child);return child}) as typeof api.createNode;await useStore.getState().addChildNode("root",id)}api.deleteNode=(()=>{deletes++;return gate.promise}) as typeof api.deleteNode;const a=useStore.getState().undo(),b=useStore.getState().undo();assert.equal(deletes,1);assert.equal(useStore.getState().undoStack.length,0);gate.resolve();await Promise.all([a,b]);assert.equal(deletes,1)}finally{api.createNode=oc;api.deleteNode=od;api.getProject=op;api.getSubtree=os;}
});

test("failed undo restores in order around concurrent push; superseded and throw do not restore",async()=>{
 const oc=api.createNode,od=api.deleteNode,op=api.getProject,os=api.getSubtree;try{const made:GNode[]=[];api.getProject=(async()=>({...project,revision:9})) as typeof api.getProject;api.getSubtree=(async()=>({...root,children:[...made]})) as typeof api.getSubtree;reset({undoStack:[],currentBranch:null});api.createNode=(async()=>{const child={...root,id:"old",revision:2,branch_id:null,authoritative_project_revision:8,authoritative_parent_id:"root",authoritative_parent_revision:4} as GNode;made.push(child);return child}) as typeof api.createNode;await useStore.getState().addChildNode("root","old");const gate=deferred<void>();api.deleteNode=(()=>gate.promise.then(()=>{throw Error("no")})) as typeof api.deleteNode;api.getProject=(async()=>({...project,revision:8})) as typeof api.getProject;api.getSubtree=(async()=>root) as typeof api.getSubtree;const old=useStore.getState().undo();api.createNode=(async()=>{const child={...root,id:"new",revision:2,branch_id:null,authoritative_project_revision:9,authoritative_parent_id:"root",authoritative_parent_revision:5} as GNode;made.push(child);return child}) as typeof api.createNode;await useStore.getState().addChildNode("root","new");gate.resolve();await old;assert.deepEqual(useStore.getState().undoStack,[]);for(const mode of ["superseded","throw"] as const){reset({undoStack:[],currentBranch:null});api.createNode=(async()=>({...root,id:mode,revision:2,branch_id:null,authoritative_project_revision:8,authoritative_parent_id:"root",authoritative_parent_revision:4})) as typeof api.createNode;await useStore.getState().addChildNode("root",mode);api.deleteNode=(async()=>{throw Error("no")}) as typeof api.deleteNode;const refresh=useStore.getState().refreshTree;useStore.setState({refreshTree:(async()=>{if(mode==="throw")throw Error("read");return "superseded"}) as never});await useStore.getState().undo();assert.deepEqual(useStore.getState().undoStack,[]);useStore.setState({refreshTree:refresh})}}finally{api.createNode=oc;api.deleteNode=od;api.getProject=op;api.getSubtree=os;}
});

test("create authority rejects collisions and hostile numerics; accepts main and exact branch",async()=>{const oc=api.createNode,op=api.getProject,os=api.getSubtree,ob=api.getBranchSubtree;const existing={...root,id:"existing"} as GNode;try{api.getProject=(async()=>({...project,revision:8})) as typeof api.getProject;for(const bad of [undefined,NaN,Infinity,-Infinity,1.5,0,-1,Number.MAX_SAFE_INTEGER+1]){reset({undoStack:[],currentBranch:null});api.createNode=(async()=>({...root,id:"made",revision:bad,branch_id:null,authoritative_project_revision:8,authoritative_parent_id:"root",authoritative_parent_revision:4})) as typeof api.createNode;await useStore.getState().addChildNode("root","x");assert.equal(useStore.getState().undoStack.length,0)}for(const id of ["root","existing"]){reset({rootNode:{...root,children:[existing]},undoStack:[],currentBranch:null});api.createNode=(async()=>({...root,id,revision:2,branch_id:null,authoritative_project_revision:8,authoritative_parent_id:"root",authoritative_parent_revision:4})) as typeof api.createNode;await useStore.getState().addChildNode("root","x");assert.equal(useStore.getState().undoStack.length,0)}for(const branch of [null,{id:"br"}] as const){reset({undoStack:[],currentBranch:branch as never});const child={...root,id:`ok-${branch?.id??"main"}`,branch_id:branch?.id,revision:2,authoritative_project_revision:8,authoritative_parent_id:"root",authoritative_parent_revision:4} as GNode;api.createNode=(async()=>child) as typeof api.createNode;api.getSubtree=(async()=>({...root,children:[child]})) as typeof api.getSubtree;api.getBranchSubtree=(async()=>({branch:branch as never,tree:{...root,children:[child]}})) as typeof api.getBranchSubtree;await useStore.getState().addChildNode("root","ok");assert.equal(useStore.getState().undoStack.length,1)}}finally{api.createNode=oc;api.getProject=op;api.getSubtree=os;api.getBranchSubtree=ob;}});

test("create settlement collision fails closed",async()=>{const oc=api.createNode,pending=deferred<never>();try{reset({undoStack:[],currentBranch:null});api.createNode=(()=>pending.promise) as typeof api.createNode;const create=useStore.getState().addChildNode("root","x");useStore.setState({rootNode:{...root,children:[{...root,id:"claimed"} as GNode]}});pending.resolve({...root,id:"claimed",revision:2,branch_id:null,authoritative_project_revision:8,authoritative_parent_id:"root",authoritative_parent_revision:4} as never);await create;assert.deepEqual(useStore.getState().undoStack,[])}finally{api.createNode=oc;}});

test("promote archive merge clear undo only after commit",async()=>{const om=api.promoteChildMainline,oa=api.archiveBranch,og=api.mergeBranch,os=api.getSubtree,child={...root,id:"child",meta:{edge_revision:1}} as GNode,tree={...root,children:[child]},branch={id:"br",revision:1} as never,dummy={description:"x"} as never;try{for(const kind of ["promote","archive","merge"] as const)for(const reject of [false,true]){reset({rootNode:tree,branches:[branch],currentBranch:null,undoStack:[dummy]});const fn=async()=>{if(reject)throw Error("no")};api.promoteChildMainline=fn as typeof api.promoteChildMainline;api.archiveBranch=fn as typeof api.archiveBranch;api.mergeBranch=(async()=>{await fn();return {ok:true}}) as typeof api.mergeBranch;api.getSubtree=(async()=>tree) as typeof api.getSubtree;await (kind==="promote"?useStore.getState().promoteMainlineChild("root","child"):kind==="archive"?useStore.getState().archiveBranch("br"):useStore.getState().mergeBranch("br","root")).catch(()=>undefined);assert.equal(useStore.getState().undoStack.length,reject?1:0)}}finally{api.promoteChildMainline=om;api.archiveBranch=oa;api.mergeBranch=og;api.getSubtree=os;}});

test("undo delayed success after A-B-A has exact one delete and no stale publication",async()=>{const oc=api.createNode,od=api.deleteNode,op=api.getProject,os=api.getSubtree,ol=api.listBranches,gate=deferred<void>();let deletes=0;api.getProject=(async()=>({...project,revision:8})) as typeof api.getProject;api.getSubtree=(async(id)=>({...root,id,project_id:id==="b-root"?"b":"p",title:"fresh"})) as typeof api.getSubtree;api.listBranches=(async()=>[]) as typeof api.listBranches;try{reset({undoStack:[],currentBranch:null,toast:null});const child={...root,id:"old",revision:2,branch_id:null,authoritative_project_revision:8,authoritative_parent_id:"root",authoritative_parent_revision:4} as GNode;api.createNode=(async()=>child) as typeof api.createNode;api.getSubtree=(async(id)=>id==="root"?({...root,children:[child]}):({...root,id,project_id:id==="b-root"?"b":"p",title:"fresh"})) as typeof api.getSubtree;await useStore.getState().addChildNode("root","old");api.deleteNode=(()=>{deletes++;return gate.promise}) as typeof api.deleteNode;const old=useStore.getState().undo();await switchAtoBtoA();gate.resolve();await old;assert.equal(deletes,1);assert.equal(useStore.getState().rootNode?.title,"root");assert.equal(useStore.getState().toast,null);assert.deepEqual(useStore.getState().undoStack,[])}finally{api.createNode=oc;api.deleteNode=od;api.getProject=op;api.getSubtree=os;api.listBranches=ol;}});
