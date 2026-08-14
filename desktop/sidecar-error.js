'use strict';
const MAX_ERROR_BYTES=65536;
const STATUSES=new Set([400,401,403,404,409,413,422,429,500,502,503,504]);
const CODES=new Set(['AUTH_REQUIRED','BRANCH_MISMATCH','CANONICAL_WRITE_CONFLICT','CYCLIC_BATCH_DEPENDENCY','ENTITLEMENT_READ_ONLY','GRANT_INACTIVE','HUMAN_AUTH_REQUIRED','HUMAN_CONTROL_DISABLED','IDEMPOTENCY_MISMATCH','ID_CONFLICT','INACTIVE_BRANCH','INVALID_BRANCH','INVALID_REFERENCE','INVALID_SOURCE','INVALID_SUBTREE','INVALID_TOKEN','LOCALHOST_ONLY','ORIGIN_DENIED','PERMISSION_DENIED','RATE_LIMITED','REVISION_CONFLICT','SCOPE_DENIED','SCOPE_TOO_LARGE','TOKEN_QUERY_FORBIDDEN']);
const REASONS=new Set(['check_in_required','clock_rollback','corrupt_free_state','corrupt_license','device_binding_unsupported','device_identity_missing','electron_forced_extraction','expired','invalid_activation_id','invalid_certificate_type','invalid_device_allowance','invalid_device_binding','invalid_document','invalid_edition','invalid_expiry','invalid_issued_at','invalid_license_id','invalid_limit','invalid_public_key','invalid_revocation','invalid_signature','legacy_bootstrap_required','major_mismatch','no_free_state','placeholder_public_key','prior_installation_evidence','prior_installation_evidence_invalid','revocation_state_invalid','revoked','startup_policy_mismatch','startup_verdict_invalid','unsupported_schema','update_recovery','wrong_device']);
function safeEnvelope(status,body,{oversize=false}={}){
 let parsed=null;if(!oversize&&Buffer.byteLength(body||'','utf8')<=MAX_ERROR_BYTES)try{parsed=JSON.parse(body)}catch{}
 const nested=parsed&&typeof parsed==='object'&&parsed.detail&&typeof parsed.detail==='object'&&!Array.isArray(parsed.detail)?parsed.detail:null;
 const source=nested||((parsed&&typeof parsed==='object'&&!Array.isArray(parsed))?parsed:{});
 return {status:STATUSES.has(Number(status))?Number(status):0,code:CODES.has(source.code)?source.code:'SIDECAR_REQUEST_FAILED',reason:REASONS.has(source.reason)?source.reason:null,detail:null};
}
function errorFromResponse(status,body,options){const payload=safeEnvelope(status,body,options),error=new Error(`GROWTHMAP_DESKTOP_ERROR:${JSON.stringify(payload)}`);error.statusCode=payload.status;error.code=payload.code;error.reason=payload.reason;return error;}
function unavailableError(){return new Error('GROWTHMAP_DESKTOP_ERROR:{"status":0,"code":"SIDECAR_UNAVAILABLE","reason":null,"detail":null}');}
function readResponse(response){
 const success=response.statusCode>=200&&response.statusCode<300;
 return new Promise((resolve,reject)=>{let chunks=[],size=0,oversize=false;
  response.on('data',chunk=>{const buffer=Buffer.isBuffer(chunk)?chunk:Buffer.from(chunk);if(success){chunks.push(buffer);size+=buffer.length;return;}if(oversize)return;if(size+buffer.length>MAX_ERROR_BYTES){oversize=true;chunks=[];size=0;return;}chunks.push(buffer);size+=buffer.length;});
  response.on('end',()=>{const body=oversize?'':Buffer.concat(chunks,size).toString('utf8');if(success)return resolve(body);reject(errorFromResponse(response.statusCode,body,{oversize}));});
  response.on('error',()=>reject(unavailableError()));
 });
}
module.exports={MAX_ERROR_BYTES,safeEnvelope,errorFromResponse,unavailableError,readResponse};
