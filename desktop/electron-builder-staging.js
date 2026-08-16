'use strict';
// Explicitly unsigned, non-publishable package for production-like Gift staging only.
// The workflow materializes both generated inputs under RUNNER_TEMP and supplies
// absolute paths. They are never copied back into the source tree.
const path=require('node:path');
const base=require('./package.json').build;
function required(name){const value=process.env[name];if(!value||!path.isAbsolute(value))throw Error(`${name} absolute generated staging input is required`);return value;}
const config=required('GROWTHMAP_STAGING_PUBLIC_CONFIG');
const publicKey=required('GROWTHMAP_STAGING_LICENSE_PUBLIC_KEY');
module.exports={
 ...base,
 files:base.files.filter(x=>x!=='commercial-config.json'),
 extraResources:[
  ...base.extraResources.filter(x=>x.to!=='commercial-config.json'&&x.to!=='commercial/license_public_key.pem'),
  {from:config,to:'commercial-config.json'},
  {from:publicKey,to:'commercial/license_public_key.pem'},
 ],
 win:{...base.win,verifyUpdateCodeSignature:false},
};
