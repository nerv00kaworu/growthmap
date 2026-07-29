'use strict';
const crypto=require('node:crypto'),fs=require('node:fs'),path=require('node:path');
const {parseStrictJson}=require('./strict-json');
function createProtectedHistory({userData,encrypt,decrypt}){const file=path.join(userData,'commercial-history.bin'),presence=path.join(userData,'commercial-history-presence.bin');
 const exact=(x,keys)=>x&&typeof x==='object'&&!Array.isArray(x)&&Object.keys(x).sort().join('\0')===keys.slice().sort().join('\0');
 function decode(target){return parseStrictJson(decrypt(fs.readFileSync(target)));}
 function read(){const a=fs.existsSync(file),b=fs.existsSync(presence);if(!a&&!b)return new Set();if(!a||!b)return null;try{const x=decode(file),p=decode(presence);if(!exact(x,['schemaVersion','kinds'])||!exact(p,['schemaVersion','kind'])||x.schemaVersion!==1||p.schemaVersion!==1||p.kind!=='growthmap-commercial-history-present'||!Array.isArray(x.kinds)||x.kinds.length<1||x.kinds.some(k=>!['paid','revocation'].includes(k))||new Set(x.kinds).size!==x.kinds.length)throw Error();return new Set(x.kinds);}catch{return null;}}
 function atomic(target,value){const temp=`${target}.${process.pid}.${crypto.randomUUID()}.tmp`;try{fs.writeFileSync(temp,encrypt(JSON.stringify(value)),{mode:0o600,flag:'wx'});fs.renameSync(temp,target);}finally{try{fs.unlinkSync(temp);}catch{}}}
 function mark(kind){const prior=read();if(!prior)throw Error('Protected commercial history is invalid');prior.add(kind);fs.mkdirSync(userData,{recursive:true,mode:0o700});atomic(presence,{schemaVersion:1,kind:'growthmap-commercial-history-present'});atomic(file,{schemaVersion:1,kinds:[...prior].sort()});}
 return {read,mark,file,presence};}
module.exports={createProtectedHistory};
