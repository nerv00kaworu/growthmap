'use strict';
const fs=require('node:fs');
function loadManifest(filename){
  const manifest=JSON.parse(fs.readFileSync(filename,'utf8'));
  if(manifest.version!==1||manifest.algorithm!=='sha256'||!Array.isArray(manifest.hashes)||!manifest.hashes.every(x=>/^sha256-[A-Za-z0-9+/]+={0,2}$/.test(x)))throw new Error('Packaged CSP script hash manifest is invalid');
  return manifest;
}
function policy(manifest){
  const scripts=["'self'",...manifest.hashes.map(x=>`'${x}'`)].join(' ');
  return `default-src 'self'; script-src ${scripts}; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`;
}
module.exports={loadManifest,policy};
