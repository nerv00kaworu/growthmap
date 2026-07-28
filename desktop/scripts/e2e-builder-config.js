'use strict';
// Isolated CI package configuration. Production package metadata is unchanged.
const build=require('../package.json').build;
module.exports={
  ...build,
  files:[...build.files.filter(entry=>entry!=='!e2e-main.js'),'e2e-main.js','e2e-commercial-config.js'],
  extraResources:[
    ...build.extraResources.filter(entry=>entry.to!=='commercial-config.json'&&entry.to!=='commercial/license_public_key.pem'),
    {from:'e2e/commercial-config.json',to:'commercial-config.json'},
    {from:'e2e/commercial/e2e-license-public-key.pem',to:'commercial/e2e-license-public-key.pem'},
  ],
  extraMetadata:{main:'e2e-main.js'},
};
