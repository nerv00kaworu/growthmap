'use strict';
function authenticatedFresh(entitlement){return entitlement?.state==='free'&&entitlement.edition==='free'&&entitlement.valid===true&&entitlement.mutations_allowed===true&&entitlement.reason==='authenticated_fresh_install'&&entitlement.max_active_projects===1&&entitlement.license_id===null;}
function decideStartup({trialMode,entitlement}){if(entitlement?.state==='paid'&&entitlement.valid&&entitlement.mutations_allowed)return {mode:'paid',writable:true};if(trialMode==='existing'&&entitlement?.state==='free'&&entitlement.mutations_allowed)return {mode:'free',writable:true};if(trialMode==='fresh'&&authenticatedFresh(entitlement))return {mode:'fresh',writable:true};return {mode:'extraction',writable:false};}
module.exports={decideStartup};
