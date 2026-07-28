'use strict';
const crypto=require('node:crypto');
const PREFIX='growthmap-startup-v1';
const MODES=new Set(['paid','trial','fresh','extraction']);
function canonicalStartupVerdict(mode,nonce){
 if(!MODES.has(mode))throw new Error('Invalid startup verdict mode');
 if(!/^[A-Za-z0-9_-]{32,128}$/.test(nonce))throw new Error('Invalid startup verdict nonce');
 return `${PREFIX}:${mode}:${nonce}`;
}
function createStartupVerdict({mode,token,nonce=crypto.randomBytes(32).toString('base64url')}){
 if(typeof token!=='string'||token.length===0)throw new Error('Startup verdict token is required');
 const mac=crypto.createHmac('sha256',Buffer.from(token,'utf8')).update(Buffer.from(canonicalStartupVerdict(mode,nonce),'utf8')).digest('hex');
 return {mode,nonce,mac};
}
function startupVerdictEnv({verdict,token}){
 if(!verdict||typeof token!=='string'||token.length===0)throw new Error('Startup verdict and token are required');
 return {GROWTHMAP_SESSION_TOKEN:token,GROWTHMAP_STARTUP_VERDICT_MODE:verdict.mode,GROWTHMAP_STARTUP_VERDICT_NONCE:verdict.nonce,GROWTHMAP_STARTUP_VERDICT_MAC:verdict.mac};
}
module.exports={canonicalStartupVerdict,createStartupVerdict,startupVerdictEnv};
