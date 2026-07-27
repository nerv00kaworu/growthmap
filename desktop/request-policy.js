'use strict';
function origin(url){try{return new URL(url).origin;}catch{return '';}}
function createRequestPolicy({getBaseUrl,token,csp}){
 function before(details){if(origin(details.url)!==getBaseUrl())return {cancel:true};return {requestHeaders:{...(details.requestHeaders||{}),Authorization:`Bearer ${token}`}};}
 function headers(details){if(origin(details.url)!==getBaseUrl())return {cancel:true};return {responseHeaders:{...(details.responseHeaders||{}),'Content-Security-Policy':[csp]}};}
 return {filter:{urls:['http://127.0.0.1:*/*']},before,headers};
}
module.exports={createRequestPolicy,origin};
