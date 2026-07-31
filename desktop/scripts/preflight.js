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
if(process.env.GROWTHMAP_COMMERCIAL_RELEASE==='1'||process.env.GROWTHMAP_UNSIGNED_MANUAL_RELEASE==='1'){
 const unsignedManual=process.env.GROWTHMAP_UNSIGNED_MANUAL_RELEASE==='1';
 if(unsignedManual&&process.env.GROWTHMAP_COMMERCIAL_RELEASE==='1'){console.error('Choose exactly one release trust mode');process.exit(1);}
 const drafts=['LICENSE','EULA.md','PRIVACY.md','THIRD_PARTY_NOTICES.md'].filter(x=>/COMMERCIALIZATION PLACEHOLDER|REQUIRES LEGAL REVIEW/.test(fs.readFileSync(path.join(root,x),'utf8')));
 const publicKey=path.join(root,'src','backend','desktop','license_public_key.pem');
 const invalidKey=!fs.existsSync(publicKey)||fs.readFileSync(publicKey,'utf8').includes('REPLACE_WITH_PRODUCTION')||!fs.readFileSync(publicKey,'utf8').includes('BEGIN PUBLIC KEY');
 const identity=JSON.parse(fs.readFileSync(path.join(root,'desktop','product-identity.json'),'utf8')),pkg=JSON.parse(fs.readFileSync(path.join(root,'desktop','package.json'),'utf8'));
 const commercialFile=path.join(root,'desktop','commercial-config.json');let commercial={};try{commercial=JSON.parse(fs.readFileSync(commercialFile,'utf8'));}catch{}
 const signed=platform==='win32'&&Boolean(process.env.WIN_CSC_LINK&&process.env.WIN_CSC_KEY_PASSWORD);
 const expectedStatus=unsignedManual?'UNSIGNED_BY_OWNER_CHOICE':'APPROVED';
 const identityOk=identity.status===expectedStatus&&identity.windowsPublisher==='月影塵 (nerv00kaworu)'&&identity.creatorDisplayName===identity.windowsPublisher&&pkg.author===identity.windowsPublisher&&pkg.build.copyright===identity.copyright&&pkg.build.win.signtoolOptions?.publisherName===identity.windowsPublisher;
 const majorOk=Number(String(pkg.version).split('.')[0])===identity.productMajor&&identity.productMajor===1;
 let endpointsOk=false,commercialOk=false;try{const expected=require('../commercial-config').EXACT,keyHash=require('node:crypto').createHash('sha256').update(fs.readFileSync(publicKey)).digest('hex');const manualPayment=commercial.paymentApiOrigin===''&&commercial.purchasePortalOrigin===''&&commercial.purchasePortalUrl===''&&/^https:\/\/www\.paypal\.com\/ncp\/payment\//.test(commercial.paypalUrl)&&/^0x[0-9a-fA-F]{40}$/.test(commercial.basePayee);const manualUpdate=commercial.updateUrl===''&&commercial.updateOrigin===''&&identity.updateMode==='manual'&&/^https:\/\/github\.com\/nerv00kaworu\/growthmap\/releases\/?$/.test(identity.releasePageUrl);endpointsOk=unsignedManual&&manualPayment&&manualUpdate;commercialOk=Object.keys(commercial).sort().join('|')===expected.sort().join('|')&&commercial.publisherStatus===expectedStatus&&commercial.publisher===identity.windowsPublisher&&commercial.productMajor===identity.productMajor&&commercial.licensePublicKeySha256===keyHash&&!/REPLACE|EXAMPLE|TBD|UNAPPROVED/i.test(JSON.stringify(commercial));}catch{}
 const signatureOk=unsignedManual?!signed:signed;
 if(drafts.length||invalidKey||!endpointsOk||!commercialOk||!signatureOk||!identityOk||!majorOk){console.error(`Release packaging blocked: ${drafts.length?'legal placeholders remain; ':''}${invalidKey?'production license public key invalid; ':''}${!endpointsOk?'manual payment/update trust invalid; ':''}${!commercialOk?'commercial config invalid/mismatched; ':''}${!signatureOk?(unsignedManual?'unsigned mode unexpectedly has signing credentials; ':'Windows code signing credentials missing; '):''}${!identityOk?'creator/publisher identity mismatch; ':''}${!majorOk?'product major metadata mismatch':''}`);process.exit(1);}
}
console.log(`Desktop packaging preflight passed (${platform}): ${binary}`);
