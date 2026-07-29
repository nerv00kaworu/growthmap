import assert from "node:assert/strict";
import test from "node:test";
import crypto from "node:crypto";
import { assignStableModuleIds, normalizeModuleIdentifier } from "./stable-module-ids.mjs";
const root="C:/Work/Growth Map";
const normalized="loader!<PROJECT_ROOT>/src/a.ts";
const base=crypto.createHash("sha256").update(normalized).digest("hex").slice(0,16);
function mods(){return [
 {key:"a",use:"chunk-a",resource:"C:/Work/Growth Map/src/a.ts",identifier(){return "loader!C:/Work/Growth Map/src/a.ts"}},
 {key:"b",use:"chunk-b",resource:"C:/Work/Growth Map/src/a.ts",identifier(){return "loader!C%3A%2FWork%2FGrowth%20Map/src/a.ts"}},
 {key:"reserved",id:base,identifier(){return "already"}},
];}
function run(rows){assignStableModuleIds(rows,root,{identity:(module)=>module.use||""});return Object.fromEntries(rows.map(x=>[x.key,x.id]));}
test("identical normalized metadata uses stable chunk identity and reserves preassigned base",()=>{
 const first=run(mods()),second=run(mods().reverse());
 assert.deepEqual(first,second);assert.equal(first.reserved,base);assert.equal(first.a,`${base}-1`);assert.equal(first.b,`${base}-2`);
});
test("indistinguishable collisions fail closed instead of inheriting iteration order",()=>{
 const rows=[0,1].map(()=>({resource:`${root}/src/a.ts`,identifier(){return `loader!${root}/src/a.ts`}}));
 assert.throws(()=>assignStableModuleIds(rows,root),/indistinguishable collision/);
});
test("Windows slash, drive case, and encoded roots normalize",()=>{
 const values=["C:/Work/Growth Map/src/x.ts","c:\\work\\growth map\\src\\x.ts","C%3A%2FWork%2FGrowth%20Map/src/x.ts"];
 for(const value of values) assert.equal(normalizeModuleIdentifier(value,root),"<PROJECT_ROOT>/src/x.ts");
});
test("project-relative identity remains meaningful",()=>{
 assert.notEqual(normalizeModuleIdentifier(`${root}/src/a.ts`,root),normalizeModuleIdentifier(`${root}/src/b.ts`,root));
});
