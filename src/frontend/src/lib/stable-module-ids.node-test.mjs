import assert from "node:assert/strict";
import test from "node:test";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
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
test("total ordering includes every metadata field and chunk identity",()=>{
 const fields=["type","layer","resource","userRequest","request","rawRequest"];
 for(const field of fields){
  const make=(value)=>({key:value,[field]:value,identifier(){return `${root}/same.ts`}});
  assert.deepEqual(run([make("z"),make("a")]),run([make("a"),make("z")]));
 }
 const chunks=(value)=>({key:value,use:value,identifier(){return `${root}/same.ts`}});
 assert.deepEqual(run([chunks("z"),chunks("a")]),run([chunks("a"),chunks("z")]));
});

test("virtual entry IDs normalize POSIX and percent-encoded Windows requests",()=>{
 const posixRoot="/home/runner/work/growthmap/src/frontend";
 const windowsRoot="D:/a/growthmap/src/frontend";
 const posixIdentifier=`javascript/auto|${posixRoot}/node_modules/next/dist/entry-loader.js?modules=%7B%22request%22%3A%22%2Fhome%2Frunner%2Fwork%2Fgrowthmap%2Fsrc%2Ffrontend%2Fsrc%2Fapp%2Fpage.tsx%22%7D!|app-pages-browser`;
 const windowsIdentifier="javascript/auto|D:\\a\\growthmap\\src\\frontend\\node_modules\\next\\dist\\entry-loader.js?modules=%7B%22request%22%3A%22D%3A%5Ca%5Cgrowthmap%5Csrc%5Cfrontend%5Csrc%5Capp%5Cpage.tsx%22%7D!|app-pages-browser";
 const make=(key,identifier)=>({key,identifier(){return identifier;}});
 const posix=make("entry",posixIdentifier),windows=make("entry",windowsIdentifier);
 assignStableModuleIds([posix],posixRoot);
 assignStableModuleIds([windows],windowsRoot);
 assert.equal(posix.id,windows.id);
 const identity=normalizeModuleIdentifier(posixIdentifier,posixRoot);
 assert.equal(identity,normalizeModuleIdentifier(windowsIdentifier,windowsRoot));
 assert.ok(!identity.includes("runner")&&!identity.includes("D:")&&!/%5c/i.test(identity));
 assert.equal(posix.id,crypto.createHash("sha256").update(identity).digest("hex").slice(0,16));
});

test("actual Next entry fixture reports every identity field without private values", async()=>{
 const { moduleIdentityReport }=await import("./stable-module-ids.mjs");
 const project="D:/a/growthmap/src/frontend";
 const identifier="javascript/auto|D:\\a\\growthmap\\src\\frontend\\node_modules\\next\\dist\\entry-loader.js?modules=%7B%22request%22%3A%22D%3A%5Ca%5Cgrowthmap%5Csrc%5Cfrontend%5Csrc%5Capp%5Cpage.tsx%22%7D!|app-pages-browser";
 class NormalModule { identifier(){return identifier} readableIdentifier(){return identifier} }
 const fixtureModule=new NormalModule();Object.assign(fixtureModule,{resource:`${project}/src/app/page.tsx`,userRequest:identifier,rawRequest:identifier,request:identifier,context:project,layer:"app-pages-browser",type:"javascript/auto"});
 const report=moduleIdentityReport(fixtureModule,project,"app/page");
 for(const field of ["identifier","readableIdentifier","resource","userRequest","rawRequest","request","context","layer","type","constructor","chunkIdentity"]){
  assert.match(report[field].rawSha256,/^[a-f0-9]{64}$/);assert.match(report[field].normalizedSha256,/^[a-f0-9]{64}$/);assert.equal(typeof report[field].rootRedactionCount,"number");
 }
 assert.deepEqual(report.identifier.structure.loaderBasenames,["entry-loader.js"]);
 assert.deepEqual(report.identifier.structure.queryKeys,["modules"]);
 assert.equal(JSON.stringify(report).includes(project),false);
});
test("identity report fails closed when normalization retains an unrecognized private path", async()=>{
 const { moduleIdentityReport }=await import("./stable-module-ids.mjs");
 let error;try{moduleIdentityReport({identifier(){return "/home/other/private.ts"}},"/safe/root")}catch(caught){error=caught}
 assert.ok(error instanceof Error);assert.match(error.message,/refused/);assert.match(error.message,/"field":"identifier"/);assert.match(error.message,/"denialReason":"raw-root"/);
 assert.match(error.message,/rawSha256/);assert.match(error.message,/normalizedSha256/);assert.match(error.message,/rootRedactionCount/);assert.match(error.message,/structure/);
 assert.doesNotMatch(error.message,/private\.ts|other/);
});
test("readable identifier uses the root-aware shortening callback", async()=>{
 const { moduleIdentityReport }=await import("./stable-module-ids.mjs");
 const project="C:/private/source";
 const report=moduleIdentityReport({identifier(){return "relative.js"},readableIdentifier({shorten}){return shorten(`${project}/src/a.js`) }},project);
 assert.equal(report.readableIdentifier.rootRedactionCount,1);
});
test("successful write diagnostic retains the normal schema 1 contract",()=>{
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),"identity-success-")),destination=path.join(directory,"report.json");
 const identifier="next-flight-client-entry-loader.js?modules=x!relative-entry.js";
 assignStableModuleIds([{identifier(){return identifier}}],"/safe/root",{identity:()=>"app/page",diagnosticPath:destination});
 const report=JSON.parse(fs.readFileSync(destination,"utf8"));
 assert.equal(report.schema,1);assert.equal(report.status,undefined);assert.equal(report.modules.length,1);
 assert.match(report.modules[0].identifier.rawSha256,/^[a-f0-9]{64}$/);
});
test("diagnostic refusal writes only bounded schema 2 metadata for every denial reason",()=>{
 const cases=[
  ["drive","D:/vault/file.ts"],
  ["raw-root","/home/person/file.ts"],
  ["encoded-root","%2FUsers%2Fperson%2Ffile.ts"],
  ["project-marker","private-project-marker.ts".replace("private-project-marker","growthmap")],
 ];
 for(const [reason,value] of cases){
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),"identity-refusal-"));
  const destination=path.join(directory,"report.json");
  const identifier="next-flight-client-entry-loader.js?modules=x!relative-entry.js";
  const fixture={resource:value,identifier(){return identifier}};
  assert.throws(()=>assignStableModuleIds([fixture],"/safe/root",{identity:()=>"app/page",diagnosticPath:destination}),new RegExp(`denialReason.*${reason}`));
  const payload=fs.readFileSync(destination,"utf8"),report=JSON.parse(payload);
  assert.equal(report.schema,2);assert.equal(report.status,"refused");assert.deepEqual(report.denials,[{moduleIndex:0,field:"resource",denialReason:reason}]);
  assert.match(report.fields[0].resource.rawSha256,/^[a-f0-9]{64}$/);assert.equal(typeof report.fields[0].resource.rawLength,"number");
  assert.equal(typeof report.fields[0].resource.structure.separators.encodedSlash,"number");
  assert.doesNotMatch(payload,/\/home|Users|runner|D:|growthmap/i);
  assert.doesNotMatch(payload,/vault|person|file\.ts/);
 }
});
test("structural token strings are allowlisted and bounded in refusal reports",()=>{
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),"identity-tokens-")),destination=path.join(directory,"report.json");
 const identifier="next-flight-client-entry-loader.js?modules=x!relative-entry.js";
 const fixture={resource:"D:/secret/file.ts?privateKey=x",request:"custom-secret-loader.js?privateKey=x",identifier(){return identifier}};
 assert.throws(()=>assignStableModuleIds([fixture],"/safe/root",{identity:()=>"app/page",diagnosticPath:destination}));
 const payload=fs.readFileSync(destination,"utf8"),report=JSON.parse(payload);
 assert.deepEqual(report.fields[0].request.structure.loaderBasenames,["other"]);
 assert.deepEqual(report.fields[0].request.structure.queryKeys,["other"]);
 assert.doesNotMatch(payload,/secret|privateKey|custom/i);
});

test("Next flight entry schema canonicalizes Windows and POSIX requests identically", async()=>{
 const { canonicalizeNextFlightEntryIdentifier }=await import("./stable-module-ids.mjs");
 const posixRoot="/home/runner/work/growthmap/src/frontend",winRoot="D:/a/growthmap/src/frontend";
 const make=(root,request,order=false)=>{
  const moduleOption=encodeURIComponent(JSON.stringify({request,ids:["default","*"]}));
  const query=order?`server=false&modules=${moduleOption}`:`modules=${moduleOption}&server=false`;
  return `javascript/auto|${root}/node_modules/next/dist/build/webpack/loaders/next-flight-client-entry-loader.js?${query}!|app-pages-browser`;
 };
 const posix=make(posixRoot,`${posixRoot}/src/app/page.tsx`);
 const windows=make("D:\\a\\growthmap\\src\\frontend","D:\\a\\growthmap\\src\\frontend\\src\\app\\page.tsx",true);
 const canonical=normalizeModuleIdentifier(posix,posixRoot);
 assert.equal(canonical,normalizeModuleIdentifier(windows,winRoot));
 assert.match(canonical,/modules=%7B%22request%22%3A%22%3CPROJECT_ROOT%3E%2Fsrc%2Fapp%2Fpage\.tsx%22%2C%22ids%22%3A%5B%22default%22%2C%22\*%22%5D%7D&server=false!/);
 assert.equal(canonicalizeNextFlightEntryIdentifier("unrelated-loader.js?modules=x&server=false!",posixRoot),"unrelated-loader.js?modules=x&server=false!");
 const rows=[{key:"posix",identifier(){return posix}},{key:"windows",identifier(){return windows}}];
 assignStableModuleIds([rows[0]],posixRoot);assignStableModuleIds([rows[1]],winRoot);
 assert.equal(rows[0].id,rows[1].id);
 assert.equal(rows[0].id,crypto.createHash("sha256").update(canonical).digest("hex").slice(0,16));
});

test("Next flight canonicalization is ordered, closed-schema, and fail-closed", async()=>{
 const { canonicalizeNextFlightEntryIdentifier, moduleIdentityReport }=await import("./stable-module-ids.mjs");
 const project="C:/Work/App",item=JSON.stringify({ids:["*"],request:"C:\\Work\\App\\src\\a.ts"});
 const encoded=encodeURIComponent(item),loader="next-flight-client-entry-loader.js";
 const expected=`${loader}?modules=${encodeURIComponent(JSON.stringify({request:"<PROJECT_ROOT>/src/a.ts",ids:["*"]}))}&server=true!`;
 const report=moduleIdentityReport({identifier(){return expected}},project);
 assert.deepEqual(report.identifier.structure.queryKeys,["modules","server"]);
 for(const query of [`modules=${encoded}&server=true`,`server=true&modules=${encoded}`])
  assert.equal(canonicalizeNextFlightEntryIdentifier(`${loader}?${query}!`,project),expected);
 const unchanged=[
  `${loader}?modules=${encoded}&server=true&unknown=x!`,
  `${loader}?modules=${encodeURIComponent(encoded)}&server=true!`,
  `${loader}?modules=%7B%22request%22%3A%ZZ&server=true!`,
  `${loader}?modules=${encodeURIComponent(JSON.stringify({request:"C:/Work/Application/a.ts",ids:[]}))}&server=true!`,
  `${loader}?modules=${encodeURIComponent(JSON.stringify({request:"C:/Work/App2/a.ts",ids:[]}))}&server=true!`,
  `${loader}?modules=${encodeURIComponent(JSON.stringify({request:"C%3A%2FWork%2FApp%2Fa.ts",ids:[]}))}&server=true!`,
 ];
 for(const value of unchanged) assert.equal(canonicalizeNextFlightEntryIdentifier(value,project),value);
});

test("exact Next 15.5.21 rawRequest prefix canonicalizes Windows and POSIX identically", async()=>{
 const { canonicalizeNextFlightEntryIdentifier, moduleIdentityReport }=await import("./stable-module-ids.mjs");
 const posixRoot="/home/runner/work/growthmap/src/frontend",winRoot="D:/a/growthmap/src/frontend";
 const option=(request)=>encodeURIComponent(JSON.stringify({request,ids:[]}));
 const posix=`next-flight-client-entry-loader?modules=${option(`${posixRoot}/src/app/page.tsx`)}&server=false!`;
 const windows=`next-flight-client-entry-loader?server=false&modules=${option("D:\\a\\growthmap\\src\\frontend\\src\\app\\page.tsx")}!`;
 const normalized=canonicalizeNextFlightEntryIdentifier(posix,posixRoot);
 assert.equal(normalized,canonicalizeNextFlightEntryIdentifier(windows,winRoot));
 assert.match(normalized,/^next-flight-client-entry-loader\?modules=.*%3CPROJECT_ROOT%3E%2Fsrc%2Fapp%2Fpage\.tsx.*&server=false!$/);
 assert.doesNotMatch(normalized,/%5c|growthmap|D%3A/i);
 for(const [raw,root] of [[posix,posixRoot],[windows,winRoot]]){
  const report=moduleIdentityReport({identifier(){return normalized},rawRequest:raw},root);
  assert.equal(report.rawRequest.normalizedSha256,report.identifier.normalizedSha256);
  assert.deepEqual(report.rawRequest.structure.loaderBasenames,[]);
  assert.deepEqual(report.rawRequest.structure.queryKeys,["modules","server"]);
 }
});

test("rawRequest canonicalization requires exact prefix and closed query schema", async()=>{
 const { canonicalizeNextFlightEntryIdentifier }=await import("./stable-module-ids.mjs");
 const project="C:/Work/App",encoded=encodeURIComponent(JSON.stringify({request:"C:\\Work\\App\\src\\a.ts",ids:["*"]}));
 const valid=`next-flight-client-entry-loader?modules=${encoded}&server=true!`;
 assert.notEqual(canonicalizeNextFlightEntryIdentifier(valid,project),valid);
 const unchanged=[
  `modules=${encoded}&server=true!`,
  `?modules=${encoded}&server=true!`,
  `other-flight-client-entry-loader?modules=${encoded}&server=true!`,
  `next-flight-client-entry-loader-x?modules=${encoded}&server=true!`,
  `next-flight-client-entry-loader?modules=${encoded}!`,
  `next-flight-client-entry-loader?modules=${encoded}&server=true&server=false!`,
  `next-flight-client-entry-loader?modules=${encoded}&server=true&unknown=x!`,
  `next-flight-client-entry-loader?modules=${encodeURIComponent(encoded)}&server=true!`,
  `next-flight-client-entry-loader?modules=%7B%22request%22%3A%ZZ&server=true!`,
 ];
 for(const value of unchanged) assert.equal(canonicalizeNextFlightEntryIdentifier(value,project),value);
});
