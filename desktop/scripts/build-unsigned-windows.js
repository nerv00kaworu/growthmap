'use strict';
const {spawnSync}=require('node:child_process'),path=require('node:path');
if(process.platform!=='win32')throw new Error('Unsigned Windows packaging must run on Windows');
const env={...process.env,GROWTHMAP_UNSIGNED_MANUAL_RELEASE:'1',CSC_IDENTITY_AUTO_DISCOVERY:'false'};
for(const key of ['CSC_LINK','CSC_KEY_PASSWORD','WIN_CSC_LINK','WIN_CSC_KEY_PASSWORD'])delete env[key];
let preflight=spawnSync(process.execPath,[path.join(__dirname,'preflight.js'),'win32'],{env,stdio:'inherit'});if(preflight.status!==0)process.exit(preflight.status??1);
const packageFile=require.resolve('electron-builder/package.json'),packageDoc=require(packageFile),bin=typeof packageDoc.bin==='string'?packageDoc.bin:packageDoc.bin?.['electron-builder'];if(!bin)throw new Error('electron-builder package has no public CLI bin');const cli=path.resolve(path.dirname(packageFile),bin);const result=spawnSync(process.execPath,[cli,'--win','nsis','--publish','never'],{cwd:path.resolve(__dirname,'..'),env,stdio:'inherit'});if(result.status!==0)process.exit(result.status??1);
