'use strict';
// Isolated CI package configuration. The production package.json remains authoritative;
// this removes its explicit E2E exclusion and adds only the CI-only entrypoint.
const build=require('../package.json').build;
module.exports={
  ...build,
  files:[...build.files.filter(entry=>entry!=='!e2e-main.js'),'e2e-main.js'],
  extraMetadata:{main:'e2e-main.js'},
};
