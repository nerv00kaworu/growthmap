import assert from "node:assert/strict";
import test from "node:test";
import crypto from "node:crypto";
import { assignStableModuleIds, normalizeModuleIdentifier, stabilizeChunkGroups, stabilizeChunkTraversal } from "./stable-module-ids.mjs";
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
test("Windows slash, drive case, and mixed component-encoded roots normalize",()=>{
 const values=[
  "C:/Work/Growth Map/src/x.ts",
  "c:\\work\\growth map\\src\\x.ts",
  "C%3A%2FWork%2FGrowth%20Map/src/x.ts",
  "D:%5Ca%5Cgrowthmap%5Cgrowthmap%5Csrc%5Cfrontend/src/x.ts",
  "D%3A%5Ca%5Cgrowthmap%5Cgrowthmap%5Csrc%5Cfrontend/src/x.ts",
 ];
 const roots=[root,root,root,"D:/a/growthmap/growthmap/src/frontend","D:/a/growthmap/growthmap/src/frontend"];
 values.forEach((value,index)=>assert.equal(normalizeModuleIdentifier(value,roots[index]),"<PROJECT_ROOT>/src/x.ts"));
});
test("project-relative identity remains meaningful",()=>{
 assert.notEqual(normalizeModuleIdentifier(`${root}/src/a.ts`,root),normalizeModuleIdentifier(`${root}/src/b.ts`,root));
});
test("production loader identity canonicalizes POSIX and Windows encoded-root forms",()=>{
 const posixRoot="/home/runner/work/repository/src/frontend";
 const windowsRoot="D:/a/repository/src/frontend";
 const loader="next-flight-client-entry-loader.js?modules=";
 const posix=`${posixRoot}/node_modules/next/dist/build/webpack/loaders/${loader}%2Fhome%2Frunner%2Fwork%2Frepository%2Fsrc%2Ffrontend%2Fsrc%2Fapp%2Fpage.tsx!`;
 const windows=`D:\\a\\repository\\src\\frontend\\node_modules\\next\\dist\\build\\webpack\\loaders\\${loader}D%3A%5Ca%5Crepository%5Csrc%5Cfrontend%5Csrc%5Capp%5Cpage.tsx!`;
 const mixedWindows=`D:%5Ca%5Crepository%5Csrc%5Cfrontend/node_modules/next/dist/build/webpack/loaders/${loader}D:%5Ca%5Crepository%5Csrc%5Cfrontend/src/app/page.tsx!`;
 const normalized=normalizeModuleIdentifier(posix,posixRoot);
 assert.equal(normalizeModuleIdentifier(windows,windowsRoot),normalized);
 const mixedNormalized=normalizeModuleIdentifier(mixedWindows,windowsRoot);
 assert.equal(mixedNormalized,normalized.replace("<PROJECT_ROOT>/src%2Fapp%2Fpage.tsx","<PROJECT_ROOT>/src/app/page.tsx"));
 assert.doesNotMatch(mixedNormalized,/D:|%5c|repository/i);
 assert.equal(normalized,`<PROJECT_ROOT>/node_modules/next/dist/build/webpack/loaders/${loader}<PROJECT_ROOT>/src%2Fapp%2Fpage.tsx!`);
 assert.ok(!/[A-Z]:|%5c|runner/i.test(normalized));
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

test("lexical root prefixes do not redact POSIX or Windows paths",()=>{
 const cases=[
  ["/repo/application/src/a.js","/repo/app"],
  ["%2frepo%2fapplication%2fsrc%2fa.js","/repo/app"],
  ["C:/Work/Application/src/a.js","C:/Work/App"],
  ["c%3a%2fwork%2fapplication%2fsrc%2fa.js","C:/Work/App"],
 ];
 for(const [value,projectRoot] of cases) assert.equal(normalizeModuleIdentifier(value,projectRoot),value);
});
test("exact roots, child paths, encoded separators, and loader chains normalize",()=>{
 const posix="/repo/app";
 const cases=[
  [posix,"<PROJECT_ROOT>"],
  [`${posix}/src/a.js`,"<PROJECT_ROOT>/src/a.js"],
  [`${posix}%2Fsrc%2Fa.js`,"<PROJECT_ROOT>/src%2Fa.js"],
  ["%2frepo%2fapp%2fsrc%2fa.js","<PROJECT_ROOT>/src%2fa.js"],
  [`loader-a!loader-b!${posix}/src/a.js`,`loader-a!loader-b!<PROJECT_ROOT>/src/a.js`],
  [`${posix}/one!${posix}/two`,`<PROJECT_ROOT>/one!<PROJECT_ROOT>/two`],
 ];
 for(const [value,expected] of cases) assert.equal(normalizeModuleIdentifier(value,posix),expected);
 const win="C:/Work/App";
 assert.equal(normalizeModuleIdentifier("c%3a%2fwork%2fapp%2Fsrc/a.js",win),"<PROJECT_ROOT>/src/a.js");
 assert.equal(normalizeModuleIdentifier("C:/WORK/APP",win),"<PROJECT_ROOT>");
});
test("loader delimiters bound raw and encoded project-root segments without leaking roots",()=>{
 const posix="/repo/app";
 const posixCases=[
  [`${posix}!${posix}/src/a.js`,"<PROJECT_ROOT>!<PROJECT_ROOT>/src/a.js"],
  [`${posix}!${posix}!${posix}`,"<PROJECT_ROOT>!<PROJECT_ROOT>!<PROJECT_ROOT>"],
  ["%2Frepo%2Fapp!%2frepo%2fapp/src/a.js","<PROJECT_ROOT>!<PROJECT_ROOT>/src/a.js"],
  ["%2Frepo/app!%2frepo/app/src/a.js","<PROJECT_ROOT>!<PROJECT_ROOT>/src/a.js"],
  [`${posix}/loader!${posix}/src/a.js`,"<PROJECT_ROOT>/loader!<PROJECT_ROOT>/src/a.js"],
  ["/repo/application!/repo/app/src/a.js","/repo/application!<PROJECT_ROOT>/src/a.js"],
 ];
 for(const [value,expected] of posixCases) assert.equal(normalizeModuleIdentifier(value,posix),expected);
 const win="C:/Work/App";
 const windowsCases=[
  ["c:\\work\\app!C:/WORK/APP/src/a.js","<PROJECT_ROOT>!<PROJECT_ROOT>/src/a.js"],
  ["C%3a%2fWork%2fApp!c%3A%2Fwork%2Fapp/src/a.js","<PROJECT_ROOT>!<PROJECT_ROOT>/src/a.js"],
  ["C%3A/Work%2fApp!c:/work/app/src/a.js","<PROJECT_ROOT>!<PROJECT_ROOT>/src/a.js"],
 ];
 for(const [value,expected] of windowsCases) assert.equal(normalizeModuleIdentifier(value,win),expected);
 for(const [value,projectRoot] of [...posixCases.slice(0,5).map(([value])=>[value,posix]),...windowsCases.map(([value])=>[value,win])]){
  const result=normalizeModuleIdentifier(value,projectRoot);
  for(const variant of [projectRoot,encodeURI(projectRoot),encodeURIComponent(projectRoot)])
   assert.equal(result.toLowerCase().includes(variant.toLowerCase()),false,`private root survived: ${result}`);
 }
});
test("filesystem root only normalizes absolute path segment starts",()=>{
 const cases=[
  ["/","<PROJECT_ROOT>"],
  ["/anything/src/a.js","<PROJECT_ROOT>/anything/src/a.js"],
  ["%2Fanything%2Fsrc%2Fa.js","<PROJECT_ROOT>/anything%2Fsrc%2Fa.js"],
  ["loader!/anything/src/a.js","loader!<PROJECT_ROOT>/anything/src/a.js"],
  ["relative/path.js","relative/path.js"],
 ];
 for(const [value,expected] of cases) assert.equal(normalizeModuleIdentifier(value,"/"),expected);
 assert.equal((normalizeModuleIdentifier("/anything/src/a.js","/").match(/<PROJECT_ROOT>/g)||[]).length,1);
});
test("literal percent, Unicode, regex metacharacters, and trailing slashes are literal roots",()=>{
 const roots=["/tmp/100%/项目/[a]+(b).","/tmp/café.$^/"];
 for(const projectRoot of roots){
  const trimmed=projectRoot.replace(/\/+$/,"");
  assert.equal(normalizeModuleIdentifier(`${trimmed}/src/x.ts`,projectRoot),"<PROJECT_ROOT>/src/x.ts");
  assert.equal(normalizeModuleIdentifier(`${encodeURIComponent(trimmed)}%2fsrc%2fx.ts`,projectRoot),"<PROJECT_ROOT>/src%2fx.ts");
  assert.equal(normalizeModuleIdentifier(`${trimmed}suffix/src/x.ts`,projectRoot),`${trimmed}suffix/src/x.ts`);
 }
});
test("boundary normalization does not leak roots or create lexical collisions",()=>{
 const projectRoot="/secret/build/repo/app";
 const child=normalizeModuleIdentifier(`${projectRoot}/src/a.ts`,projectRoot);
 const lexical=normalizeModuleIdentifier(`${projectRoot}lication/src/a.ts`,projectRoot);
 assert.equal(child,"<PROJECT_ROOT>/src/a.ts");
 assert.ok(!child.includes(projectRoot)&&!child.includes(encodeURIComponent(projectRoot)));
 assert.equal(lexical,`${projectRoot}lication/src/a.ts`);
 assert.notEqual(child,lexical);
 const rows=[
  {key:"child",resource:`${projectRoot}/src/a.ts`,identifier(){return `${projectRoot}/src/a.ts`}},
  {key:"lexical",resource:`${projectRoot}lication/src/a.ts`,identifier(){return `${projectRoot}lication/src/a.ts`}},
 ];
 const ids=run(rows);
 assert.notEqual(ids.child,ids.lexical);
});
test("malformed and double-encoded text is never broadly decoded into a root",()=>{
 const malformed="loader!C%3G/Work/Growth%20Map/src/x.ts";
 const doubled="loader!C%253A%252FWork%252FGrowth%2520Map/src/x.ts";
 assert.equal(normalizeModuleIdentifier(malformed,root),malformed);
 assert.equal(normalizeModuleIdentifier(doubled,root),doubled);
 assert.notEqual(normalizeModuleIdentifier(malformed,root),normalized);
 assert.notEqual(normalizeModuleIdentifier(doubled,root),normalized);
});
test("chunk groups normalize filesystem-dependent discovery order",()=>{
 const chunks=[
  {name:"vendors-z",id:"vendors-z"},
  {name:"app/page",id:"app/page"},
  {name:"a",id:"a"},
  {name:"a",id:"a-2"},
 ];
 const expected=["a:a","a:a-2","app/page:app/page","vendors-z:vendors-z"];
 const groups=[{chunks:chunks.slice().reverse()},{chunks:[chunks[2],chunks[0],chunks[3],chunks[1]]}];
 stabilizeChunkGroups(groups);
 for(const group of groups) assert.deepEqual(group.chunks.map((chunk)=>`${chunk.name}:${chunk.id}`),expected);
});
test("entrypoint and chunk files normalize filesystem-dependent traversal order",()=>{
 const chunks=[
  {name:"vendors-z",id:"vendors-z",files:new Set(["z.js","a.js"])},
  {name:"app/page",id:"app/page",files:new Set(["page-z.js","page-a.js"])},
 ];
 const entrypoint={chunks:chunks.slice().reverse()};
 stabilizeChunkTraversal({chunkGroups:[],entrypoints:new Map([["app/page",entrypoint]]),chunks:new Set(chunks)});
 assert.deepEqual(entrypoint.chunks.map((chunk)=>chunk.name),["app/page","vendors-z"]);
 assert.deepEqual([...chunks[0].files],["a.js","z.js"]);
 assert.deepEqual([...chunks[1].files],["page-a.js","page-z.js"]);
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
test("extracted client module flight metadata canonicalizes Windows JSON escapes",async()=>{
 const {canonicalizeNextFlightEntryIdentifier}=await import("./stable-module-ids.mjs");
 const posixRoot="/home/runner/work/growthmap/growthmap/src/frontend",windowsRoot="D:/a/growthmap/growthmap/src/frontend";
 const option=(request,ids)=>encodeURIComponent(JSON.stringify({request,ids}));
 const posixModules=[
  [`${posixRoot}/src/app/page.tsx`,["default"]],
  [`${posixRoot}/src/lib/node-history-loader.ts`,["freshNodeHistoryView","loadNodeHistory","NodeHistoryRequestCoordinator","visibleNodeHistoryView"]],
 ];
 const windowsModules=[
  ["D:\\a\\growthmap\\growthmap\\src\\frontend\\src\\app\\page.tsx",["default"]],
  ["D:\\a\\growthmap\\growthmap\\src\\frontend\\src\\lib\\node-history-loader.ts",["freshNodeHistoryView","loadNodeHistory","NodeHistoryRequestCoordinator","visibleNodeHistoryView"]],
 ];
 const request=(loaderRoot,modules,serverFirst=false)=>{
  const encoded=modules.map(([path,ids])=>`modules=${option(path,ids)}`);
  const query=serverFirst?["server=false",...encoded]:[...encoded,"server=false"];
  return `${loaderRoot}/node_modules/next/dist/build/webpack/loaders/next-flight-client-entry-loader.js?${query.join("&")}!`;
 };
 const posix=request(posixRoot,posixModules),windows=request("D:\\a\\growthmap\\growthmap\\src\\frontend",windowsModules,true);
 const normalized=normalizeModuleIdentifier(posix,posixRoot);
 assert.equal(normalizeModuleIdentifier(windows,windowsRoot),normalized);
 assert.doesNotMatch(normalized,/%5c|growthmap|[A-Z]%3A/i);
 const rawWindows=`next-flight-client-entry-loader?${windows.split("?")[1]}`;
 const rawPosix=`next-flight-client-entry-loader?${posix.split("?")[1]}`;
 assert.equal(canonicalizeNextFlightEntryIdentifier(rawWindows,windowsRoot),canonicalizeNextFlightEntryIdentifier(rawPosix,posixRoot));
});
test("flight metadata normalization stays closed-schema and fail-closed",async()=>{
 const {canonicalizeNextFlightEntryIdentifier}=await import("./stable-module-ids.mjs");
 const item=encodeURIComponent(JSON.stringify({request:"C:\\Work\\App\\src\\a.ts",ids:["*"]}));
 const valid=`next-flight-client-entry-loader?modules=${item}&server=true!`;
 assert.notEqual(canonicalizeNextFlightEntryIdentifier(valid,"C:/Work/App"),valid);
 for(const value of [
  `modules=${item}&server=true!`,
  `other-flight-client-entry-loader?modules=${item}&server=true!`,
  `next-flight-client-entry-loader?modules=${item}&server=true&unknown=x!`,
  `next-flight-client-entry-loader?modules=${encodeURIComponent(item)}&server=true!`,
 ]) assert.equal(canonicalizeNextFlightEntryIdentifier(value,"C:/Work/App"),value);
});
