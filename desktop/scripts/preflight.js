'use strict';
const fs=require('node:fs'),path=require('node:path');
const {verify}=require('./csp-manifest');
const root=path.resolve(process.env.GROWTHMAP_PREFLIGHT_ROOT||path.resolve(__dirname,'..','..')); const platform=process.argv[2]||process.platform;
const binary=path.join(root,'src','backend','dist',platform==='win32'?'growthmap-sidecar.exe':'growthmap-sidecar');
const required=[binary,path.join(root,'src','frontend','out','index.html'),...['LICENSE','EULA.md','PRIVACY.md','THIRD_PARTY_NOTICES.md'].map(x=>path.join(root,x))];
const missing=required.filter(x=>!fs.statSync?.(x,{throwIfNoEntry:false})?.isFile());
if(missing.length){console.error('Desktop packaging preflight failed; missing required files:\n'+missing.map(x=>`- ${x}`).join('\n'));process.exit(1);}
const manifestFile=path.join(root,'desktop','generated','csp-script-hashes.json');
if(!fs.statSync(manifestFile,{throwIfNoEntry:false})?.isFile()){console.error(`Desktop packaging preflight failed; CSP manifest missing: ${manifestFile}`);process.exit(1);}
try{verify(JSON.parse(fs.readFileSync(manifestFile,'utf8')),path.join(root,'src','frontend','out'));}catch(e){console.error(`Desktop packaging preflight failed: ${e.message}`);process.exit(1);}
if(platform!=='win32'){try{fs.accessSync(binary,fs.constants.X_OK);}catch{console.error(`Desktop packaging preflight failed; sidecar is not executable: ${binary}`);process.exit(1);}}
if(process.env.GROWTHMAP_COMMERCIAL_RELEASE==='1'){
 const drafts=['LICENSE','EULA.md','PRIVACY.md','THIRD_PARTY_NOTICES.md'].filter(x=>fs.readFileSync(path.join(root,x),'utf8').includes('REQUIRES LEGAL REVIEW'));
 const publicKey=path.join(root,'src','backend','desktop','license_public_key.pem');
 const invalidKey=!fs.existsSync(publicKey)||fs.readFileSync(publicKey,'utf8').includes('REPLACE_WITH_PRODUCTION')||!fs.readFileSync(publicKey,'utf8').includes('BEGIN PUBLIC KEY');
 const identity=JSON.parse(fs.readFileSync(path.join(root,'desktop','product-identity.json'),'utf8')),pkg=JSON.parse(fs.readFileSync(path.join(root,'desktop','package.json'),'utf8'));
 const commercialFile=path.join(root,'desktop','commercial-config.json');let commercial={};try{commercial=JSON.parse(fs.readFileSync(commercialFile,'utf8'));}catch{}
 const updateUrl=commercial.updateUrl||'';
 const checkoutOrigin=commercial.checkoutOrigin||'',checkoutUrl=commercial.checkoutUrl||'';
 const signed=platform==='win32'&&Boolean(process.env.WIN_CSC_LINK&&process.env.WIN_CSC_KEY_PASSWORD);
 const publisherOk=identity.status==='APPROVED'&&typeof identity.windowsPublisher==='string'&&!/REPLACE|EXAMPLE|TBD/i.test(identity.windowsPublisher)&&pkg.build.win.publisherName===identity.windowsPublisher;
 const majorOk=Number(String(pkg.version).split('.')[0])===identity.productMajor&&identity.productMajor===1;
 let endpointsOk=false,commercialOk=false;try{const {validateUpdateUrl,checkoutAllowed,canonicalOrigin}=require('../update-policy');validateUpdateUrl(updateUrl,{production:true});const checkout=new URL(checkoutOrigin);endpointsOk=checkout.protocol==='https:'&&!/example\.(com|invalid)|localhost|127\.0\.0\.1/i.test(checkout.href)&&checkoutAllowed(checkoutUrl,checkoutOrigin)&&new URL(updateUrl).origin===canonicalOrigin(commercial.updateOrigin);const expected=['schemaVersion','productMajor','licensePublicKeyResource','licensePublicKeySha256','checkoutOrigin','checkoutUrl','updateUrl','updateOrigin','publisher','publisherStatus'];commercialOk=Object.keys(commercial).sort().join('|')===expected.sort().join('|')&&commercial.publisherStatus==='APPROVED'&&commercial.publisher===identity.windowsPublisher&&commercial.productMajor===identity.productMajor&&commercial.licensePublicKeySha256===require('node:crypto').createHash('sha256').update(fs.readFileSync(publicKey)).digest('hex')&&!/REPLACE|EXAMPLE|TBD|UNAPPROVED/i.test(JSON.stringify(commercial));}catch{}
 if(drafts.length||invalidKey||!endpointsOk||!commercialOk||!signed||!publisherOk||!majorOk){console.error(`Commercial packaging blocked: ${drafts.length?'legal drafts require approval; ':''}${invalidKey?'production license public key is missing/placeholder; ':''}${!endpointsOk?'production HTTPS update/checkout endpoints missing; ':''}${!commercialOk?'immutable commercial config invalid/mismatched/placeholder; ':''}${!signed?'Windows code signing credentials missing; ':''}${!publisherOk?'approved exact Windows publisher identity missing/mismatched; ':''}${!majorOk?'product major metadata mismatch':''}`);process.exit(1);}
}
console.log(`Desktop packaging preflight passed (${platform}): ${binary}`);
