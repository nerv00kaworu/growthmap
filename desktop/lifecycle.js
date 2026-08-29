'use strict';
const {spawn:defaultSpawn}=require('node:child_process');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function exited(child){return !child||child.exitCode!==null||child.signalCode!==null;}
function waitForExit(child,ms){if(exited(child))return Promise.resolve(true);return new Promise(resolve=>{let done=false;const finish=value=>{if(done)return;done=true;clearTimeout(timer);child.removeListener('exit',onExit);resolve(value);};const onExit=()=>finish(true);const timer=setTimeout(()=>finish(false),ms);child.once('exit',onExit);});}
function signalTree(child,signal,platform,spawn=defaultSpawn){if(exited(child))return;if(platform==='win32'){spawn('taskkill',['/PID',String(child.pid),'/T','/F'],{stdio:'ignore',windowsHide:true}).once('error',()=>{});return;}try{process.kill(-child.pid,signal);}catch{try{child.kill(signal);}catch{}}}
function killWindowsTree(child,spawn=defaultSpawn,ms=10000){return new Promise(resolve=>{if(!child||!child.pid)return resolve();let done=false;const finish=()=>{if(done)return;done=true;clearTimeout(timer);resolve();};const killer=spawn('taskkill',['/PID',String(child.pid),'/T','/F'],{stdio:'ignore',windowsHide:true});const timer=setTimeout(finish,ms);killer.once('error',finish);killer.once('exit',finish);});}
function createLifecycle({platform=process.platform,spawn=defaultSpawn,graceMs=2500,killMs=1500}={}){
 let child=null,shuttingDown=false,shutdownPromise=null,acceptingIpc=true;const expectedExits=new WeakSet();
 function attach(next){if(shuttingDown)throw new Error('Application is shutting down');child=next;return next;}
 async function cleanup(target=child){if(target)expectedExits.add(target);if(!target){if(target===child)child=null;return;}if(platform==='win32'){
   // PyInstaller one-file uses a bootloader parent plus an application child. Killing
   // only the parent can orphan the child and leave the SQLite file locked.
   await killWindowsTree(target,spawn,graceMs+killMs);
   await waitForExit(target,killMs);
 }else if(!exited(target)){
   signalTree(target,'SIGTERM',platform,spawn);
   if(!await waitForExit(target,graceMs)){signalTree(target,'SIGKILL',platform,spawn);await waitForExit(target,killMs);}
 }
 if(target===child)child=null;
 }
 function beginShutdown(){shuttingDown=true;acceptingIpc=false;}
 function shutdown(closeWindows=()=>{}){if(shutdownPromise)return shutdownPromise;beginShutdown();shutdownPromise=(async()=>{closeWindows();await cleanup();})();return shutdownPromise;}
 return {attach,cleanup,beginShutdown,shutdown,isExpectedExit:target=>expectedExits.has(target),get child(){return child;},get shuttingDown(){return shuttingDown;},get acceptingIpc(){return acceptingIpc;}};
}
let isolatedE2EDiagnostics=false,isolatedE2EReporter=()=>{};
function enableIsolatedE2EDiagnostics(reportStage=()=>{}){isolatedE2EDiagnostics=true;isolatedE2EReporter=typeof reportStage==='function'?reportStage:()=>{};}
function reportIsolatedE2EStage(name){try{isolatedE2EReporter(name)}catch{}}
function sidecarSpawnOptions(platform=process.platform){return {detached:platform!=='win32',windowsHide:true,stdio:isolatedE2EDiagnostics?['ignore','ignore','pipe']:['ignore','ignore','ignore']};}
function probeSpawnOptions(platform=process.platform){return {...sidecarSpawnOptions(platform),stdio:['ignore','pipe','pipe']};}
module.exports={createLifecycle,sidecarSpawnOptions,probeSpawnOptions,enableIsolatedE2EDiagnostics,reportIsolatedE2EStage,waitForExit,signalTree,killWindowsTree,delay};
