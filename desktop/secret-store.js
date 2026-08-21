'use strict';
const {secureFiles}=require('./secure-files');
const MAX_SECRET_CHARS=16384,MAX_SECRET_BYTES=32768;
function validSecret(value){return typeof value==='string'&&value.length>0&&value.length<=MAX_SECRET_CHARS&&!value.includes('\0')&&Buffer.byteLength(value,'utf8')<=MAX_SECRET_BYTES}
function createSecretStore({trustedRoot,directory,encrypt,decrypt,putRemote,hydrateRemote=putRemote,deleteRemote,recoverRemote,recoverStatus,warn=()=>{},files=secureFiles(trustedRoot||directory,directory)}){
 const valid=id=>{if(!/^[A-Za-z0-9-]{1,80}$/.test(id))throw Error('Invalid provider id');return id};
 const bin=id=>`${valid(id)}.bin`,journal=id=>`${valid(id)}.recover`;
 const decode=(name,label)=>{let value;try{value=JSON.parse(decrypt(files.read(name)))}catch{throw Error(`Invalid credential recovery ${label}`)}return value};
 const readJournal=name=>{const value=decode(name,'journal');if(!value||value.v!==1||!Number.isSafeInteger(value.revision)||value.revision<1||!['set','delete'].includes(value.operation)||typeof value.id!=='string'||journal(value.id)!==name||(value.operation==='set'&&!validSecret(value.value))||(value.operation==='delete'&&Object.hasOwn(value,'value')))throw Error('Invalid credential recovery journal');return value};
 const promote=j=>{if(j.operation==='set')files.write(bin(j.id),encrypt(j.value));else files.remove(bin(j.id));files.remove(journal(j.id))};
 const entries=()=>{const names=files.list();for(const name of names)if(!/^[A-Za-z0-9-]{1,80}\.(?:bin|recover)$/.test(name))throw Error('Unknown secret-store artifact');return names};
 const quarantine=(name,reason)=>{try{files.quarantine(name)}catch{}warn(`A stored provider key was quarantined (${reason}). Re-enter it in Settings.`)};
 return{
  has:id=>files.exists(bin(id)),
  async set(id,value){if(!validSecret(value))throw Error('INVALID_PROVIDER_CREDENTIAL');try{await putRemote(valid(id),value);files.write(bin(id),encrypt(value));return true}catch{throw Error('API key could not be stored securely')}},
  async delete(id){await deleteRemote(valid(id));try{files.remove(bin(id))}catch{throw Error('API key could not be removed securely')}return true},
  async recover(id,revision,operation,value){if(!Number.isSafeInteger(revision)||revision<1||!['set','delete'].includes(operation)||operation==='set'&&!validSecret(value))throw Error('INVALID_PROVIDER_CREDENTIAL');const name=journal(id),desired={v:1,id:valid(id),revision,operation,...(operation==='set'?{value}:{})};if(files.exists(name)){const old=readJournal(name);if(JSON.stringify(old)!==JSON.stringify(desired))throw Error('A different credential recovery is pending')}else files.write(name,encrypt(JSON.stringify(desired)));try{await recoverRemote(id,revision,operation,value);promote(desired);return true}catch{throw Error('Credential recovery could not be completed securely')}},
  async reconcile(){for(const name of entries().filter(n=>n.endsWith('.recover'))){const j=readJournal(name),status=await recoverStatus(j.id);if(status.revision!==j.revision)throw Error('Stale credential recovery journal');if(status.secret_change_pending)await recoverRemote(j.id,j.revision,j.operation,j.value);else if(status.credential_status!=='ready')throw Error('Ambiguous credential recovery state');promote(j)}},
  async hydrate(){const names=entries();if(names.some(n=>n.endsWith('.recover')))throw Error('Credential recovery must be reconciled before hydration');for(const name of names.filter(n=>n.endsWith('.bin'))){const id=name.slice(0,-4);let value;try{value=decrypt(files.read(name));if(!validSecret(value))throw Error()}catch{quarantine(name,'corrupt');continue}try{await hydrateRemote(id,value)}catch(error){if(error&&error.statusCode===404){quarantine(name,'stale provider');continue}throw Error('A stored provider key could not be loaded securely')}}}
 };
}
module.exports={createSecretStore,validSecret,MAX_SECRET_CHARS,MAX_SECRET_BYTES};
