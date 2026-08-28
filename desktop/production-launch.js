'use strict';
const {runCredentialStartup}=require('./credential-startup');
/** Production launch barrier. IPC is the commit point and is unreachable until the
 * sidecar has created/verified the DB, authority is bound, and credentials have
 * reconciled, hydrated, and sealed. Dependencies are explicit test/DI seams. */
async function completeProductionLaunch({prepare,hasStore,bind,makeStore,hydrateAndSeal,enable}){
 const prepared=await prepare();
 let transition=null,store=hasStore();
 try{
  if(!store){transition=await bind();store=await makeStore()}
  await runCredentialStartup({store,hydrate:()=>hydrateAndSeal(prepared,store),enable:()=>enable(store)});
  await transition?.commit?.();
  return {prepared,store};
 }catch(error){
  try{await transition?.rollback?.()}catch(rollbackError){throw new AggregateError([error,rollbackError],'Launch and authority rollback both failed')}
  throw error;
 }
}
module.exports={completeProductionLaunch};
