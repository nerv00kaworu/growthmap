'use strict';
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
const {scan,stable}=require('./csp-manifest');
const root=path.resolve(__dirname,'..','..'), source=path.join(root,'src','frontend');
const temporary=[];
try{
  // Three unrelated absolute roots catch path leakage while keeping every run
  // a clean dependency install and production build.
  for(const label of ['a','b','encoded root %20']){
    const dir=fs.mkdtempSync(path.join(os.tmpdir(),`growthmap-deterministic-${label}-`));temporary.push(dir);
    const frontend=path.join(dir,'src','frontend');fs.mkdirSync(path.dirname(frontend),{recursive:true});
    fs.cpSync(source,frontend,{recursive:true,filter:(entry)=>!['node_modules','.next','out','tsconfig.tsbuildinfo'].includes(path.basename(entry))});
    const scripts=path.join(dir,'desktop','scripts');fs.mkdirSync(scripts,{recursive:true});
    for(const file of ['csp-manifest.js','generate-csp-manifest.js','verify-client-reference-boundary.js'])fs.copyFileSync(path.join(__dirname,file),path.join(scripts,file));
    const run=(command,args)=>{const r=spawnSync(command,args,{cwd:frontend,stdio:'inherit',shell:process.platform==='win32'});if(r.status!==0)throw new Error(`${command} failed`);};
    run('npm',['ci']);run('npm',['run','build']);
  }
  const manifests=temporary.map(dir=>stable(scan(path.join(dir,'src','frontend','out'))));
  for(const manifest of manifests.slice(1))assert.equal(manifests[0],manifest,'clean production builds produced different complete CSP manifests');
  const tracked=fs.readFileSync(path.join(root,'desktop','generated','csp-script-hashes.json'),'utf8');assert.equal(tracked,manifests[0]);
  console.log(`Three clean builds and tracked CSP manifest are identical: ${crypto.createHash('sha256').update(tracked).digest('hex')}`);
}finally{for(const dir of temporary)fs.rmSync(dir,{recursive:true,force:true});}
