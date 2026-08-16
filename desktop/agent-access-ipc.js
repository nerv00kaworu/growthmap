'use strict';
const MAX_SAFE_ERROR=180;
function agentAccessIpcError(){const payload={status:0,code:'SIDECAR_REQUEST_FAILED',reason:null,detail:null},error=new Error(`GROWTHMAP_DESKTOP_ERROR:${JSON.stringify(payload)}`);error.code=payload.code;return error;}
async function agentAccessBoundary(operation,{diagnostic}={}){try{return await operation();}catch(error){if(diagnostic){const type=error&&typeof error==='object'&&typeof error.code==='string'&&/^[A-Z0-9_]{1,40}$/.test(error.code)?error.code:'ERROR';diagnostic(`type=${type}`.slice(0,MAX_SAFE_ERROR));}throw agentAccessIpcError();}}
function registerAgentAccessIpc({ipcMain,guard,getAgentAccess,diagnostic}){const methods={status:'status',enable:'enable',disable:'disable',copy:'copyConfig',download:'downloadConfig',test:'test',regenerate:'regenerate'};for(const [channel,method] of Object.entries(methods))ipcMain.handle(`agent-access:${channel}`,async(e,...args)=>{guard(e);return agentAccessBoundary(()=>getAgentAccess()[method](...args),{diagnostic});});}
module.exports={MAX_SAFE_ERROR,agentAccessIpcError,agentAccessBoundary,registerAgentAccessIpc};
