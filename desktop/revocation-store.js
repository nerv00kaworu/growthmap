'use strict';
const crypto=require('node:crypto'),fs=require('node:fs'),path=require('node:path');
const {parseStrictJson}=require('./strict-json');
function exact(v,keys){return v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join('\0')===keys.slice().sort().join('\0');}
function createRevocationStore({userData,encrypt,decrypt}){
 const assertion=path.join(userData,'revocation.json'),receipt=path.join(userData,'revocation-receipt.bin'),anchor=path.join(userData,'revocation-prior-use.bin');
 const digest=b=>crypto.createHash('sha256').update(b).digest('hex');
 function readAnchor(){try{const x=parseStrictJson(decrypt(fs.readFileSync(anchor)));if(!exact(x,['schemaVersion','kind','licenseId','highestSequence'])||x.schemaVersion!==1||x.kind!=='growthmap-revocation-prior-use'||typeof x.licenseId!=='string'||!Number.isSafeInteger(x.highestSequence)||x.highestSequence<1)throw Error();return x;}catch(e){return e.code==='ENOENT'?null:{invalid:true};}}
 function inspect(){
  const a=fs.existsSync(assertion),r=fs.existsSync(receipt),prior=readAnchor();if(prior?.invalid)return {state:'invalid',reason:'revocation_evidence_tampered'};if(!a&&!r)return prior?{state:'invalid',reason:'revocation_evidence_deleted'}:{state:'none'};if(!a||!r||!prior)return {state:'invalid',reason:'revocation_evidence_deleted'};
  try{const bytes=fs.readFileSync(assertion),doc=parseStrictJson(bytes.toString('utf8')),mark=parseStrictJson(decrypt(fs.readFileSync(receipt)));if(!exact(mark,['schemaVersion','licenseId','sequence','sha256'])||mark.schemaVersion!==1||mark.licenseId!==doc.license_id||mark.sequence!==doc.sequence||mark.sha256!==digest(bytes)||prior.licenseId!==mark.licenseId||prior.highestSequence!==mark.sequence)throw Error('mismatch');return {state:'accepted',licenseId:mark.licenseId,sequence:mark.sequence};}catch{return {state:'invalid',reason:'revocation_evidence_tampered'};}
 }
 function atomic(target,bytes){const temp=`${target}.${process.pid}.${crypto.randomUUID()}.tmp`;try{fs.writeFileSync(temp,bytes,{mode:0o600,flag:'wx'});fs.renameSync(temp,target);}finally{try{fs.unlinkSync(temp);}catch{}}}
 function commit(doc){
  const current=inspect();if(current.state==='invalid')throw Error('Stored revocation evidence is invalid');if(current.state==='accepted'&&doc.sequence<=current.sequence)throw Error('Revocation sequence replay');
  fs.mkdirSync(userData,{recursive:true,mode:0o700});const bytes=Buffer.from(JSON.stringify(doc)),mark={schemaVersion:1,licenseId:doc.license_id,sequence:doc.sequence,sha256:digest(bytes)},prior={schemaVersion:1,kind:'growthmap-revocation-prior-use',licenseId:doc.license_id,highestSequence:doc.sequence};
  // Anchor first: every interrupted commit is detectably fail-closed.
  atomic(anchor,encrypt(JSON.stringify(prior)));atomic(assertion,bytes);atomic(receipt,encrypt(JSON.stringify(mark)));return inspect();
 }
 return {inspect,commit,paths:{assertion,receipt,anchor}};
}
module.exports={createRevocationStore};
