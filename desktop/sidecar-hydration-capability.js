'use strict';
const crypto=require('node:crypto');
function createHydrationCapability(writable,randomBytes=crypto.randomBytes){return writable?randomBytes(32).toString('base64url'):''}
module.exports={createHydrationCapability};
