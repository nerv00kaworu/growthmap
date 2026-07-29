'use strict';
const crypto=require('node:crypto'),fs=require('node:fs'),path=require('node:path');
function createProtectedHistory({userData,encrypt,decrypt}){const file=path.join(userData,'commercial-history.bin');
 function read(){try{const x=JSON.parse(decrypt(fs.readFileSync(file)));if(x.schemaVersion!==1||!Array.isArray(x.kinds)||x.kinds.some(k=>!['paid','revocation'].includes(k)))throw Error();return new Set(x.kinds);}catch(e){if(e.code==='ENOENT')return new Set();return null;}}
 function mark(kind){const prior=read();if(!prior)throw Error('Protected commercial history is invalid');prior.add(kind);fs.mkdirSync(userData,{recursive:true,mode:0o700});const temp=`${file}.${process.pid}.${crypto.randomUUID()}.tmp`;fs.writeFileSync(temp,encrypt(JSON.stringify({schemaVersion:1,kinds:[...prior].sort()})),{mode:0o600,flag:'wx'});fs.renameSync(temp,file);}
 return {read,mark,file};}
module.exports={createProtectedHistory};
