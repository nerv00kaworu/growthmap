'use strict';
const fs=require('node:fs'),path=require('node:path'),{openEvidence}=require('./safe-open-evidence');
async function evidence(file,validate,options){if(!fs.existsSync(file))return null;const opened=await openEvidence(file,validate,options);return opened}
const value=opened=>opened?.evidence;
const exact=(actual,expected)=>Boolean(actual&&expected&&actual.sha256===expected.sha256&&actual.size===expected.size);
/** Idempotent recovery. Exact recorded DB evidence + exact authenticated authority
 * state are the only inputs. Deterministic failed/quarantine names make every
 * rename replayable; hooks are used only by hard-exit tests. */
async function recoverReplacement({journal,authority,validate,databasePath,fsyncDir,hooks={},nativeOpen=null,platform=process.platform,windowsReplacementOwner=null}){
 let i=await journal.read();if(!i)return {recovered:false};if(platform==='win32'&&!windowsReplacementOwner){const e=Error('Windows replacement recovery owner is unavailable');e.code='REPLACEMENT_TRANSACTION_UNAVAILABLE';throw e}const opened=[];const inspect=async file=>{const x=await evidence(file,validate,{nativeOpen,platform});if(x)opened.push(x);return x};const closeAllOpened=async()=>{let closeError=null;for(const item of opened.splice(0)){try{await item.close()}catch(error){closeError??=error}}if(closeError)throw closeError};try{
 if(path.resolve(databasePath)!==i.databasePath)throw Error('Replacement journal database mismatch');
 let primaryError=null;try{
 const live=await inspect(databasePath),old=await inspect(i.oldPath),failed=await inspect(i.failedPath),quarantine=await inspect(i.quarantinePath);if(fs.existsSync(i.capturePath))throw Error('Replacement capture residue remains');
 const liveOld=exact(value(live),i.oldEvidence),liveNew=exact(value(live),i.newEvidence),oldOld=exact(value(old),i.oldEvidence),failedNew=exact(value(failed),i.newEvidence),quarantineOld=exact(value(quarantine),i.oldEvidence);
 const oldAuthority=await authority.matches(i.authorityPre),newAuthority=i.authorityNew&&await authority.matches(i.authorityNew);
 if(!oldAuthority&&!newAuthority)throw Error('Replacement journal and credential authority disagree');
 if(i.phase==='intent'&&liveOld&&!old&&!failed&&!quarantine){if(fs.existsSync(i.stagingPath))fs.unlinkSync(i.stagingPath);i=await journal.update(i,{phase:'aborted-durable'});await journal.markTerminalVerified(i);return {recovered:true,outcome:'aborted-before-install',completedJournalRetained:true};}
 // Prefer rollback until the durable committed marker. During rollback, either
 // authority state is legal: DB is made exact-old first, then authority exact-old.
 const committedPhase=['committed','cleanup','cleanup-old-moved','cleanup-durable'].includes(i.phase);
 if(!committedPhase){
  if(live&&!liveOld&&!liveNew)throw Error('Replacement recovery live database is unknown');
  if(!live&&!oldOld&&!liveOld)throw Error('Replacement recovery old database is missing');
  if(liveNew&&!oldOld&&!failedNew)throw Error('Replacement recovery old database is missing');
  if(liveNew&&oldOld){if(failed)throw Error('Replacement failed evidence path already exists');if(platform==='win32')await closeAllOpened();if(platform==='win32')await windowsReplacementOwner.renameExact({action:'rollback-live-to-failed',databasePath,transitionId:i.transitionId,expected:i.newEvidence});else fs.renameSync(databasePath,i.failedPath);hooks.afterLiveToFailed?.();i=await journal.update(i,{phase:'rollback-live-moved'});}
  await live?.close();await old?.close();let nowLive=await inspect(databasePath),nowOld=await inspect(i.oldPath);
  if(!exact(value(nowLive),i.oldEvidence)){
   if(nowLive)throw Error('Replacement recovery refuses to overwrite live database');
   if(!exact(value(nowOld),i.oldEvidence))throw Error('Replacement recovery old database changed');
   if(platform==='win32')await closeAllOpened();
   if(platform==='win32')await windowsReplacementOwner.renameExact({action:'rollback-old-to-live',databasePath,transitionId:i.transitionId,expected:i.oldEvidence});else fs.renameSync(i.oldPath,databasePath);hooks.afterOldToLive?.();i=await journal.update(i,{phase:'rollback-old-live'});
  }
  await nowLive?.close();await nowOld?.close();const heldOldLive=await inspect(databasePath),heldFailed=fs.existsSync(i.failedPath)?await inspect(i.failedPath):null;if(!exact(value(heldOldLive),i.oldEvidence)||(heldFailed&&!exact(value(heldFailed),i.newEvidence)))throw Error('Replacement rollback evidence changed');await heldOldLive.assertExact(i.oldEvidence);if(heldFailed)await heldFailed.assertExact(i.newEvidence);
  await fsyncDir(path.dirname(databasePath));hooks.afterRollbackFsync?.();await heldOldLive.assertExact(i.oldEvidence);if(heldFailed)await heldFailed.assertExact(i.newEvidence);i=await journal.update(i,{phase:'rollback-db-durable'});
  await heldOldLive.assertExact(i.oldEvidence);if(!await authority.matches(i.authorityPre))await authority.restore(i.authorityPre);hooks.afterAuthorityRestore?.();await heldOldLive.assertExact(i.oldEvidence);
  if(!await authority.matches(i.authorityPre))throw Error('Credential authority rollback verification failed');
  hooks.beforeRollbackMarker?.();await heldOldLive.assertExact(i.oldEvidence);if(heldFailed)await heldFailed.assertExact(i.newEvidence);if(!await authority.matches(i.authorityPre))throw Error('Credential authority rollback verification failed');i=await journal.update(i,{phase:'rollback-durable'});hooks.afterRollbackMarker?.();if(fs.existsSync(i.stagingPath))fs.unlinkSync(i.stagingPath);await journal.markTerminalVerified(i);return {recovered:true,outcome:'rolled-back',completedJournalRetained:true};
 }
 // Committed cleanup accepts exactly one safe residue state: exact old at
 // oldPath, or exact old at the deterministic quarantine path after rename.
 if(!i.authorityNew||!newAuthority)throw Error('Committed replacement authority is invalid');
 if(!liveNew)throw Error('Replacement recovery committed database changed');
 if(failed||fs.existsSync(i.stagingPath)||fs.existsSync(i.capturePath))throw Error('Committed replacement has unexpected residue');
 const initial=oldOld&&!quarantine,renamed=!old&&quarantineOld;
 if(!initial&&!renamed)throw Error('Committed replacement old evidence is invalid');
 if(initial){if(platform==='win32')await closeAllOpened();if(platform==='win32')await windowsReplacementOwner.renameExact({action:'cleanup-old-to-quarantine',databasePath,transitionId:i.transitionId,expected:i.oldEvidence});else fs.renameSync(i.oldPath,i.quarantinePath);hooks.afterOldQuarantine?.();i=await journal.update(i,{phase:'cleanup-old-moved'});}
 if(platform==='win32')await closeAllOpened();else{await old?.close();await quarantine?.close()}let heldLive=await inspect(databasePath),q=await inspect(i.quarantinePath);if(!exact(value(heldLive),i.newEvidence)||!exact(value(q),i.oldEvidence)||!await authority.matches(i.authorityNew))throw Error('Committed replacement evidence changed');
 await fsyncDir(path.dirname(databasePath));hooks.afterQuarantineFsync?.();await heldLive.assertExact(i.newEvidence);await q.assertExact(i.oldEvidence);if(!await authority.matches(i.authorityNew))throw Error('Committed replacement authority changed');i=await journal.update(i,{phase:'cleanup-durable'});hooks.afterCleanupMarker?.();await heldLive.assertExact(i.newEvidence);await q.assertExact(i.oldEvidence);if(!await authority.matches(i.authorityNew))throw Error('Committed replacement authority changed');await journal.markTerminalVerified(i);return {recovered:true,outcome:'committed',completedJournalRetained:true};
}catch(error){primaryError=error;throw error}finally{try{await closeAllOpened()}catch(closeError){if(!primaryError)throw closeError}}}finally{}
}
module.exports={recoverReplacement};
