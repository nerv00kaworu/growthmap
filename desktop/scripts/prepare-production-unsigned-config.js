'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),os=require('node:os');
const {loadCommercialConfig}=require('../commercial-config');
function fail(message){throw Error(`Production unsigned package blocked: ${message}`);}
function requiredAbsolute(name){const value=process.env[name];if(!value||!path.isAbsolute(value))fail(`${name} absolute path is required`);return value;}
const key=requiredAbsolute('GROWTHMAP_PRODUCTION_LICENSE_PUBLIC_KEY');
const output=requiredAbsolute('GROWTHMAP_PRODUCTION_PUBLIC_CONFIG');
const releaseMode=requiredAbsolute('GROWTHMAP_PRODUCTION_RELEASE_MODE');
if(!fs.statSync(key,{throwIfNoEntry:false})?.isFile())fail('G1 public key is missing');
const expectedMode={schemaVersion:1,mode:'unsigned-commercial',updatesEnabled:false,publisherDisplay:'Unknown Publisher — 月影塵（nerv00kaworu）'};
let actualMode;try{actualMode=JSON.parse(fs.readFileSync(releaseMode,'utf8'));}catch{fail('external production release mode is missing or invalid JSON');}
if(JSON.stringify(actualMode)!==JSON.stringify(expectedMode))fail('external production release mode metadata mismatch');
const stagedMode=path.join(__dirname,'..','dist','production-input','release-mode.json');
fs.mkdirSync(path.dirname(stagedMode),{recursive:true});fs.writeFileSync(stagedMode,JSON.stringify(actualMode,null,2)+'\n',{flag:'wx'});
const keyBytes=fs.readFileSync(key),pem=keyBytes.toString('utf8');
if(!/^-----BEGIN PUBLIC KEY-----\r?\n[\s\S]+\r?\n-----END PUBLIC KEY-----\r?\n?$/.test(pem)||pem.includes('PRIVATE KEY'))fail('G1 input must be an exact public PEM');
const pin=crypto.createHash('sha256').update(keyBytes).digest('hex');
if(process.env.GROWTHMAP_PRODUCTION_PUBLIC_KEY_SHA256!==pin)fail('witnessed G1 public-key pin does not match supplied PEM bytes');
const templatePath=path.join(__dirname,'..','production-unsigned-commercial-config.template.json');
let doc;try{doc=JSON.parse(fs.readFileSync(templatePath,'utf8'));}catch{fail('production unsigned template is invalid');}
doc.licensePublicKeySha256=pin;
fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(doc,null,2)+'\n',{flag:'wx'});
const root=fs.mkdtempSync(path.join(os.tmpdir(),'gm-production-unsigned-'));
try{fs.mkdirSync(path.join(root,'commercial'));fs.copyFileSync(key,path.join(root,'commercial','license_public_key.pem'));fs.copyFileSync(output,path.join(root,'commercial-config.json'));loadCommercialConfig({isPackaged:true,resourcesPath:root,releaseMode:'unsigned-commercial'});}finally{fs.rmSync(root,{recursive:true,force:true});}
console.log(`Production unsigned public config prepared; G1 pin ${pin}`);
