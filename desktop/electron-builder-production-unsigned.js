'use strict';
// Explicitly unsigned commercial manual-distribution package. The exact public
// G1 PEM and generated immutable config are supplied from job-external paths.
const path=require('node:path');
const base=require('./package.json').build;
function required(name){const value=process.env[name];if(!value||!path.isAbsolute(value))throw Error(`${name} absolute generated production input is required`);return value;}
const config=required('GROWTHMAP_PRODUCTION_PUBLIC_CONFIG');
const publicKey=required('GROWTHMAP_PRODUCTION_LICENSE_PUBLIC_KEY');
module.exports={
 ...base,
 // The workflow materializes the reviewed production metadata at the canonical
 // release-mode.json path before electron-builder evaluates the ordinary file list.
 files:[...base.files.filter(x=>x!=='commercial-config.json')],
 extraResources:[
  ...base.extraResources.filter(x=>x.to!=='commercial-config.json'&&x.to!=='commercial/license_public_key.pem'),
  {from:config,to:'commercial-config.json'},
  {from:publicKey,to:'commercial/license_public_key.pem'},
 ],
 win:{...base.win,verifyUpdateCodeSignature:false},
};
