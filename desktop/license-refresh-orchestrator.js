'use strict';
const {refreshActivationCertificate,verifyRefreshedCertificate,shouldRefresh,hasInstalledCertificateCapability,hasVerifiedCandidateCapability}=require('./activation-refresh');
function refreshGate({entitlement,installed,installedCapability,revocationState,freshnessState,flowKind}){if(!hasInstalledCertificateCapability(installedCapability,installed,entitlement))return false;if(revocationState!=='none'||!flowKind||freshnessState?.invalid||freshnessState?.licenseId!==entitlement.license_id)return false;return ['paid','check_in_required'].includes(entitlement.state==='paid'?'paid':entitlement.reason)&&shouldRefresh(installed);}
async function reconcileFailure(provenance,readInstalled){try{const actual=await readInstalled();provenance.reconcile(actual);}catch{/* Preserve pending evidence when stable read/reconciliation is ambiguous. */}}
async function refreshIfEligible(options){
 if(!refreshGate(options))return {state:'skipped'};
 const checkpoint=()=>{if(!hasInstalledCertificateCapability(options.installedCapability,options.installed,options.entitlement))throw Error('The current certificate changed during refresh');};
 const received=await refreshActivationCertificate({certificate:options.installed,entitlement:options.entitlement,installedCapability:options.installedCapability,checkpoint,flowKind:options.flowKind,activationApiOrigin:options.activationApiOrigin,deviceIdentity:options.deviceIdentity,fetchImpl:options.fetchImpl});
 checkpoint();
 const candidate=verifyRefreshedCertificate({installedCapability:options.installedCapability,certificate:options.installed,entitlement:options.entitlement,candidate:received,deviceIdentity:options.deviceIdentity,authorityPublicKeyPem:options.authorityPublicKeyPem,now:options.now});
 const candidateCheckpoint=()=>{checkpoint();if(!hasVerifiedCandidateCapability(candidate,received))throw Error('The refreshed certificate changed during the transaction');};
 candidateCheckpoint();
 if(!options.provenance||typeof options.readInstalled!=='function')throw Error('Refresh transaction protection is missing');
 try{options.provenance.begin(candidate,options.flowKind);candidateCheckpoint();await options.importCertificate(candidate);candidateCheckpoint();options.provenance.promote(candidate);candidateCheckpoint();}catch(error){await reconcileFailure(options.provenance,options.readInstalled);throw error;}
 return {state:'refreshed',certificate:candidate};
}
async function installActivatedCertificate({certificate,flowKind,provenance,verify,importCertificate,readInstalled}){
 const source=certificate,verified=verify(source);
 const checkpoint=()=>{if(!hasVerifiedCandidateCapability(verified,source))throw Error('The activation certificate changed during the transaction');};
 try{checkpoint();if(!provenance||typeof readInstalled!=='function')throw Error('Activation transaction protection is missing');provenance.begin(verified,flowKind);checkpoint();await importCertificate(verified);checkpoint();provenance.promote(verified);checkpoint();}catch(error){await reconcileFailure(provenance,readInstalled);throw error;}
 return verified;
}
module.exports={refreshGate,refreshIfEligible,installActivatedCertificate};
