import test from "node:test";
import assert from "node:assert/strict";
import { api, MalformedAuthoritativeResponseError, resetRevisionCacheForTests } from "./api";
const json=(v:unknown,s=200)=>new Response(JSON.stringify(v),{status:s,headers:{"content-type":"application/json"}});
const project=(revision:number)=>({id:"p",revision,root_node_id:"root"});
const edge=(revision:number,extra:Record<string,unknown>={})=>({id:"e",project_id:"p",from_node_id:"a",to_node_id:"b",relation_type:"supports",weight:1,note:"canonical",is_mainline:false,created_at:"2026",revision,...extra});

test("updateEdge owns CAS and advances only a complete authoritative pair",async()=>{
 resetRevisionCacheForTests();const bodies:Record<string,unknown>[]=[];let patches=0;
 globalThis.fetch=async(input,init)=>{const url=String(input);if(url.endsWith("/projects"))return json([project(7)]);if(url.endsWith("/projects/p/edges"))return json([edge(3)]);bodies.push(JSON.parse(String(init?.body)));patches++;return json(edge(3+patches,{authoritative_project_revision:7+patches,authoritative_edge_revision:3+patches}));};
 await api.listProjects();await api.listEdges("p");await api.updateEdge("e",{weight:.5,expected_project_revision:99,expected_revision:99});await api.updateEdge("e",{note:"x"});
 assert.deepEqual(bodies.map(x=>[x.expected_project_revision,x.expected_revision]),[[7,3],[8,4]]);
});

test("409 preserves snapshot and next valid update uses the same CAS",async()=>{
 resetRevisionCacheForTests();const bodies:Record<string,unknown>[]=[];let patches=0;
 globalThis.fetch=async(input,init)=>{const url=String(input);if(url.endsWith("/projects"))return json([project(9)]);if(url.endsWith("/projects/p/edges"))return json([edge(2)]);bodies.push(JSON.parse(String(init?.body)));patches++;if(patches===1)return json({detail:{code:"REVISION_CONFLICT",message:"stale"}},409);return json(edge(3,{authoritative_project_revision:10,authoritative_edge_revision:3}));};
 await api.listProjects();await api.listEdges("p");await assert.rejects(api.updateEdge("e",{note:"a"}),/stale/);await api.updateEdge("e",{note:"b"});
 assert.deepEqual(bodies.map(x=>[x.expected_project_revision,x.expected_revision]),[[9,2],[9,2]]);
});

for(const [name,response] of Object.entries({
 "missing authoritative pair":edge(3),
 "wrong id":edge(3,{id:"WRONG",authoritative_project_revision:10,authoritative_edge_revision:3}),
 "wrong project":edge(3,{project_id:"evil",authoritative_project_revision:10,authoritative_edge_revision:3}),
 "wrong row revision":edge(999,{authoritative_project_revision:10,authoritative_edge_revision:3}),
})) test(`malformed 200 (${name}) rejects without exposing a replacement row`,async()=>{
 resetRevisionCacheForTests();const bodies:Record<string,unknown>[]=[];let patch=0;
 globalThis.fetch=async(input,init)=>{const url=String(input);if(url.endsWith("/projects"))return json([project(9)]);if(url.endsWith("/projects/p/edges"))return json([edge(2)]);bodies.push(JSON.parse(String(init?.body)));patch++;return patch===1?json(response):json(edge(3,{authoritative_project_revision:10,authoritative_edge_revision:3}));};
 await api.listProjects();const canonical=(await api.listEdges("p"))[0];let rendered=canonical;
 await assert.rejects(api.updateEdge("e",{note:"attacker"}).then(row=>{rendered=row;}),e=>e instanceof MalformedAuthoritativeResponseError&&e.code==="MALFORMED_AUTHORITATIVE_RESPONSE");
 assert.equal(rendered,canonical);await api.updateEdge("e",{note:"valid"});assert.deepEqual(bodies.map(x=>[x.expected_project_revision,x.expected_revision]),[[9,2],[9,2]]);
});

test("malformed response after in-flight cache change invalidates coupled entries",async()=>{
 resetRevisionCacheForTests();let release!:(r:Response)=>void;let writes=0;
 globalThis.fetch=async(input)=>{const url=String(input);if(url.endsWith("/projects"))return json([project(writes?20:9)]);if(url.endsWith("/projects/p/edges"))return json([edge(writes?8:2)]);writes++;return new Promise<Response>(resolve=>{release=resolve;});};
 await api.listProjects();await api.listEdges("p");const pending=api.updateEdge("e",{note:"x"});await new Promise(resolve=>setTimeout(resolve,0));await api.listProjects();await api.listEdges("p");release(json(edge(3)));
 await assert.rejects(pending,MalformedAuthoritativeResponseError);await assert.rejects(api.updateEdge("e",{note:"retry"}),/Edge revision unavailable/);
});
