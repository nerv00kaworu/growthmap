'use strict';
// Isolated package adapter: this file and its E2E_ONLY trust status never enter production ASAR.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {parseStrictJson}=require('./strict-json');
const EXACT=['schemaVersion', 'productMajor', 'licenseIssuer', 'supportEmail', 'supportUrl', 'licensePublicKeyResource', 'licensePublicKeySha256', 'paymentApiOrigin', 'purchasePortalOrigin', 'purchasePortalUrl', 'baseNetwork', 'baseUsdc', 'basePayee', 'earlyLimit', 'earlyPriceMicros', 'regularPriceMicros', 'paypalUrl', 'updateUrl', 'updateOrigin', 'publisher', 'publisherStatus'];
function loadE2ECommercialConfig({isPackaged,resourcesPath}){
 if(!isPackaged)throw Error('E2E commercial configuration requires a packaged app');
 const doc=parseStrictJson(fs.readFileSync(path.join(resourcesPath,'commercial-config.json'),'utf8'));
 if(Object.keys(doc).sort().join('\0')!==EXACT.slice().sort().join('\0')||doc.schemaVersion!==3||doc.productMajor!==1||doc.publisherStatus!=='E2E_ONLY'||doc.paymentApiOrigin||doc.purchasePortalOrigin||doc.purchasePortalUrl||doc.paypalUrl||doc.updateUrl||doc.updateOrigin)throw Error('Isolated E2E commercial configuration is invalid');
 const publicKey=path.resolve(resourcesPath,doc.licensePublicKeyResource),root=`${path.resolve(resourcesPath)}${path.sep}`;
 if(!publicKey.startsWith(root)||!doc.licensePublicKeyResource.endsWith('.pem')||!/^[0-9a-f]{64}$/.test(doc.licensePublicKeySha256)||crypto.createHash('sha256').update(fs.readFileSync(publicKey)).digest('hex')!==doc.licensePublicKeySha256)throw Error('Isolated E2E license public key hash mismatch');
 return {...doc,licensePublicKeyPath:publicKey,e2eOnly:true};
}
module.exports={loadE2ECommercialConfig};
