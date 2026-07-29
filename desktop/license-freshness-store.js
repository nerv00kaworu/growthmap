'use strict';
const crypto=require('node:crypto'),fs=require('node:fs'),path=require('node:path');
function createLicenseFreshnessStore({userData,encrypt,decrypt,now=()=>new Date()}){
 const state=path.join(userData,'license-freshness.json'),receipt=path.join(userData,'license-freshness.bin');
 const exact=(v,k)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join('\0')===k.slice().sort().join('\0');
 function read(){const a=fs.existsSync(state),b=fs.existsSync(receipt);if(!a&&!b)return null;if(!a||!b)return {invalid:true};try{const x=JSON.parse(fs.readFileSync(state,'utf8')),y=JSON.parse(decrypt(fs.readFileSync(receipt)));if(!exact(x,['schemaVersion','licenseId','lastSeenAt'])||!exact(y,['schemaVersion','licenseId','lastSeenAt','sha256'])||x.schemaVersion!==1||y.schemaVersion!==1||x.licenseId!==y.licenseId||x.lastSeenAt!==y.lastSeenAt||y.sha256!==crypto.createHash('sha256').update(JSON.stringify(x)).digest('hex'))throw Error();return x;}catch{return {invalid:true};}}
 function checkpoint(licenseId){const prior=read(),instant=now();if(prior?.invalid)throw Error('License freshness evidence is invalid');if(prior&&prior.licenseId!==licenseId)throw Error('License freshness identity mismatch');if(prior&&instant.getTime()+300000<Date.parse(prior.lastSeenAt))throw Error('System clock rollback detected');const x={schemaVersion:1,licenseId,lastSeenAt:instant.toISOString()},y={...x,sha256:crypto.createHash('sha256').update(JSON.stringify(x)).digest('hex')};fs.mkdirSync(userData,{recursive:true,mode:0o700});for(const [target,bytes] of [[state,Buffer.from(JSON.stringify(x))],[receipt,encrypt(JSON.stringify(y))]]){const temp=`${target}.${process.pid}.${crypto.randomUUID()}.tmp`;fs.writeFileSync(temp,bytes,{mode:0o600,flag:'wx'});fs.renameSync(temp,target);}return x;}
 return {read,checkpoint,paths:{state,receipt}};
}
module.exports={createLicenseFreshnessStore};
