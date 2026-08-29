'use strict';
/** Behavioral seam shared by initial startup and replacement restart. */
async function hydrateAndSeal({writable,store,getCapability,seal}){
 if(!writable)return {hydrated:false,sealed:false};
 await store.hydrate();
 await seal(getCapability());
 return {hydrated:true,sealed:true};
}
async function restartHydration({prepare,store,getCapability,seal,reload,reportStage=()=>{}}){
 const report=name=>{try{reportStage(name)}catch{}};
 let prepared;report('replacement-restart-prepare-enter');
 try{prepared=await prepare();report('replacement-restart-prepare-ready')}catch(error){report('replacement-restart-failed-prepare');throw error}
 try{await store.reconcile();report('replacement-restart-reconcile-ready')}catch(error){report('replacement-restart-failed-reconcile');throw error}
 if(prepared.policy.writable){
  try{await store.hydrate();report('replacement-restart-hydrate-ready')}catch(error){report('replacement-restart-failed-hydrate');throw error}
  try{await seal(getCapability());report('replacement-restart-seal-ready')}catch(error){report('replacement-restart-failed-seal');throw error}
 }
 try{await reload();report('replacement-restart-reload-ready')}catch(error){report('replacement-restart-failed-reload');throw error}
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
