'use strict';
const crypto=require('node:crypto'),fs=require('node:fs'),path=require('node:path');
const {createProtectedHistory}=require('./protected-history');
const {parseStrictJson}=require('./strict-json');
function createLicenseFreshnessStore({userData,encrypt,decrypt,now=()=>new Date()}){
 const history=createProtectedHistory({userData,encrypt,decrypt});
 const state=path.join(userData,'license-freshness.json'),receipt=path.join(userData,'license-freshness.bin');
 const exact=(v,k)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join('\0')===k.slice().sort().join('\0');
 function read(){const a=fs.existsSync(state),b=fs.existsSync(receipt),h=history.read();if(h===null)return {invalid:true};if(!a&&!b)return h.has('paid')?{invalid:true}:null;if(!a||!b||!h.has('paid'))return {invalid:true};try{const x=parseStrictJson(fs.readFileSync(state,'utf8')),y=parseStrictJson(decrypt(fs.readFileSync(receipt)));if(!exact(x,['schemaVersion','licenseId','firstSeenAt','lastSeenAt'])||!exact(y,['schemaVersion','licenseId','firstSeenAt','lastSeenAt','sha256'])||x.schemaVersion!==1||y.schemaVersion!==1||x.licenseId!==y.licenseId||x.firstSeenAt!==y.firstSeenAt||x.lastSeenAt!==y.lastSeenAt||y.sha256!==crypto.createHash('sha256').update(JSON.stringify(x)).digest('hex'))throw Error();return x;}catch{return {invalid:true};}}
 function checkpoint(licenseId){const prior=read(),instant=now();if(prior?.invalid)throw Error('License freshness evidence is invalid');if(prior&&prior.licenseId!==licenseId)throw Error('License freshness identity mismatch');if(prior&&instant.getTime()+300000<Date.parse(prior.lastSeenAt))throw Error('System clock rollback detected');const x={schemaVersion:1,licenseId,firstSeenAt:prior?.firstSeenAt||instant.toISOString(),lastSeenAt:instant.toISOString()},y={...x,sha256:crypto.createHash('sha256').update(JSON.stringify(x)).digest('hex')};fs.mkdirSync(userData,{recursive:true,mode:0o700});for(const [target,bytes] of [[state,Buffer.from(JSON.stringify(x))],[receipt,encrypt(JSON.stringify(y))]]){const temp=`${target}.${process.pid}.${crypto.randomUUID()}.tmp`;fs.writeFileSync(temp,bytes,{mode:0o600,flag:'wx'});fs.renameSync(temp,target);}history.mark('paid');return x;}
 return {read,checkpoint,paths:{state,receipt,history:history.file,historyPresence:history.presence}};
}
module.exports={createLicenseFreshnessStore};
