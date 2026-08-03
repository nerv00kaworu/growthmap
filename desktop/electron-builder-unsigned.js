'use strict';
// Unsigned manual beta: runnable authoring build with all online commercial
// activation, purchase and update authorities intentionally absent.
const base=require('./package.json').build;
module.exports={
  ...base,
  files:[...base.files.filter(entry=>entry!=='commercial-config.json')],
  extraResources:[
    ...base.extraResources.filter(entry=>entry.to!=='commercial-config.json'&&entry.to!=='commercial/license_public_key.pem'),
    {from:'noncommercial-config.json',to:'commercial-config.json'},
    {from:'noncommercial-license-public-key.pem',to:'commercial/noncommercial-license-public-key.pem'},
  ],
};
