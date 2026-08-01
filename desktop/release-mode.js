'use strict';
const fs=require('node:fs'),path=require('node:path');
const MODES=new Set(['unsigned-manual','signed-commercial']);
function loadReleaseMode({isPackaged,resourcesPath,appDir=__dirname}){const file=isPackaged?path.join(resourcesPath,'app.asar','release-mode.json'):path.join(appDir,'release-mode.json'),doc=JSON.parse(fs.readFileSync(file,'utf8'));if(Object.keys(doc).sort().join('|')!=='mode|publisherDisplay|schemaVersion|updatesEnabled'||doc.schemaVersion!==1||!MODES.has(doc.mode)||typeof doc.publisherDisplay!=='string'||typeof doc.updatesEnabled!=='boolean')throw Error('Invalid release mode metadata');if(doc.mode==='unsigned-manual'&&(doc.updatesEnabled||doc.publisherDisplay!=='Unknown Publisher'))throw Error('Unsigned release mode must disable updates');if(doc.mode==='signed-commercial'&&(!doc.updatesEnabled||doc.publisherDisplay==='Unknown Publisher'))throw Error('Signed release mode metadata mismatch');return Object.freeze(doc);}
module.exports={loadReleaseMode};
