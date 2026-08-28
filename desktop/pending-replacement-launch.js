'use strict';
async function recoverPendingReplacementAtLaunch({pending,evidencePolicy,recover,activateAuthority,hydrate,startSidecar,enableIpc}){
 if(!pending)return {recovered:false};await evidencePolicy.assertAvailable();const result=await recover();if(activateAuthority)await activateAuthority();if(hydrate)await hydrate();else if(startSidecar)await startSidecar();if(enableIpc)await enableIpc();return result;
}
module.exports={recoverPendingReplacementAtLaunch};
