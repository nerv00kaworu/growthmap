'use strict';
const DEFAULT_SIDECAR_READY_TIMEOUT_MS=60000;
const DEFAULT_SIDECAR_READY_POLL_MS=150;
function waitForSidecarReady({child,probe,timeoutMs=DEFAULT_SIDECAR_READY_TIMEOUT_MS,pollIntervalMs=DEFAULT_SIDECAR_READY_POLL_MS,now=Date.now,setTimer=setTimeout,clearTimer=clearTimeout,diagnosticDetail=()=>''}){
 if(!child||typeof child.once!=='function'||typeof probe!=='function')throw new TypeError('Sidecar readiness requires a child and probe');
 if(!Number.isFinite(timeoutMs)||timeoutMs<=0||!Number.isFinite(pollIntervalMs)||pollIntervalMs<=0)throw new RangeError('Sidecar readiness timing must be positive and bounded');
 return new Promise((resolve,reject)=>{
  let settled=false,pollTimer=null,deadlineTimer=null;const deadline=now()+timeoutMs;
  const onExit=(code,signal)=>fail(`GrowthMap sidecar exited before readiness (code=${code}, signal=${signal||'none'})`);
  const onError=()=>fail('GrowthMap sidecar could not be started');
  const cleanup=()=>{if(pollTimer!==null)clearTimer(pollTimer);clearTimer(deadlineTimer);child.removeListener('exit',onExit);child.removeListener('error',onError);};
  const finish=fn=>value=>{if(settled)return;settled=true;cleanup();fn(value);};
  const succeed=finish(resolve),rejectOnce=finish(reject);
  const fail=message=>rejectOnce(new Error(`${message}${diagnosticDetail()||''}`));
  deadlineTimer=setTimer(()=>fail('GrowthMap sidecar readiness timed out'),timeoutMs);
  const poll=async()=>{if(settled)return;try{await probe();succeed();}catch{if(settled)return;const remaining=deadline-now();if(remaining<=0)return fail('GrowthMap sidecar readiness timed out');pollTimer=setTimer(poll,Math.min(pollIntervalMs,remaining));}};
  child.once('exit',onExit);child.once('error',onError);
  if(child.exitCode!==null&&child.exitCode!==undefined||child.signalCode!==null&&child.signalCode!==undefined)onExit(child.exitCode,child.signalCode);
  else poll();
 });
}
module.exports={waitForSidecarReady,DEFAULT_SIDECAR_READY_TIMEOUT_MS,DEFAULT_SIDECAR_READY_POLL_MS};
