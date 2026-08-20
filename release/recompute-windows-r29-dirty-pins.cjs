'use strict';
// Review-only helper for a deliberately dirty candidate. It never weakens the
// clean committed verifier used by release CI and writes nothing.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..');
const manifest=JSON.parse(fs.readFileSync(path.join(__dirname,'windows-r29-candidate.json'),'utf8'));
for(const relative of Object.keys(manifest.integrity)){
 const absolute=path.resolve(root,relative);
 if(!absolute.startsWith(root+path.sep)||!fs.statSync(absolute).isFile())throw Error(`Invalid path: ${relative}`);
 console.log(`${crypto.createHash('sha256').update(fs.readFileSync(absolute)).digest('hex')}  ${relative}`);
}
