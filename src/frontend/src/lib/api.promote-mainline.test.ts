import test from "node:test";
import assert from "node:assert/strict";
import { api, MalformedAuthoritativeResponseError, resetRevisionCacheForTests } from "./api";
const json=(x:unknown,s=200)=>new Response(JSON.stringify(x),{status:s,headers:{"Content-Type":"application/json"}});
const project=(r:number)=>({id:"p",revision:r,root_node_id:"a"});
const nodes=(a=8,b=2,c=2)=>[
 {id:"a",project_id:"p",node_type:"idea",revision:a},
 {id:"b",project_id:"p",node_type:"idea",revision:b},
 {id:"c",project_id:"p",node_type:"idea",revision:c},
];
const edges=(target=3,sibling=5)=>[
 {id:"t",project_id:"p",from_node_id:"a",to_node_id:"b",relation_type:"child_of",weight:1,note:"",is_mainline:false,created_at:"x",revision:target},
 {id:"s",project_id:"p",from_node_id:"a",to_node_id:"c",relation_type:"child_of",weight:1,note:"",is_mainline:true,created_at:"x",revision:sibling},
];
type PromotionResult=ReturnType<typeof result>;
const result=(target=4,sibling=6,extra:Record<string,unknown>={})=>({ok:true,project_id:"p",edge_id:"t",parent_node_id:"a",child_node_id:"b",project_revision:11,target_revision:target,touched_sibling_revisions:{s:sibling} as Record<string,number>,touched_node_revisions:{a:8,b:2,c:2} as Record<string,number>,...extra});
async function seed(fetchNodes=true){await api.listProjects();if(fetchNodes)await api.getSubtree("a");await api.listEdges("p")}
function fixture(reply:(write:number)=>Response, nodeRows=nodes()) {
 let writes=0;
 globalThis.fetch=async(input)=>{const u=String(input);if(u.endsWith("/projects"))return json(project(10));if(u.endsWith("/nodes/a/subtree"))return json({...nodeRows[0],children:nodeRows.slice(1)});if(u.endsWith("/projects/p/edges"))return json(edges());return reply(++writes)};
}
async function expectMalformedAndFullInvalidation() {
 await assert.rejects(api.promoteMainline("t"),MalformedAuthoritativeResponseError);
 await assert.rejects(api.promoteMainline("t"),/Target edge revision unavailable/);
 await assert.rejects(async()=>api.updateNode("a",{}),/Node revision unavailable/);
}
test("promotion owns exact target+sibling+endpoint snapshot and sequential call consumes authoritative revisions",async()=>{resetRevisionCacheForTests();const bodies:unknown[]=[];let writes=0;globalThis.fetch=async(input,init)=>{const u=String(input);if(u.endsWith("/projects"))return json(project(10));if(u.endsWith("/nodes/a/subtree"))return json({...nodes()[0],children:nodes().slice(1)});if(u.endsWith("/projects/p/edges"))return json(edges());bodies.push(JSON.parse(String(init?.body)));writes++;return json(writes===1?result():{...result(5,6),project_revision:12,touched_sibling_revisions:{},touched_node_revisions:{a:8,b:2}})};await seed();await api.promoteMainline("t");await api.promoteMainline("t");assert.deepEqual(bodies,[{expected_project_revision:10,expected_revision:3,expected_sibling_revisions:{s:5}},{expected_project_revision:11,expected_revision:4,expected_sibling_revisions:{}}])});
test("409 leaves promotion snapshot unchanged",async()=>{resetRevisionCacheForTests();let writes=0;fixture(()=>++writes===1?json({detail:{code:"REVISION_CONFLICT",message:"stale"}},409):json(result()));await seed();await assert.rejects(api.promoteMainline("t"),/stale/);await api.promoteMainline("t")});
const nodeMutations:Record<string,(value:PromotionResult)=>void>={
 empty:x=>{x.touched_node_revisions={}},
 missing:x=>{delete x.touched_node_revisions.c},
 extra:x=>{x.touched_node_revisions.evil=1},
 wrongEndpoint:x=>{delete x.touched_node_revisions.c;x.touched_node_revisions.wrong=2},
 wrongPositiveRevision:x=>{x.touched_node_revisions.b=99},
};
for(const [name,mutate] of Object.entries(nodeMutations))test(`node revision map ${name} rejects and invalidates full coupled union`,async()=>{resetRevisionCacheForTests();fixture(()=>{const x=result();mutate(x);return json(x)});await seed();await expectMalformedAndFullInvalidation()});
test("cached endpoint node unavailable rejects before write and invalidates full coupled union",async()=>{resetRevisionCacheForTests();let writes=0;fixture(()=>{writes++;return json(result())},nodes().slice(0,2));await seed();await expectMalformedAndFullInvalidation();assert.equal(writes,0)});
test("inflight endpoint node change rejects and invalidates full coupled union",async()=>{resetRevisionCacheForTests();let release!:(r:Response)=>void;const pending=new Promise<Response>(r=>release=r);let subtreeReads=0;globalThis.fetch=async(input)=>{const u=String(input);if(u.endsWith("/projects"))return json(project(10));if(u.endsWith("/nodes/a/subtree")){subtreeReads++;const changed=nodes(subtreeReads===1?8:9);return json({...changed[0],children:changed.slice(1)})}if(u.endsWith("/projects/p/edges"))return json(edges());return pending};await seed();const promote=api.promoteMainline("t");await new Promise(r=>setTimeout(r,0));await api.getSubtree("a");release(json(result()));await assert.rejects(promote,MalformedAuthoritativeResponseError);await assert.rejects(api.promoteMainline("t"),/Target edge revision unavailable/);await assert.rejects(async()=>api.updateNode("a",{}),/Node revision unavailable/)});
