'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {loadCommercialConfig}=require('../commercial-config');
function fail(message){console.error(`Gift staging package blocked: ${message}`);process.exit(1);}
const key=process.env.GROWTHMAP_STAGING_LICENSE_PUBLIC_KEY,output=process.env.GROWTHMAP_STAGING_PUBLIC_CONFIG,origin=process.env.GROWTHMAP_STAGING_AUTHORITY_ORIGIN;
if(!key||!output||!origin||!path.isAbsolute(key)||!path.isAbsolute(output))fail('absolute public key/config paths and staging Authority origin are required');
if(!fs.statSync(key,{throwIfNoEntry:false})?.isFile())fail('staging public key is missing');
let template;try{template=JSON.parse(fs.readFileSync(path.join(__dirname,'..','staging-commercial-config.template.json'),'utf8'));}catch{fail('staging template is invalid');}
template.activationApiOrigin=origin;
template.licensePublicKeySha256=crypto.createHash('sha256').update(fs.readFileSync(key)).digest('hex');
if(process.env.GROWTHMAP_STAGING_PUBLIC_KEY_SHA256!==template.licensePublicKeySha256)fail('witnessed public-key pin does not match the supplied public key');
fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(template,null,2)+'\n',{flag:'wx'});
try{loadCommercialConfig({isPackaged:true,resourcesPath:path.dirname(output),releaseMode:'unsigned-staging'});}catch(error){
 // Validate through an exact resources layout without weakening production loader.
 const root=fs.mkdtempSync(path.join(require('node:os').tmpdir(),'gm-staging-config-'));try{fs.mkdirSync(path.join(root,'commercial'));fs.copyFileSync(key,path.join(root,'commercial','license_public_key.pem'));fs.copyFileSync(output,path.join(root,'commercial-config.json'));loadCommercialConfig({isPackaged:true,resourcesPath:root,releaseMode:'unsigned-staging'});}catch(e){fail(e.message);}finally{fs.rmSync(root,{recursive:true,force:true});}
}
console.log(`Gift staging public config prepared; pin ${template.licensePublicKeySha256}`);
