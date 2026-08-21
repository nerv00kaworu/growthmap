'use strict';
/** Behavioral seam shared by initial startup and replacement restart. */
async function hydrateAndSeal({writable,store,getCapability,seal}){
 if(!writable)return {hydrated:false,sealed:false};
 await store.hydrate();
 await seal(getCapability());
 return {hydrated:true,sealed:true};
}
async function restartHydration({prepare,store,getCapability,seal,reload}){
 const prepared=await prepare();
 await store.reconcile();
 await hydrateAndSeal({writable:prepared.policy.writable,store,getCapability,seal});
 await reload();
 return prepared;
}
function createAttemptLifecycle({writable,newCapability,setCurrent}){
 return {begin(){const capability=writable?newCapability():'';setCurrent(capability);return capability},failed(){setCurrent('')}};
}
async function runSidecarAttempts({attempts=3,writable,newCapability,spawn,ready,setCurrent,cleanup}){
 const lifecycle=createAttemptLifecycle({writable,newCapability,setCurrent});
 for(let attempt=1;attempt<=attempts;attempt++){
  const capability=lifecycle.begin();
  const child=await spawn({attempt,capability});
  try{await ready(child,{attempt,capability});return {child,capability,attempt}}
  catch(error){await cleanup(child);lifecycle.failed();if(attempt===attempts)throw error}
 }
}
module.exports={hydrateAndSeal,restartHydration,createAttemptLifecycle,runSidecarAttempts};
