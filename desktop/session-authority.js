'use strict';
const crypto=require('node:crypto');
function createSessionAuthority(randomBytes=crypto.randomBytes){
 let token='';
 return Object.freeze({
  rotate(){token=randomBytes(32).toString('base64url');return token;},
  current(){if(!token)throw new Error('Desktop session is not initialized');return token;},
 });
}
module.exports={createSessionAuthority};
