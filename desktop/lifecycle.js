'use strict';
const {spawn:defaultSpawn}=require('node:child_process');
const {spawnTrustedTaskkill}=require('./trusted-taskkill');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function exited(child){return !child||child.exitCode!==null||child.signalCode!==null;}
function waitForExit(child,ms){if(exited(child))return Promise.resolve(true);return new Promise(resolve=>{let done=false;const finish=value=>{if(done)return;done=true;clearTimeout(timer);child.removeListener('exit',onExit);resolve(value);};const onExit=()=>finish(true);const timer=setTimeout(()=>finish(false),ms);child.once('exit',onExit);});}
function signalTree(child,signal,platform,spawn=defaultSpawn,env=process.env){if(exited(child))return;if(platform==='win32'){try{spawnTrustedTaskkill(child.pid,{spawn,env}).once('error',()=>{})}catch{}return;}try{process.kill(-child.pid,signal);}catch{try{child.kill(signal);}catch{}}}
function killWindowsTree(child,spawn=defaultSpawn,ms=10000,env=process.env){return new Promise(resolve=>{if(!child||!child.pid)return resolve(false);let done=false,timer=null;const finish=value=>{if(done)return;done=true;if(timer)clearTimeout(timer);resolve(value);};let killer;try{killer=spawnTrustedTaskkill(child.pid,{spawn,env})}catch{return finish(false)}timer=setTimeout(()=>finish(false),ms);killer.once('error',()=>finish(false));killer.once('exit',code=>finish(code===0));});}
function createLifecycle({platform=process.platform,spawn=defaultSpawn,env=process.env,graceMs=2500,killMs=1500}={}){
 let child=null,shuttingDown=false,shutdownPromise=null,acceptingIpc=true;const expectedExits=new WeakSet();
 function attach(next){if(shuttingDown)throw new Error('Application is shutting down');child=next;return next;}
 async function cleanup(target=child,{confirmed=false}={}){if(target)expectedExits.add(target);if(!target){if(target===child)child=null;return true;}if(exited(target)){if(target===child)child=null;return true}let stopped=true;if(platform==='win32'){
   // PyInstaller one-file has a bootloader parent plus an application child, so use
   // taskkill's process-tree mode and separately confirm the tracked parent exit.
   const treeKilled=await killWindowsTree(target,spawn,graceMs+killMs,env),parentExited=await waitForExit(target,killMs);stopped=treeKilled&&parentExited;
 }else if(!exited(target)){
   signalTree(target,'SIGTERM',platform,spawn);
   if(!await waitForExit(target,graceMs)){signalTree(target,'SIGKILL',platform,spawn);stopped=await waitForExit(target,killMs);}
 }
 if(!stopped&&confirmed){const error=Error('Sidecar process-tree exit was not confirmed');error.code='SIDECAR_STOP_UNCONFIRMED';throw error}if(target===child&&(stopped||!confirmed))child=null;return stopped;
 }
 const cleanupConfirmed=target=>cleanup(target,{confirmed:true});
 function beginShutdown(){shuttingDown=true;acceptingIpc=false;}
 function shutdown(closeWindows=()=>{}){if(shutdownPromise)return shutdownPromise;beginShutdown();shutdownPromise=(async()=>{closeWindows();await cleanup();})();return shutdownPromise;}
 return {attach,cleanup,cleanupConfirmed,beginShutdown,shutdown,isExpectedExit:target=>expectedExits.has(target),get child(){return child;},get shuttingDown(){return shuttingDown;},get acceptingIpc(){return acceptingIpc;}};
}
let isolatedE2EDiagnostics=false,isolatedE2EReporter=()=>{};
function enableIsolatedE2EDiagnostics(reportStage=()=>{}){isolatedE2EDiagnostics=true;isolatedE2EReporter=typeof reportStage==='function'?reportStage:()=>{};}
function reportIsolatedE2EStage(name){try{isolatedE2EReporter(name)}catch{}}
function sidecarSpawnOptions(platform=process.platform){return {detached:platform!=='win32',windowsHide:true,stdio:isolatedE2EDiagnostics?['ignore','ignore','pipe']:['ignore','ignore','ignore']};}
function probeSpawnOptions(platform=process.platform){return {...sidecarSpawnOptions(platform),stdio:['ignore','pipe','pipe']};}
module.exports={createLifecycle,sidecarSpawnOptions,probeSpawnOptions,enableIsolatedE2EDiagnostics,reportIsolatedE2EStage,waitForExit,signalTree,killWindowsTree,delay};
