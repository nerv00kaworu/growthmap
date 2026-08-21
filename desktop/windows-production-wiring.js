'use strict';
const {createWindowsNativeBroker}=require('./windows-native-broker');
const {createWindowsNativeOpen}=require('./windows-native-evidence');
const {createWindowsReplacementOwner}=require('./windows-native-replacement');

function createWindowsProductionWiring({
 platform=process.platform,
 createBroker=createWindowsNativeBroker,
 createNativeOpen=createWindowsNativeOpen,
 createReplacementOwner=createWindowsReplacementOwner,
}={}){
 if(platform!=='win32')return Object.freeze({broker:null,nativeOpen:null,windowsReplacementOwner:null,assertAvailable:async()=>{}});
 // Production deliberately supplies no broker fault/crash hooks or payload extensions.
 const broker=createBroker();
 const nativeOpen=createNativeOpen({broker});
 const windowsReplacementOwner=createReplacementOwner({broker});
 return Object.freeze({broker,nativeOpen,windowsReplacementOwner,assertAvailable:async()=>{await broker.start();}});
}

function createOrderlyShutdown({lifecycle,getDatabaseManager,getMainWindow,broker=null,quit}){
 let shutdownPromise=null;
 return function orderlyShutdown(){
  if(shutdownPromise)return shutdownPromise;
  lifecycle.beginShutdown();
  shutdownPromise=(async()=>{
   const errors=[];
   try{const manager=getDatabaseManager();if(manager?.busy)await manager.awaitIdle();}catch(error){errors.push(error)}
   try{await lifecycle.shutdown(()=>{const window=getMainWindow();if(window&&!window.isDestroyed())window.destroy();});}catch(error){errors.push(error)}
   try{if(broker)await broker.close();}catch(error){errors.push(error)}
   if(errors.length===1)throw errors[0];
   if(errors.length>1)throw new AggregateError(errors,'GrowthMap orderly shutdown failed');
  })().finally(()=>quit());
  return shutdownPromise;
 };
}

module.exports={createWindowsProductionWiring,createOrderlyShutdown};
