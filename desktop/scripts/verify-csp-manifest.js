'use strict';
const fs=require('node:fs');
const {spawnSync}=require('node:child_process');
const {equivalent}=require('./csp-manifest');
function readTracked(spec){
  if(!/^HEAD:[A-Za-z0-9._/-]+$/.test(spec))throw new Error('unsafe tracked git object');
  const result=spawnSync('git',['show',spec],{encoding:'utf8',maxBuffer:1024*1024});
  if(result.status!==0)throw new Error('could not read tracked CSP manifest');
  return JSON.parse(result.stdout);
}
function main(argv=process.argv.slice(2)){
  const trackedAt=argv.indexOf('--tracked-git'),generatedAt=argv.indexOf('--generated');
  if(trackedAt<0||generatedAt<0||!argv[trackedAt+1]||!argv[generatedAt+1])throw new Error('required arguments: --tracked-git and --generated');
  const tracked=readTracked(argv[trackedAt+1]);const generated=JSON.parse(fs.readFileSync(argv[generatedAt+1],'utf8'));
  if(!equivalent(tracked,generated))throw new Error('generated CSP semantic content identity differs from the tracked manifest');
  console.log('Generated CSP semantic content identity matches the tracked manifest; emitted hashes retained as platform evidence.');
}
if(require.main===module){try{main();}catch(error){console.error(`CSP manifest verification failed closed: ${error.message}`);process.exitCode=1;}}
module.exports={main};
