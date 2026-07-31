'use strict';
const crypto=require('node:crypto');
function createSessionAuthority(randomBytes=crypto.randomBytes){
 let current='',pending='',generation=0;
 return Object.freeze({
  begin(){pending=randomBytes(32).toString('base64url');generation++;return Object.freeze({token:pending,generation});},
  commit(candidate){if(!candidate||candidate.generation!==generation||candidate.token!==pending)throw new Error('Desktop session candidate is stale');current=pending;pending='';return current;},
  invalidate(candidate){if(!candidate||candidate.generation===generation){current='';pending='';generation++;}},
  current(){if(!current)throw new Error('Desktop session is not initialized');return current;},
  candidate(candidate){if(!candidate||candidate.generation!==generation||candidate.token!==pending)throw new Error('Desktop session candidate is stale');return pending;},
 });
}
module.exports={createSessionAuthority};
