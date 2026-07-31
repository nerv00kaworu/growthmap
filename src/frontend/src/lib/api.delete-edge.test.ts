/* eslint-disable @typescript-eslint/no-explicit-any */
import test from "node:test";
import assert from "node:assert/strict";
import {api,resetRevisionCacheForTests} from "./api";

const project=(revision:number)=>({id:"p",revision,root_node_id:"n"});
const edge=(revision:number)=>({id:"e",project_id:"p",from_node_id:"a",to_node_id:"b",relation_type:"supports",revision});

test("deleteEdge advances unchanged snapshot and permits the next project mutation",async()=>{
 resetRevisionCacheForTests();const calls:{url:string,body:any}[]=[];
 globalThis.fetch=(async(url:any,init:any={})=>{const path=String(url);calls.push({url:path,body:init.body&&JSON.parse(init.body)});if(path.endsWith("/projects"))return new Response(JSON.stringify([project(4)]));if(path.includes("/projects/p/edges"))return new Response(JSON.stringify([edge(2)]));if(init.method==="DELETE")return new Response(null,{status:204});return new Response(JSON.stringify({...project(6),status:"active"}));}) as any;
 await api.listProjects();await api.listEdges("p");await api.deleteEdge("e");await api.updateProject("p",{status:"active"});
 assert.deepEqual(calls[2].body,{expected_project_revision:4,expected_revision:2});assert.equal(calls[3].body.expected_project_revision,5);
 await assert.rejects(api.deleteEdge("e"),/Edge revision unavailable/);
});

test("deleteEdge 409 leaves cache untouched",async()=>{
 resetRevisionCacheForTests();let deletes=0;
 globalThis.fetch=(async(url:any,init:any={})=>{const path=String(url);if(path.endsWith("/projects"))return new Response(JSON.stringify([project(7)]));if(path.includes("/edges" )&&init.method!=="DELETE")return new Response(JSON.stringify([edge(3)]));if(init.method==="DELETE"&&deletes++===0)return new Response(JSON.stringify({detail:{code:"REVISION_CONFLICT",message:"stale"}}),{status:409});return new Response(null,{status:204});}) as any;
 await api.listProjects();await api.listEdges("p");await assert.rejects(api.deleteEdge("e"),/stale/);await api.deleteEdge("e");
});

test("deleteEdge invalidates coupled cache when reads change snapshot in flight",async()=>{
 resetRevisionCacheForTests();let release!:(r:Response)=>void;let projectReads=0,edgeReads=0;
 globalThis.fetch=(async(url:any,init:any={})=>{const path=String(url);if(init.method==="DELETE")return await new Promise<Response>(r=>release=r);if(path.endsWith("/projects"))return new Response(JSON.stringify([project(projectReads++ ? 10 : 9)]));return new Response(JSON.stringify([edge(edgeReads++ ? 5 : 4)]));}) as any;
 await api.listProjects();await api.listEdges("p");const pending=api.deleteEdge("e");await new Promise(r=>setTimeout(r,0));await api.listProjects();await api.listEdges("p");release(new Response(null,{status:204}));await pending;
 await assert.rejects(api.deleteEdge("e"),/Edge revision unavailable/);assert.throws(()=>api.updateProject("p",{status:"active"}),/Revision state unavailable/);
});
