'use strict';
const net=require('node:net');

function forbiddenPublicLiteralHost(hostname){
 const host=String(hostname).toLowerCase().replace(/^\[|\]$/g,'');
 return net.isIP(host)!==0;
}
function strictCanonicalPublicHttpsOrigin(value){
 if(typeof value!=='string')throw new Error('Public HTTPS origin is invalid');
 let url;try{url=new URL(value);}catch{throw new Error('Public HTTPS origin is invalid');}
 if(url.protocol!=='https:'||url.username||url.password||url.pathname!=='/'||url.search||url.hash||url.hostname.endsWith('.')||forbiddenPublicLiteralHost(url.hostname)||url.origin!==value)throw new Error('Public HTTPS origin must be canonical and use a public host');
 return url.origin;
}
function validatePurchasePortalUrl(value,configuredOrigin){
 const origin=strictCanonicalPublicHttpsOrigin(configuredOrigin);
 let url;try{url=new URL(value);}catch{throw new Error('Purchase portal URL is invalid');}
 if(url.protocol!=='https:'||url.origin!==origin||url.username||url.password||url.search||url.hash||url.hostname.endsWith('.')||forbiddenPublicLiteralHost(url.hostname)||url.href!==value)throw new Error('Purchase portal must be an exact query-free HTTPS URL on the reviewed public origin');
 return url.href;
}
function purchasePortalTarget(value,configuredOrigin){return validatePurchasePortalUrl(value,configuredOrigin);}
function purchaseTargetForArgs(args,config,validPaypalUrl){
 if(!Array.isArray(args)||args.length!==1)throw new Error('Purchase request has invalid arguments');
 const rail=args[0];
 if(typeof rail!=='string')throw new Error('Purchase request is not configured for this build');
 if(rail==='x402')return purchasePortalTarget(config.purchasePortalUrl,config.purchasePortalOrigin);
 if(rail==='paypal'&&validPaypalUrl(config.paypalUrl))return config.paypalUrl;
 throw new Error('Purchase request is not configured for this build');
}
module.exports={forbiddenPublicLiteralHost,strictCanonicalPublicHttpsOrigin,validatePurchasePortalUrl,purchasePortalTarget,purchaseTargetForArgs};
