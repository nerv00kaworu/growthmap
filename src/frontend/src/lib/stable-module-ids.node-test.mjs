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
test("Unicode-equivalent ties receive deterministic IDs across shuffled input",()=>{
 function unicodeRows(){return [
  {key:"nfc",resource:`${root}/caf\u00e9.ts`,identifier(){return `${root}/same.ts`}},
  {key:"nfd",resource:`${root}/cafe\u0301.ts`,identifier(){return `${root}/same.ts`}},
 ];}
 assert.deepEqual(run(unicodeRows()),run(unicodeRows().reverse()));
});
test("POSIX roots normalize lowercase percent escapes without leaking build paths",()=>{
 const posix="/tmp/Growth Map%Source";
 const values=[
  "/tmp/Growth Map%Source/src/x.ts",
  "%2Ftmp%2FGrowth%20Map%25Source/src/x.ts",
  "%2ftmp%2fGrowth%20Map%25Source/src/x.ts",
 ];
 for(const value of values){
  const result=normalizeModuleIdentifier(`loader!${value}`,posix);
  assert.equal(result,"loader!<PROJECT_ROOT>/src/x.ts");assert.ok(!result.includes("/tmp")&&!result.includes("%2ftmp"));
 }
});
test("Windows encoded separators, percent signs, drive and separator case normalize",()=>{
 const percentRoot="C:/Work/Growth%Map";
 const values=["c:\\work\\growth%map\\src\\x.ts","C%3A%2FWork%2FGrowth%25Map/src/x.ts","c%3a%2fwork%2fgrowth%25map/src/x.ts"];
 for(const value of values) assert.equal(normalizeModuleIdentifier(value,percentRoot),"<PROJECT_ROOT>/src/x.ts");
});
test("malformed and double-encoded text is never broadly decoded into a root",()=>{
 const malformed="loader!C%3G/Work/Growth%20Map/src/x.ts";
 const doubled="loader!C%253A%252FWork%252FGrowth%2520Map/src/x.ts";
 assert.equal(normalizeModuleIdentifier(malformed,root),malformed);
 assert.equal(normalizeModuleIdentifier(doubled,root),doubled);
 assert.notEqual(normalizeModuleIdentifier(malformed,root),normalized);
 assert.notEqual(normalizeModuleIdentifier(doubled,root),normalized);
});
test("total ordering includes every metadata field and chunk identity",()=>{
 const fields=["type","layer","resource","userRequest","request","rawRequest"];
 for(const field of fields){
  const make=(value)=>({key:value,[field]:value,identifier(){return `${root}/same.ts`}});
  assert.deepEqual(run([make("z"),make("a")]),run([make("a"),make("z")]));
 }
 const chunks=(value)=>({key:value,use:value,identifier(){return `${root}/same.ts`}});
 assert.deepEqual(run([chunks("z"),chunks("a")]),run([chunks("a"),chunks("z")]));
});
