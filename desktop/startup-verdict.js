'use strict';
const crypto=require('node:crypto');
const PREFIX='growthmap-startup-v2';
const PROOF_DOMAIN=Buffer.from('growthmap-device-startup-v1\0');
// `trial` remains accepted as a signed transport value for compatibility with
// older desktop launchers, but the backend interprets it as permanent Free.
const MODES=new Set(['paid','free','trial','fresh','extraction']);
function fields({mode,devicePublicKey,nonce,session}){
 if(!MODES.has(mode))throw new Error('Invalid startup verdict mode');
 if(!/^[A-Za-z0-9_-]{32,128}$/.test(nonce))throw new Error('Invalid startup verdict nonce');
 if(typeof devicePublicKey!=='string'||devicePublicKey.length<40)throw new Error('Device public key is required');
 if(typeof session!=='string'||session.length<32)throw new Error('Startup session is required');
 return {device_public_key:devicePublicKey,mode,nonce,session};
}
function canonicalStartupProof(value){return Buffer.concat([PROOF_DOMAIN,Buffer.from(JSON.stringify(fields(value)),'utf8')]);}
function canonicalStartupVerdict(value){const f=fields(value);if(typeof value.proof!=='string'||!value.proof)throw new Error('Startup device proof is required');return Buffer.from(`${PREFIX}:${f.mode}:${f.device_public_key}:${f.nonce}:${f.session}:${value.proof}`,'utf8');}
function createStartupVerdict({mode,token,devicePublicKey,privateKeyPem,nonce=crypto.randomBytes(32).toString('base64url'),session=crypto.randomBytes(32).toString('base64url')}){
 if(typeof token!=='string'||token.length===0)throw new Error('Startup verdict token is required');
 const f={mode,devicePublicKey,nonce,session};const proof=crypto.sign(null,canonicalStartupProof(f),privateKeyPem).toString('base64');
 const mac=crypto.createHmac('sha256',Buffer.from(token,'utf8')).update(canonicalStartupVerdict({...f,proof})).digest('hex');
 return {...f,proof,mac};
}
function startupVerdictEnv({verdict,token}){
 if(!verdict||typeof token!=='string'||token.length===0)throw new Error('Startup verdict and token are required');
 return {GROWTHMAP_SESSION_TOKEN:token,GROWTHMAP_STARTUP_VERDICT_MODE:verdict.mode,GROWTHMAP_DEVICE_PUBLIC_KEY:verdict.devicePublicKey,GROWTHMAP_STARTUP_VERDICT_NONCE:verdict.nonce,GROWTHMAP_STARTUP_SESSION:verdict.session,GROWTHMAP_STARTUP_DEVICE_PROOF:verdict.proof,GROWTHMAP_STARTUP_VERDICT_MAC:verdict.mac};
}
function sidecarSessionEnv(scrubbedEnv,token){
 if(typeof token!=='string'||token.length===0)throw new Error('Sidecar session token is required');
 return {...scrubbedEnv,GROWTHMAP_SESSION_TOKEN:token};
}
module.exports={canonicalStartupProof,canonicalStartupVerdict,createStartupVerdict,startupVerdictEnv,sidecarSessionEnv};
