'use strict';
const {secureFiles}=require('./secure-files');
const MAX_SECRET_CHARS=16384,MAX_SECRET_BYTES=32768;
function validSecret(value){return typeof value==='string'&&value.length>0&&value.length<=MAX_SECRET_CHARS&&!value.includes('\0')&&Buffer.byteLength(value,'utf8')<=MAX_SECRET_BYTES}
function createSecretStore(options){
 const {trustedRoot,directory,encrypt,decrypt,putRemote,hydrateRemote=putRemote,deleteRemote,recoverRemote,recoverStatus,warn=()=>{},windowsAdapter=null,platform=process.platform}=options;
 const files=options.files===undefined?secureFiles(trustedRoot||directory,directory,undefined,{windowsAdapter,platform,...(options.ownerUid===undefined?{}:{ownerUid:options.ownerUid})}):options.files;
 const valid=id=>{if(!/^[A-Za-z0-9-]{1,80}$/.test(id))throw Error('Invalid provider id');return id};
 const bin=id=>`${valid(id)}.bin`,journal=id=>`${valid(id)}.recover`;
 const decode=async(name,label)=>{let value;try{value=JSON.parse(decrypt(await files.read(name)))}catch{throw Error(`Invalid credential recovery ${label}`)}return value};
 const readJournal=async name=>{const value=await decode(name,'journal');if(!value||value.v!==1||!Number.isSafeInteger(value.revision)||value.revision<1||!['set','delete'].includes(value.operation)||typeof value.id!=='string'||journal(value.id)!==name||(value.operation==='set'&&!validSecret(value.value))||(value.operation==='delete'&&Object.hasOwn(value,'value')))throw Error('Invalid credential recovery journal');return value};
 const promote=async j=>{if(j.operation==='set')await files.write(bin(j.id),encrypt(j.value));else await files.remove(bin(j.id));await files.remove(journal(j.id))};
 const entries=async()=>{const names=await files.list();for(const name of names)if(!/^[A-Za-z0-9-]{1,80}\.(?:bin|recover)$/.test(name))throw Error('Unknown secret-store artifact');return names};
 const quarantine=async(name,reason)=>{try{await files.quarantine(name)}catch{}warn(`A stored provider key was quarantined (${reason}). Re-enter it in Settings.`)};
 return{
  has:id=>files.exists(bin(id)),
  async set(id,value){if(!validSecret(value))throw Error('INVALID_PROVIDER_CREDENTIAL');try{await putRemote(valid(id),value);await files.write(bin(id),encrypt(value));return true}catch{throw Error('API key could not be stored securely')}},
  async delete(id){await deleteRemote(valid(id));try{await files.remove(bin(id))}catch{throw Error('API key could not be removed securely')}return true},
  async recover(id,revision,operation,value){if(!Number.isSafeInteger(revision)||revision<1||!['set','delete'].includes(operation)||operation==='set'&&!validSecret(value))throw Error('INVALID_PROVIDER_CREDENTIAL');const name=journal(id),desired={v:1,id:valid(id),revision,operation,...(operation==='set'?{value}:{})};if(await files.exists(name)){const old=await readJournal(name);if(JSON.stringify(old)!==JSON.stringify(desired))throw Error('A different credential recovery is pending')}else await files.write(name,encrypt(JSON.stringify(desired)));try{await recoverRemote(id,revision,operation,value);await promote(desired);return true}catch{throw Error('Credential recovery could not be completed securely')}},
  async reconcile(){for(const name of (await entries()).filter(n=>n.endsWith('.recover'))){const j=await readJournal(name),status=await recoverStatus(j.id);if(status.revision!==j.revision)throw Error('Stale credential recovery journal');if(status.secret_change_pending)await recoverRemote(j.id,j.revision,j.operation,j.value);else if(status.credential_status!=='ready')throw Error('Ambiguous credential recovery state');await promote(j)}},
  async hydrate(){const names=await entries();if(names.some(n=>n.endsWith('.recover')))throw Error('Credential recovery must be reconciled before hydration');for(const name of names.filter(n=>n.endsWith('.bin'))){const id=name.slice(0,-4);let value;try{value=decrypt(await files.read(name));if(!validSecret(value))throw Error()}catch{await quarantine(name,'corrupt');continue}try{await hydrateRemote(id,value)}catch(error){if(error&&error.statusCode===404){await quarantine(name,'stale provider');continue}throw Error('A stored provider key could not be loaded securely')}}}
 };
}
module.exports={createSecretStore,validSecret,MAX_SECRET_CHARS,MAX_SECRET_BYTES};
