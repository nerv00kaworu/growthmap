'use strict';
function decideStartup({trialMode,entitlement}){if(entitlement?.state==='paid'&&entitlement.valid&&entitlement.mutations_allowed)return {mode:'paid',writable:true};if(trialMode==='existing'&&entitlement?.state==='trial'&&entitlement.mutations_allowed)return {mode:'trial',writable:true};if(trialMode==='fresh'&&!entitlement?.valid)return {mode:'fresh',writable:true};return {mode:'extraction',writable:false};}
module.exports={decideStartup};
