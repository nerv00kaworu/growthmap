'use strict';
/** Production launch barrier. IPC is the commit point and is unreachable until the
 * sidecar has created/verified the DB, authority is bound, and credentials have
 * reconciled, hydrated, and sealed. Dependencies are explicit test/DI seams. */
const diagnosticOperations=new Set(['secure-path-policy','secure-read-file','initialize-private-acl']);
const diagnosticStages=new Set(['timeout','closed','aborted','socket','protocol','bounds','response-schema','request','request-schema','request-path','request-boundary','response-schema-policy','response-schema-policy-container','response-schema-policy-item','response-schema-policy-path','response-schema-policy-identity','response-schema-read','response-schema-initialize','cleanup-unconfirmed','remote','remote-state','remote-target','remote-acl','remote-path','remote-boundary','remote-identity','remote-final','remote-named','remote-owner','remote-reparse','remote-network','remote-unsafe']);
function diagnosticValue(value,key){try{if(value===null||!['object','function'].includes(typeof value))return;const descriptor=Object.getOwnPropertyDescriptor(value,key),candidate=descriptor&&Object.prototype.hasOwnProperty.call(descriptor,'value')&&typeof descriptor.value==='string'?descriptor.value:undefined,allowed=key==='nativeOperation'?diagnosticOperations:key==='stage'?diagnosticStages:null;if(candidate&&allowed?.has(candidate))return candidate}catch{}}
async function completeProductionLaunch({prepare,hasStore,bind,makeStore,hydrateAndSeal,enable}){
 let stage='prepare',prepared=null,transition=null,store=null;
 try{
  prepared=await prepare();store=hasStore();
  if(!store){stage='bind';transition=await bind();stage='store';store=await makeStore()}
  stage='reconcile';await store.reconcile();
  stage='hydrate';await hydrateAndSeal(prepared,store);
  stage='enable';await enable(store);
  stage='commit';await transition?.commit?.();
  return {prepared,store};
 }catch(error){
  let rollbackError=null;try{await transition?.rollback?.()}catch(caught){rollbackError=caught}
  const failure=new Error('Production launch barrier failed');Object.defineProperties(failure,{launchBarrierStage:{value:stage},nativeOperation:{value:diagnosticValue(error,'nativeOperation')},stage:{value:diagnosticValue(error,'stage')}});
  if(rollbackError){const rollbackOperation=diagnosticValue(rollbackError,'nativeOperation'),rollbackStage=diagnosticValue(rollbackError,'stage'),rollbackFailure=new Error('Authority rollback failed');Object.defineProperties(rollbackFailure,{nativeOperation:{value:rollbackOperation},stage:{value:rollbackStage}});const aggregate=new AggregateError([failure,rollbackFailure],'Launch and authority rollback both failed');Object.defineProperties(aggregate,{launchBarrierStage:{value:stage},rollbackNativeOperation:{value:rollbackOperation},rollbackNativeStage:{value:rollbackStage}});throw aggregate}
  throw failure;
 }
}
module.exports={completeProductionLaunch};
