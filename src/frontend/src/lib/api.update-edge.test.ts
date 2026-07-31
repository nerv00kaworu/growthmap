import test from "node:test";
import assert from "node:assert/strict";
import { api, resetRevisionCacheForTests } from "./api";
const json=(v:unknown,s=200)=>new Response(JSON.stringify(v),{status:s,headers:{"content-type":"application/json"}});
const project=(revision:number)=>({id:"p",revision,root_node_id:"root"});
const edge=(revision:number,extra:Record<string,unknown>={})=>({id:"e",project_id:"p",from_node_id:"a",to_node_id:"b",relation_type:"supports",weight:1,note:"",is_mainline:false,created_at:"2026",revision,...extra});

test("updateEdge owns CAS and advances only a complete authoritative pair",async()=>{
 resetRevisionCacheForTests();const bodies:Record<string,unknown>[]=[];let patches=0;
 globalThis.fetch=async(input,init)=>{const url=String(input);if(url.endsWith("/projects"))return json([project(7)]);if(url.endsWith("/projects/p/edges"))return json([edge(3)]);bodies.push(JSON.parse(String(init?.body)));patches++;return json(edge(3+patches,{authoritative_project_revision:7+patches,authoritative_edge_revision:3+patches}));};
 await api.listProjects();await api.listEdges("p");await api.updateEdge("e",{weight:.5,expected_project_revision:99,expected_revision:99});await api.updateEdge("e",{note:"x"});
 assert.deepEqual(bodies.map(x=>[x.expected_project_revision,x.expected_revision]),[[7,3],[8,4]]);
});

test("updateEdge conflict and malformed success do not pollute coupled cache",async()=>{
 resetRevisionCacheForTests();const bodies:Record<string,unknown>[]=[];let patches=0;
 globalThis.fetch=async(input,init)=>{const url=String(input);if(url.endsWith("/projects"))return json([project(9)]);if(url.endsWith("/projects/p/edges"))return json([edge(2)]);bodies.push(JSON.parse(String(init?.body)));patches++;if(patches===1)return json({detail:{code:"REVISION_CONFLICT",message:"stale"}},409);if(patches===2)return json(edge(3,{authoritative_project_revision:10}));return json(edge(3,{authoritative_project_revision:10,authoritative_edge_revision:4}));};
 await api.listProjects();await api.listEdges("p");await assert.rejects(api.updateEdge("e",{note:"a"}),/stale/);await api.updateEdge("e",{note:"b"});await api.updateEdge("e",{note:"c"});
 assert.deepEqual(bodies.map(x=>[x.expected_project_revision,x.expected_revision]),[[9,2],[9,2],[9,2]]);
});
