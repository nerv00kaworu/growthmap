'use strict';
function createActivationRelaunchScheduler({schedule=setImmediate,relaunch,shutdown,diagnostic=()=>{}}){
 if(typeof schedule!=='function'||typeof relaunch!=='function'||typeof shutdown!=='function'||typeof diagnostic!=='function')throw new TypeError('Activation relaunch dependencies are required');
 let scheduled=false;
 const report=kind=>{try{diagnostic(kind);}catch{/* Diagnostics must never disrupt activation or shutdown. */}};
 return result=>{
  if(!scheduled){
   scheduled=true;
   schedule(()=>{
    try{relaunch();}catch{report('relaunch-failed');}
    try{Promise.resolve(shutdown()).catch(()=>report('shutdown-failed'));}catch{report('shutdown-failed');}
   });
  }
  return result;
 };
}
module.exports={createActivationRelaunchScheduler};
