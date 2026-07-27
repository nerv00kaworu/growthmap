'use strict';
const {spawn:defaultSpawn}=require('node:child_process');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function exited(child){return !child||child.exitCode!==null||child.signalCode!==null;}
function waitForExit(child,ms){if(exited(child))return Promise.resolve(true);return new Promise(resolve=>{let done=false;const finish=value=>{if(done)return;done=true;clearTimeout(timer);child.removeListener('exit',onExit);resolve(value);};const onExit=()=>finish(true);const timer=setTimeout(()=>finish(false),ms);child.once('exit',onExit);});}
function signalTree(child,signal,platform,spawn=defaultSpawn){if(exited(child))return;if(platform==='win32'){spawn('taskkill',['/PID',String(child.pid),'/T','/F'],{stdio:'ignore',windowsHide:true}).once('error',()=>{});return;}try{process.kill(-child.pid,signal);}catch{try{child.kill(signal);}catch{}}}
function createLifecycle({platform=process.platform,spawn=defaultSpawn,graceMs=2500,killMs=1500}={}){
 let child=null,shuttingDown=false,shutdownPromise=null,acceptingIpc=true;const expectedExits=new WeakSet();
 function attach(next){if(shuttingDown)throw new Error('Application is shutting down');child=next;return next;}
 async function cleanup(target=child){if(target)expectedExits.add(target);if(!target||exited(target)){if(target===child)child=null;return;}if(platform==='win32'){
   // Windows has no reliable graceful process-tree signal; request normal child termination first.
   try{target.kill();}catch{}
 }else signalTree(target,'SIGTERM',platform,spawn);
 if(!await waitForExit(target,graceMs)){signalTree(target,'SIGKILL',platform,spawn);await waitForExit(target,killMs);}
 if(target===child)child=null;
 }
 function shutdown(closeWindows=()=>{}){if(shutdownPromise)return shutdownPromise;shuttingDown=true;acceptingIpc=false;shutdownPromise=(async()=>{closeWindows();await cleanup();})();return shutdownPromise;}
 return {attach,cleanup,shutdown,isExpectedExit:target=>expectedExits.has(target),get child(){return child;},get shuttingDown(){return shuttingDown;},get acceptingIpc(){return acceptingIpc;}};
}
function spawnOptions(platform=process.platform){return {detached:platform!=='win32',windowsHide:true,stdio:['ignore','ignore','ignore']};}
module.exports={createLifecycle,spawnOptions,waitForExit,signalTree,delay};
