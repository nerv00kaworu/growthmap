'use strict';
function origin(url){try{return new URL(url).origin;}catch{return '';}}
const PRIVATE_HEADER='X-GrowthMap-Hydration-Capability';
function createRequestPolicy({getBaseUrl,token,csp}){
 function before(details){if(origin(details.url)!==getBaseUrl())return {cancel:true};const requestHeaders={...(details.requestHeaders||{})};for(const key of Object.keys(requestHeaders))if(key.toLowerCase()===PRIVATE_HEADER.toLowerCase())delete requestHeaders[key];return {requestHeaders:{...requestHeaders,Authorization:`Bearer ${token}`}};}
 function headers(details){if(origin(details.url)!==getBaseUrl())return {cancel:true};return {responseHeaders:{...(details.responseHeaders||{}),'Content-Security-Policy':[csp]}};}
 return {filter:{urls:['http://127.0.0.1:*/*']},before,headers};
}
module.exports={createRequestPolicy,origin,PRIVATE_HEADER};
