'use strict';
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');

const SCRIPT_RE=/<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi;
const SRC_RE=/(?:^|\s)src\s*=/i;

function htmlFiles(directory){
  const found=[];
  function visit(dir){
    for(const entry of fs.readdirSync(dir,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name,'en'))){
      const absolute=path.join(dir,entry.name);
      if(entry.isDirectory())visit(absolute);
      else if(entry.isFile()&&entry.name.endsWith('.html'))found.push(absolute);
    }
  }
  visit(directory);
  return found;
}
function hash(content){return `sha256-${crypto.createHash('sha256').update(content,'utf8').digest('base64')}`;}
function scan(outDirectory){
  const files={};
  for(const absolute of htmlFiles(outDirectory)){
    const relative=path.relative(outDirectory,absolute).split(path.sep).join('/');
    const source=fs.readFileSync(absolute,'utf8');
    const hashes=[];
    for(const match of source.matchAll(SCRIPT_RE))if(!SRC_RE.test(match[1]))hashes.push(hash(match[2]));
    files[relative]=hashes;
  }
  const hashes=[...new Set(Object.values(files).flat())].sort();
  return {version:1,algorithm:'sha256',files,hashes};
}
function stable(manifest){return `${JSON.stringify(manifest,null,2)}\n`;}
function verify(manifest,outDirectory){
  const expected=scan(outDirectory);
  if(stable(manifest)!==stable(expected))throw new Error('CSP script hash manifest is stale or incomplete; run npm run csp:generate after the frontend build');
  return expected;
}
module.exports={hash,scan,stable,verify};
