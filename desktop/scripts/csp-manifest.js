'use strict';
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');

const SCRIPT_RE=/<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi;
const SRC_RE=/(?:^|\s)src\s*=/i;
const PAGE_CHUNK_RE=/^_next\/static\/chunks\/app\/page-[A-Za-z0-9]+\.js$/;
const PAGE_TOKEN='__GROWTHMAP_APP_PAGE_CHUNK__';

function digest(content){return crypto.createHash('sha256').update(content,'utf8').digest('hex');}
function hash(content){return `sha256-${crypto.createHash('sha256').update(content,'utf8').digest('base64')}`;}
function filesBelow(directory,predicate){
  const found=[];
  function visit(dir){
    for(const entry of fs.readdirSync(dir,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name,'en'))){
      const absolute=path.join(dir,entry.name);
      if(entry.isDirectory())visit(absolute);else if(entry.isFile()&&predicate(absolute))found.push(absolute);
    }
  }
  visit(directory);return found;
}
function htmlFiles(directory){return filesBelow(directory,file=>file.endsWith('.html'));}
function lexicalState(text,index,state){
  const char=text[index],next=text[index+1];
  if(state.quote){if(state.escape)state.escape=false;else if(char==='\\')state.escape=true;else if(char===state.quote)state.quote=null;return 0;}
  if(state.line){if(char==='\n')state.line=false;return 0;}
  if(state.block){if(char==='*'&&next==='/'){state.block=false;return 1;}return 0;}
  if(char==='"'||char==="'"||char==='`'){state.quote=char;return 0;}
  if(char==='/'&&next==='/'){state.line=true;return 1;}
  if(char==='/'&&next==='*'){state.block=true;return 1;}
  return -1;
}
function matching(text,start,open,close){
  if(text[start]!==open)throw new Error('malformed emitted app page chunk');
  const state={};let depth=0;
  for(let i=start;i<text.length;i++){
    const skip=lexicalState(text,i,state);if(skip>=0){i+=skip;continue;}
    if(text[i]===open)depth++;else if(text[i]===close&&--depth===0)return i;
  }
  throw new Error('malformed emitted app page chunk');
}
function splitTopLevel(text,start,end){
  const parts=[];const state={};let square=0,curly=0,round=0,last=start;
  for(let i=start;i<end;i++){
    const skip=lexicalState(text,i,state);if(skip>=0){i+=skip;continue;}
    const c=text[i];if(c==='[')square++;else if(c===']')square--;else if(c==='{')curly++;else if(c==='}')curly--;else if(c==='(')round++;else if(c===')')round--;
    else if(c===','&&!square&&!curly&&!round){parts.push(text.slice(last,i).trim());last=i+1;}
    if(square<0||curly<0||round<0)throw new Error('malformed emitted app page chunk');
  }
  parts.push(text.slice(last,end).trim());
  if(state.quote||state.block||square||curly||round)throw new Error('malformed emitted app page chunk');
  return parts;
}
function colonAtTopLevel(text){
  const state={};let square=0,curly=0,round=0;
  for(let i=0;i<text.length;i++){
    const skip=lexicalState(text,i,state);if(skip>=0){i+=skip;continue;}
    const c=text[i];if(c==='[')square++;else if(c===']')square--;else if(c==='{')curly++;else if(c==='}')curly--;else if(c==='(')round++;else if(c===')')round--;else if(c===':'&&!square&&!curly&&!round)return i;
  }
  return -1;
}
function moduleId(id){
  if(id[0]==='"')return JSON.parse(id);
  if(id[0]!=="'")return id;
  return id.slice(1,-1).replace(/\\(['\\])/g,'$1');
}
function normalizeLocalModuleReferences(factory,modules){
  return factory.replace(/\b([A-Za-z_$][\w$]*)\.bind\(\1,\s*("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\)/g,(match,loader,quoted)=>{
    let referenced;try{referenced=moduleId(quoted);}catch{return match;}
    const target=modules.get(referenced);
    if(target===undefined)return match;
    return `${loader}.bind(${loader},"__GROWTHMAP_LOCAL_MODULE_${digest(target)}__")`;
  });
}
function appPageIdentity(source){
  const marker='.push(';const markerAt=source.indexOf(marker);
  if(markerAt<0)throw new Error('unsupported emitted app page chunk wrapper');
  const open=markerAt+marker.length-1,close=matching(source,open,'(',')');
  if(source.slice(close+1).trim()!==''&&source.slice(close+1).trim()!==';')throw new Error('unsupported emitted app page chunk suffix');
  const argument=source.slice(open+1,close).trim();
  if(!argument.startsWith('[')||matching(argument,0,'[',']')!==argument.length-1)throw new Error('emitted app page chunk tuple must be one array');
  const tuple=splitTopLevel(argument,1,argument.length-1);
  if(tuple.length!==3)throw new Error('emitted app page chunk tuple must have length 3');
  let chunkList;try{chunkList=JSON.parse(tuple[0]);}catch{throw new Error('emitted app page chunk list is malformed');}
  if(!Array.isArray(chunkList)||chunkList.length===0)throw new Error('emitted app page chunk list is unsupported');
  if(!tuple[1].startsWith('{')||matching(tuple[1],0,'{','}')!==tuple[1].length-1)throw new Error('emitted app page module map is malformed');
  const entries=splitTopLevel(tuple[1],1,tuple[1].length-1);
  if(entries.length===1&&entries[0]==='')throw new Error('emitted app page module map is empty');
  const parsed=entries.map(entry=>{
    const colon=colonAtTopLevel(entry);if(colon<=0||colon===entry.length-1)throw new Error('emitted app page module entry is malformed');
    const id=entry.slice(0,colon).trim(),factory=entry.slice(colon+1).trim();
    if(!/^(?:[A-Za-z_$][\w$]*|"(?:\\.|[^"\\])+"|'(?:\\.|[^'\\])+')$/.test(id))throw new Error('emitted app page module ID is malformed');
    if(!factory.includes('=>')&&!/^function\b/.test(factory))throw new Error('emitted app page factory is malformed');
    let value;try{value=moduleId(id);}catch{throw new Error('emitted app page module ID is malformed');}
    return {id:value,factory};
  });
  const modules=new Map();for(const entry of parsed){if(modules.has(entry.id))throw new Error('emitted app page module ID is duplicated');modules.set(entry.id,entry.factory);}
  const factories=parsed.map(({factory})=>{
    const normalized=normalizeLocalModuleReferences(factory,modules);
    return {sha256:digest(normalized),bytes:Buffer.byteLength(normalized,'utf8')};
  }).sort((a,b)=>a.sha256.localeCompare(b.sha256)||a.bytes-b.bytes);
  return {chunkListSha256:digest(tuple[0]),chunkListBytes:Buffer.byteLength(tuple[0],'utf8'),sourceCount:factories.length,sources:factories};
}
function scan(outDirectory){
  const pageFiles=filesBelow(outDirectory,file=>PAGE_CHUNK_RE.test(path.relative(outDirectory,file).split(path.sep).join('/')));
  if(pageFiles.length!==1)throw new Error(`expected exactly one emitted app page chunk, found ${pageFiles.length}`);
  const pageAbsolute=pageFiles[0],pageRelative=path.relative(outDirectory,pageAbsolute).split(path.sep).join('/');
  const pageSource=fs.readFileSync(pageAbsolute,'utf8'),pageName=path.basename(pageRelative);
  const files={},semanticFiles={};
  for(const absolute of htmlFiles(outDirectory)){
    const relative=path.relative(outDirectory,absolute).split(path.sep).join('/');const source=fs.readFileSync(absolute,'utf8');const hashes=[],semanticHashes=[];
    for(const match of source.matchAll(SCRIPT_RE))if(!SRC_RE.test(match[1])){hashes.push(hash(match[2]));semanticHashes.push(hash(match[2].split(pageName).join(PAGE_TOKEN)));}
    files[relative]=hashes;semanticFiles[relative]=semanticHashes;
  }
  const hashes=[...new Set(Object.values(files).flat())].sort();
  return {version:2,algorithm:'sha256',files,hashes,contentIdentity:{version:1,algorithm:'sha256',files:semanticFiles,appPage:appPageIdentity(pageSource)},evidence:{appPage:{file:pageRelative,bytes:Buffer.byteLength(pageSource,'utf8'),sha256:digest(pageSource)}}};
}
function stable(manifest){return `${JSON.stringify(manifest,null,2)}\n`;}
function securityIdentity(manifest){
  if(!manifest||manifest.version!==2||manifest.algorithm!=='sha256'||!manifest.contentIdentity||manifest.contentIdentity.version!==1)throw new Error('unsupported CSP manifest schema');
  return JSON.stringify(manifest.contentIdentity);
}
function equivalent(left,right){return securityIdentity(left)===securityIdentity(right);}
function verify(manifest,outDirectory){const expected=scan(outDirectory);if(stable(manifest)!==stable(expected))throw new Error('CSP script hash manifest is stale or incomplete; run npm run csp:generate after the frontend build');return expected;}
module.exports={appPageIdentity,equivalent,hash,scan,securityIdentity,stable,verify};
