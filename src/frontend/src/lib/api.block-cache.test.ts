import assert from "node:assert/strict";
import test from "node:test";
import { createApiClient } from "./api";
import { reorderBlockAuthoritatively, type OwnerToken } from "../components/NodePanel/block-reorder";
const response=(v:unknown)=>({ok:true,status:200,json:async()=>v}) as Response;
const p=(id:string,revision:number,root="n")=>({id,root_node_id:root,revision});const n=(id:string,project_id:string,revision:number)=>({id,project_id,node_type:"concept",revision});const b=(id:string,node_id:string,revision:number)=>({id,node_id,block_type:"note",content:{},order_index:0,revision});
const token:OwnerToken={projectId:"p",nodeId:"n",generation:1};

test("real helper supersession clears initiating A authority but preserves B",async()=>{const api=createApiClient();api.rememberResponse([p("p",1),n("n","p",1),b("a","n",1),p("q",4,"m"),n("m","q",5),b("z","m",6)]);let current=true;const bodies:any[]=[];globalThis.fetch=(async(url,init)=>{const path=String(url);if(init?.method==="PATCH"){bodies.push(JSON.parse(String(init.body)));return response(path.includes("/a")?b("a","n",2):b("z","m",7))}if(path.endsWith("/projects/p"))return response(p("p",2));if(path.endsWith("/nodes/n"))return response(n("n","p",2));return response([b("a","n",2)])}) as typeof fetch;const resultPromise=reorderBlockAuthoritatively([b("a","n",1),b("x","n",1)],0,1,token,{current:()=>current},(id,i)=>api.updateBlock(id,{order_index:i}),async()=>{const[project,node,blocks]=await Promise.all([api.getProject("p",false),api.getNode("n",false),api.getBlocks("n",false)]);current=false;return{project,node,blocks}},x=>api.rememberResponse([x.project,x.node,x.blocks]),x=>api.invalidateBlockOwner(x.nodeId,x.projectId));assert.deepEqual(await resultPromise,{moved:false,superseded:true});const before=bodies.length;assert.throws(()=>api.updateBlock("a",{order_index:0}),/Block revision unavailable/);assert.equal(bodies.length,before);await api.updateBlock("z",{order_index:0});assert.deepEqual(bodies.at(-1),{expected_project_revision:4,expected_node_revision:5,expected_revision:6,order_index:0})});

test("real helper partial owner failure invalidates PATCH-auto-remembered authority",async()=>{const api=createApiClient();api.rememberResponse([p("p",1),n("n","p",1),b("a","n",1)]);let fetches=0;globalThis.fetch=(async(url,init)=>{fetches++;const path=String(url);if(init?.method==="PATCH")return response(b("a","n",2));if(path.endsWith("/projects/p"))return response(p("p",2));if(path.endsWith("/nodes/n"))throw Error("node failed");return response([b("a","n",2)])}) as typeof fetch;await assert.rejects(()=>reorderBlockAuthoritatively([b("a","n",1),b("x","n",1)],0,1,token,{current:()=>true},id=>api.updateBlock(id,{order_index:0}),async()=>{const[project,node,blocks]=await Promise.all([api.getProject("p",false),api.getNode("n",false),api.getBlocks("n",false)]);return{project,node,blocks}},x=>api.rememberResponse([x.project,x.node,x.blocks]),x=>api.invalidateBlockOwner(x.nodeId,x.projectId)),/CONTENT_REORDER_SAVED_REFRESH_FAILED/);const before=fetches;assert.throws(()=>api.updateBlock("a",{order_index:0}),/Block revision unavailable/);assert.equal(fetches,before)});

test("explicit stale A invalidation cannot erase B reusing the same node id",async()=>{const api=createApiClient();api.rememberResponse([p("p",1),n("n","p",1),b("a","n",1)]);api.rememberResponse([p("q",4),n("n","q",5),b("z","n",6)]);const bodies:any[]=[];globalThis.fetch=(async(_url,init)=>{bodies.push(JSON.parse(String(init?.body)));return response(b("z","n",7))}) as typeof fetch;api.invalidateBlockOwner("n","p");assert.throws(()=>api.updateProject("p",{}),/Revision state unavailable/);await api.updateBlock("z",{order_index:0});assert.deepEqual(bodies[0],{expected_project_revision:4,expected_node_revision:5,expected_revision:6,order_index:0})});

test("explicit project invalidation with absent node leaves ambiguous blocks and other owner intact",async()=>{const api=createApiClient();api.rememberResponse([p("p",1),b("a","n",1),p("q",4,"m"),n("m","q",5),b("z","m",6)]);let fetches=0;globalThis.fetch=(async()=>{fetches++;return response(b("z","m",7))}) as typeof fetch;api.invalidateBlockOwner("n","p");assert.throws(()=>api.updateBlock("a",{order_index:0}),/Block owner unavailable/);assert.equal(fetches,0);await api.updateBlock("z",{order_index:0});assert.equal(fetches,1)});

test("misbound explicit project callback fails closed without harming cached node owner",async()=>{const api=createApiClient();api.rememberResponse([p("q",9),n("n","q",8),b("z","n",7),p("p",3,"a")]);const bodies:any[]=[];globalThis.fetch=(async(_url,init)=>{bodies.push(JSON.parse(String(init?.body)));return response(b("z","n",8))}) as typeof fetch;api.invalidateBlockOwner("n","p");assert.throws(()=>api.updateProject("p",{}),/Revision state unavailable/);await api.updateBlock("z",{order_index:0});assert.deepEqual(bodies[0],{expected_project_revision:9,expected_node_revision:8,expected_revision:7,order_index:0})});

test("same node replacement blocks stale A PATCH locally while B uses exact q CAS",async()=>{const api=createApiClient();api.rememberResponse([p("p",1),n("n","p",1),b("a","n",1)]);api.rememberResponse([p("q",4),n("n","q",5),b("z","n",6)]);let fetches=0;const bodies:any[]=[];globalThis.fetch=(async(_url,init)=>{fetches++;bodies.push(JSON.parse(String(init?.body)));return response(b("z","n",7))}) as typeof fetch;assert.throws(()=>api.updateBlock("a",{order_index:0}),/Block owner changed/);assert.equal(fetches,0);await api.updateBlock("z",{order_index:0});assert.deepEqual(bodies[0],{expected_project_revision:4,expected_node_revision:5,expected_revision:6,order_index:0})});

test("delayed A PATCH response cannot relabel its block to replacement B",async()=>{const api=createApiClient();api.rememberResponse([p("p",1),n("n","p",1),b("a","n",1),p("q",4)]);let fetches=0;globalThis.fetch=(async()=>{fetches++;api.rememberResponse([n("n","q",5),b("z","n",6)]);return response(b("a","n",2))}) as typeof fetch;await api.updateBlock("a",{order_index:0});assert.equal(fetches,1);assert.throws(()=>api.updateBlock("a",{order_index:0}),/Block owner changed/);assert.equal(fetches,1)});

test("invalidated in-flight A response cannot acquire replacement B custody",async()=>{const api=createApiClient();api.rememberResponse([p("p",1),n("n","p",1),b("a","n",1)]);let resolveA!:(value:Response)=>void;const delayed=new Promise<Response>(resolve=>{resolveA=resolve});const bodies:any[]=[];let fetches=0;globalThis.fetch=(async(url,init)=>{fetches++;bodies.push(JSON.parse(String(init?.body)));if(String(url).endsWith("/blocks/a")&&fetches===1)return delayed;return response(b("z","n",7))}) as typeof fetch;const pending=api.updateBlock("a",{order_index:0});api.invalidateBlockOwner("n","p");api.rememberResponse([p("q",4),n("n","q",5),b("z","n",6)]);resolveA(response(b("a","n",2)));await pending;assert.throws(()=>api.updateBlock("a",{order_index:0}),/Block revision unavailable/);assert.equal(fetches,1);await api.updateBlock("z",{order_index:0});assert.equal(fetches,2);assert.deepEqual(bodies[1],{expected_project_revision:4,expected_node_revision:5,expected_revision:6,order_index:0})});

for(const returnedRevision of [2,99])test(`same block UUID reuse rejects delayed A revision ${returnedRevision}`,async()=>{const api=createApiClient();api.rememberResponse([p("p",1),n("n","p",1),b("a","n",5)]);let resolveA!:(value:Response)=>void;const delayed=new Promise<Response>(resolve=>{resolveA=resolve});const bodies:any[]=[];let fetches=0;globalThis.fetch=(async(_url,init)=>{fetches++;bodies.push(JSON.parse(String(init?.body)));if(fetches===1)return delayed;return response(b("a","n",11))}) as typeof fetch;const pending=api.updateBlock("a",{order_index:0});api.invalidateBlockOwner("n","p");api.rememberResponse([p("q",4),n("n","q",5),b("a","n",10)]);resolveA(response(b("a","n",returnedRevision)));await pending;await api.updateBlock("a",{order_index:0});assert.equal(fetches,2);assert.deepEqual(bodies[1],{expected_project_revision:4,expected_node_revision:5,expected_revision:10,order_index:0})});

test("absent node explicit invalidation clears tagged A blocks and preserves distinct B",async()=>{const api=createApiClient();api.rememberResponse([p("p",1),n("n","p",1),b("a","n",1),p("q",4,"m"),n("m","q",5),b("z","m",6)]);api.invalidateBlockOwner("n");api.rememberResponse(b("a","n",2));api.invalidateBlockOwner("n","p");let fetches=0;globalThis.fetch=(async()=>{fetches++;return response(b("z","m",7))}) as typeof fetch;assert.throws(()=>api.updateBlock("a",{order_index:0}),/Block revision unavailable|Block owner unavailable/);assert.equal(fetches,0);await api.updateBlock("z",{order_index:0});assert.equal(fetches,1)});

test("unknown-owner block is never mutation authority",()=>{const api=createApiClient();api.rememberResponse(b("orphan","missing",1));let fetches=0;globalThis.fetch=(async()=>{fetches++;return response(b("orphan","missing",2))}) as typeof fetch;assert.throws(()=>api.updateBlock("orphan",{order_index:0}),/Block owner unavailable/);assert.equal(fetches,0)});

const hostileBlockResponses: { name: string; operation: "patch" | "create"; value: unknown; injectedId: string }[] = [
  { name: "PATCH wrong ID", operation: "patch", value: b("z", "n", 99), injectedId: "z" },
  { name: "PATCH wrong node", operation: "patch", value: b("z", "m", 99), injectedId: "z" },
  { name: "create wrong node", operation: "create", value: b("z", "m", 99), injectedId: "z" },
  { name: "non-block response", operation: "patch", value: { id: "z", node_id: "n", revision: 99 }, injectedId: "z" },
  { name: "array mixed envelope", operation: "patch", value: [b("z", "n", 99), { ok: true }], injectedId: "z" },
  { name: "nested mixed envelope", operation: "patch", value: { ok: true, block: b("z", "n", 99) }, injectedId: "z" },
];

for (const hostile of hostileBlockResponses) test(`${hostile.name} cannot mint block mutation authority`, async () => {
  const api = createApiClient();
  api.rememberResponse([p("p", 10), n("n", "p", 11), b("a", "n", 12)]);
  const bodies: unknown[] = [];
  let fetches = 0;
  globalThis.fetch = (async (_url, init) => {
    fetches++;
    bodies.push(JSON.parse(String(init?.body)));
    return response(fetches === 1 ? hostile.value : b("a", "n", 13));
  }) as typeof fetch;
  if (hostile.operation === "create") await api.createBlock("n", { block_type: "note", content: {} });
  else await api.updateBlock("a", { order_index: 1 });
  assert.throws(() => api.updateBlock(hostile.injectedId, { order_index: 0 }), /Block revision unavailable/);
  assert.equal(fetches, 1);
  await api.updateBlock("a", { order_index: 0 });
  assert.equal(fetches, 2);
  assert.deepEqual(bodies[1], { expected_project_revision: 10, expected_node_revision: 11, expected_revision: 12, order_index: 0 });
});

test("matching PATCH and create responses provide their latest revisions", async () => {
  const api = createApiClient();
  api.rememberResponse([p("p", 10), n("n", "p", 11), b("a", "n", 12)]);
  const bodies: any[] = [];
  let fetches = 0;
  globalThis.fetch = (async (_url, init) => {
    fetches++;
    bodies.push(JSON.parse(String(init?.body)));
    if (fetches === 1) return response(b("a", "n", 20));
    if (fetches === 2) return response(b("a", "n", 21));
    if (fetches === 3) return response(b("new", "n", 30));
    return response(b("new", "n", 31));
  }) as typeof fetch;
  await api.updateBlock("a", { order_index: 1 });
  await api.updateBlock("a", { order_index: 0 });
  assert.equal(bodies[1].expected_revision, 20);
  await api.createBlock("n", { block_type: "note", content: {} });
  await api.updateBlock("new", { order_index: 0 });
  assert.equal(bodies[3].expected_revision, 30);
});

for (const returnedRevision of [13, 12, 3]) test(`create duplicate existing same-owner ID revision ${returnedRevision} preserves exact CAS`, async () => {
  const api = createApiClient();
  api.rememberResponse([p("p", 10), n("n", "p", 11), b("a", "n", 12)]);
  const bodies: any[] = [];
  let fetches = 0;
  globalThis.fetch = (async (_url, init) => {
    fetches++;
    bodies.push(JSON.parse(String(init?.body)));
    return response(fetches === 1 ? b("a", "n", returnedRevision) : b("a", "n", 13));
  }) as typeof fetch;
  await api.createBlock("n", { block_type: "note", content: {} });
  await api.updateBlock("a", { order_index: 0 });
  assert.equal(fetches, 2);
  assert.deepEqual(bodies[1], { expected_project_revision: 10, expected_node_revision: 11, expected_revision: 12, order_index: 0 });
});

test("create duplicate cross-owner same UUID cannot replace authority", async () => {
  const api = createApiClient();
  api.rememberResponse([p("p", 10), n("n", "p", 11), p("q", 20, "m"), n("m", "q", 21), b("shared", "m", 22)]);
  const bodies: any[] = [];
  let fetches = 0;
  globalThis.fetch = (async (_url, init) => {
    fetches++;
    bodies.push(JSON.parse(String(init?.body)));
    return response(fetches === 1 ? b("shared", "n", 99) : b("shared", "m", 23));
  }) as typeof fetch;
  await api.createBlock("n", { block_type: "note", content: {} });
  await api.updateBlock("shared", { order_index: 0 });
  assert.equal(fetches, 2);
  assert.deepEqual(bodies[1], { expected_project_revision: 20, expected_node_revision: 21, expected_revision: 22, order_index: 0 });
});

for (const order of [[0, 1], [1, 0]] as const) test(`colliding creates grant custody only to first settlement ${order.join("-")}`, async () => {
  const api = createApiClient();
  api.rememberResponse([p("p", 10), n("n", "p", 11)]);
  const revisions = [30, 90];
  const resolvers: ((value: Response) => void)[] = [];
  const bodies: any[] = [];
  let fetches = 0;
  globalThis.fetch = (async (_url, init) => {
    fetches++;
    bodies.push(JSON.parse(String(init?.body)));
    if (fetches <= 2) return new Promise<Response>(resolve => resolvers.push(resolve));
    return response(b("same", "n", 100));
  }) as typeof fetch;
  const creates = [api.createBlock("n", { block_type: "note", content: {} }), api.createBlock("n", { block_type: "note", content: {} })];
  resolvers[order[0]](response(b("same", "n", revisions[order[0]])));
  await creates[order[0]];
  resolvers[order[1]](response(b("same", "n", revisions[order[1]])));
  await creates[order[1]];
  await api.updateBlock("same", { order_index: 0 });
  assert.equal(fetches, 3);
  assert.equal(bodies[2].expected_revision, revisions[order[0]]);
});

test("intervening legitimate readback owns a create response ID", async () => {
  const api = createApiClient();
  api.rememberResponse([p("p", 10), n("n", "p", 11)]);
  let resolveCreate!: (value: Response) => void;
  let fetches = 0;
  const bodies: any[] = [];
  globalThis.fetch = (async (_url, init) => {
    fetches++;
    bodies.push(JSON.parse(String(init?.body)));
    if (fetches === 1) return new Promise<Response>(resolve => { resolveCreate = resolve; });
    return response(b("readback", "n", 41));
  }) as typeof fetch;
  const pending = api.createBlock("n", { block_type: "note", content: {} });
  api.rememberResponse(b("readback", "n", 40));
  resolveCreate(response(b("readback", "n", 99)));
  await pending;
  await api.updateBlock("readback", { order_index: 0 });
  assert.equal(fetches, 2);
  assert.equal(bodies[1].expected_revision, 40);
});

test("unique concurrent creates each retain returned revision", async () => {
  const api = createApiClient();
  api.rememberResponse([p("p", 10), n("n", "p", 11)]);
  const resolvers: ((value: Response) => void)[] = [];
  const bodies: any[] = [];
  let fetches = 0;
  globalThis.fetch = (async (_url, init) => {
    fetches++;
    bodies.push(JSON.parse(String(init?.body)));
    if (fetches <= 2) return new Promise<Response>(resolve => resolvers.push(resolve));
    return response(b(fetches === 3 ? "left" : "right", "n", fetches === 3 ? 31 : 41));
  }) as typeof fetch;
  const left = api.createBlock("n", { block_type: "note", content: {} });
  const right = api.createBlock("n", { block_type: "note", content: {} });
  resolvers[1](response(b("right", "n", 40)));
  resolvers[0](response(b("left", "n", 30)));
  await Promise.all([left, right]);
  await api.updateBlock("left", { order_index: 0 });
  await api.updateBlock("right", { order_index: 0 });
  assert.equal(fetches, 4);
  assert.equal(bodies[2].expected_revision, 30);
  assert.equal(bodies[3].expected_revision, 40);
});
