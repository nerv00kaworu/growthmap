'use strict';
const crypto=require('node:crypto'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');

const E2E_KEY_RESOURCE='commercial/e2e-license-public-key.pem';
function sha256(bytes){return crypto.createHash('sha256').update(bytes).digest('hex');}
function generateE2ECommercialConfig({
  templatePath=path.join(__dirname,'../e2e/commercial-config.json'),
  keyPath=path.join(__dirname,'../e2e/commercial/e2e-license-public-key.pem'),
  outputDirectory=fs.mkdtempSync(path.join(os.tmpdir(),'growthmap-e2e-builder-')),
}={}){
  const config=JSON.parse(fs.readFileSync(templatePath,'utf8'));
  if(config.publisherStatus!=='E2E_ONLY'||config.licensePublicKeyResource!==E2E_KEY_RESOURCE)throw Error('Refusing to generate E2E config from an invalid trust template');
  config.licensePublicKeySha256=sha256(fs.readFileSync(keyPath));
  const configPath=path.join(outputDirectory,'commercial-config.json');
  fs.mkdirSync(outputDirectory,{recursive:true});
  fs.writeFileSync(configPath,`${JSON.stringify(config,null,2)}\n`,'utf8');
  return {configPath,keyPath,config};
}

module.exports={generateE2ECommercialConfig,sha256};
