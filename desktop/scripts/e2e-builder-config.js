'use strict';
// Isolated CI package configuration. Production package metadata is unchanged.
const build=require('../package.json').build;
const {generateE2ECommercialConfig}=require('./e2e-config-support');

const generated=generateE2ECommercialConfig();
module.exports={
  ...build,
  files:[...build.files.filter(entry=>entry!=='!e2e-main.js'),'e2e-main.js','e2e-commercial-config.js'],
  extraResources:[
    ...build.extraResources.filter(entry=>entry.to!=='commercial-config.json'&&entry.to!=='commercial/license_public_key.pem'),
    {from:generated.configPath,to:'commercial-config.json'},
    {from:generated.keyPath,to:'commercial/e2e-license-public-key.pem'},
  ],
  extraMetadata:{main:'e2e-main.js'},
};
