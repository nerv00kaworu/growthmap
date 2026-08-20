'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),cp=require('node:child_process');
const root=path.resolve(__dirname,'..'),manifestPath=path.join(__dirname,'windows-r29-candidate.json');
const manifest=JSON.parse(fs.readFileSync(manifestPath,'utf8'));
if(manifest.releaseStatus!=='candidate-not-released'||manifest.source.tag!==null||manifest.source.release!==null)throw new Error('R29 metadata must not claim a tag or release');
if(manifest.scope.platform!=='windows'||manifest.scope.arch!=='x64'||manifest.scope.channel!=='unsigned-commercial'||manifest.scope.linuxSidecarReleaseGate!==false)throw new Error('R29 scope mismatch');
const status=cp.execFileSync('git',['status','--porcelain=v1','--untracked-files=all'],{cwd:root,encoding:'utf8'});
if(status!=='')throw new Error('R29 candidate integrity requires a clean committed checkout');
for(const [relative,expected] of Object.entries(manifest.integrity)){
 const absolute=path.resolve(root,relative);if(!absolute.startsWith(root+path.sep)||!fs.statSync(absolute).isFile())throw new Error(`Invalid integrity path: ${relative}`);
 if(relative.includes('\\')||relative.startsWith('/')||relative.split('/').includes('..'))throw new Error(`Non-canonical integrity path: ${relative}`);
 let committed;try{committed=cp.execFileSync('git',['show',`HEAD:${relative}`],{cwd:root,encoding:null,maxBuffer:16*1024*1024});}catch{throw new Error(`Integrity path is not committed at HEAD: ${relative}`);}
 const actual=crypto.createHash('sha256').update(committed).digest('hex');if(actual!==expected)throw new Error(`Integrity mismatch: ${relative}`);
}
console.log(`Verified ${Object.keys(manifest.integrity).length} committed R29 candidate integrity pins.`);
