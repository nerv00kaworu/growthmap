'use strict';
const fs=require('node:fs'),path=require('node:path');const {parseStrictJson}=require('./strict-json');
const EXACT=['schemaVersion','productMajor','licenseIssuer','supportEmail','supportUrl','licensePublicKeyResource','licensePublicKeySha256','activationApiOrigin','purchasePortalOrigin','purchasePortalUrl','updateUrl','updateOrigin','publisher','publisherStatus'];
function loadE2ECommercialConfig({isPackaged,resourcesPath}){
 if(!isPackaged)throw Error('E2E commercial configuration requires a packaged app');
 const doc=parseStrictJson(fs.readFileSync(path.join(resourcesPath,'commercial-config.json'),'utf8'));
 if(Object.keys(doc).sort().join('\0')!==EXACT.slice().sort().join('\0')||doc.schemaVersion!==4||doc.productMajor!==1||doc.publisherStatus!=='E2E_ONLY'||doc.activationApiOrigin||doc.purchasePortalOrigin||doc.purchasePortalUrl||doc.updateUrl||doc.updateOrigin)throw Error('Isolated E2E commercial configuration is invalid');
 return {...doc,licensePublicKeyPath:path.join(resourcesPath,doc.licensePublicKeyResource)};
}
module.exports={loadE2ECommercialConfig};
