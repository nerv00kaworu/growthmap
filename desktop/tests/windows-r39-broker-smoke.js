'use strict';
const path=require('node:path'),{createWindowsNativeBroker}=require('../windows-native-broker');
(async()=>{if(process.platform!=='win32')throw Error('win32 required');const times=[],spawns=[];for(let run=0;run<2;run++){const t=Date.now(),b=createWindowsNativeBroker({onSpawn:x=>spawns.push(x)}),s=await b.start();times.push({run,coldMs:Date.now()-t,ownerSid:s.ownerSid,acl:s.acl,childPid:s.childPid});await b.request('shutdown',{});await b.close()}console.log(JSON.stringify({ok:true,times,spawns}))})().catch(e=>{console.error(e.stage,e.stack||e);process.exit(1)});
