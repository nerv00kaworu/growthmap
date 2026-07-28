'use strict';
// Isolated package adapter: this file and its E2E_ONLY trust status never enter production ASAR.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const EXACT=['schemaVersion','productMajor','licensePublicKeyResource','licensePublicKeySha256','checkoutOrigin','checkoutUrl','updateUrl','updateOrigin','publisher','publisherStatus'];
function loadE2ECommercialConfig({isPackaged,resourcesPath}){
 if(!isPackaged)throw Error('E2E commercial configuration requires a packaged app');
 const doc=JSON.parse(fs.readFileSync(path.join(resourcesPath,'commercial-config.json'),'utf8'));
 if(Object.keys(doc).sort().join('\0')!==EXACT.slice().sort().join('\0')||doc.schemaVersion!==1||doc.productMajor!==1||doc.publisherStatus!=='E2E_ONLY'||doc.checkoutOrigin||doc.checkoutUrl||doc.updateUrl||doc.updateOrigin)throw Error('Isolated E2E commercial configuration is invalid');
 const publicKey=path.resolve(resourcesPath,doc.licensePublicKeyResource),root=`${path.resolve(resourcesPath)}${path.sep}`;
 if(!publicKey.startsWith(root)||!doc.licensePublicKeyResource.endsWith('.pem')||!/^[0-9a-f]{64}$/.test(doc.licensePublicKeySha256)||crypto.createHash('sha256').update(fs.readFileSync(publicKey)).digest('hex')!==doc.licensePublicKeySha256)throw Error('Isolated E2E license public key hash mismatch');
 return {...doc,licensePublicKeyPath:publicKey,e2eOnly:true};
}
module.exports={loadE2ECommercialConfig};
