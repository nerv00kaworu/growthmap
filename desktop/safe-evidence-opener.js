'use strict';
function createSafeEvidenceOpener({platform=process.platform,windowsNativeOpen=null}={}){
 const available=platform!=='win32'||typeof windowsNativeOpen==='function';
 const assertAvailable=()=>{if(!available){const e=Error('Windows replacement recovery requires native opened-handle evidence');e.code='REPLACEMENT_EVIDENCE_UNAVAILABLE';throw e}};
 const open=platform==='win32'?async(...args)=>{assertAvailable();return windowsNativeOpen(...args)}:null;
 return {available,assertAvailable,open};
}
module.exports={createSafeEvidenceOpener};
