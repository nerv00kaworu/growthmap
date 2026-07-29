'use strict';
const crypto=require('node:crypto'),fs=require('node:fs'),path=require('node:path');
const {createProtectedHistory}=require('./protected-history');
const {parseStrictJson}=require('./strict-json');
function exact(v,keys){return v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join('\0')===keys.slice().sort().join('\0');}
function createRevocationStore({userData,encrypt,decrypt}){
 const history=createProtectedHistory({userData,encrypt,decrypt});
 const assertion=path.join(userData,'revocation.json'),receipt=path.join(userData,'revocation-receipt.bin');
 const digest=b=>crypto.createHash('sha256').update(b).digest('hex');
 function inspect(){
  const a=fs.existsSync(assertion),r=fs.existsSync(receipt);if(!a&&!r){const h=history.read();return h===null||h.has('revocation')?{state:'invalid',reason:'revocation_evidence_deleted'}:{state:'none'};}if(!a||!r)return {state:'invalid',reason:'revocation_evidence_deleted'};
  try{const bytes=fs.readFileSync(assertion),doc=parseStrictJson(bytes.toString('utf8')),mark=JSON.parse(decrypt(fs.readFileSync(receipt)));if(!exact(mark,['schemaVersion','licenseId','sequence','sha256'])||mark.schemaVersion!==1||mark.licenseId!==doc.license_id||mark.sequence!==doc.sequence||mark.sha256!==digest(bytes))throw Error('mismatch');return {state:'accepted',licenseId:mark.licenseId,sequence:mark.sequence};}catch{return {state:'invalid',reason:'revocation_evidence_tampered'};}
 }
 function commit(doc){
  const current=inspect();if(current.state==='invalid')throw Error('Stored revocation evidence is invalid');if(current.state==='accepted'&&doc.sequence<=current.sequence)throw Error('Revocation sequence replay');
  fs.mkdirSync(userData,{recursive:true,mode:0o700});const bytes=Buffer.from(JSON.stringify(doc));const mark={schemaVersion:1,licenseId:doc.license_id,sequence:doc.sequence,sha256:digest(bytes)};
  const at=`${assertion}.${process.pid}.${crypto.randomUUID()}.tmp`,rt=`${receipt}.${process.pid}.${crypto.randomUUID()}.tmp`;
  try{fs.writeFileSync(at,bytes,{mode:0o600,flag:'wx'});fs.writeFileSync(rt,encrypt(JSON.stringify(mark)),{mode:0o600,flag:'wx'});fs.renameSync(at,assertion);fs.renameSync(rt,receipt);}finally{for(const f of [at,rt])try{fs.unlinkSync(f);}catch{}}
  history.mark('revocation');return inspect();
 }
 return {inspect,commit,paths:{assertion,receipt}};
}
module.exports={createRevocationStore};
