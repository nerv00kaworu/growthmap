'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),manifestPath=path.join(__dirname,'windows-r29-candidate.json');
const manifest=JSON.parse(fs.readFileSync(manifestPath,'utf8'));
if(manifest.releaseStatus!=='candidate-not-released'||manifest.source.tag!==null||manifest.source.release!==null)throw new Error('R29 metadata must not claim a tag or release');
if(manifest.scope.platform!=='windows'||manifest.scope.arch!=='x64'||manifest.scope.channel!=='unsigned-commercial'||manifest.scope.linuxSidecarReleaseGate!==false)throw new Error('R29 scope mismatch');
for(const [relative,expected] of Object.entries(manifest.integrity)){
 const absolute=path.resolve(root,relative);if(!absolute.startsWith(root+path.sep)||!fs.statSync(absolute).isFile())throw new Error(`Invalid integrity path: ${relative}`);
 const actual=crypto.createHash('sha256').update(fs.readFileSync(absolute)).digest('hex');if(actual!==expected)throw new Error(`Integrity mismatch: ${relative}`);
}
console.log(`Verified ${Object.keys(manifest.integrity).length} R29 candidate integrity pins.`);
