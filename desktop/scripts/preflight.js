'use strict';
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(process.env.GROWTHMAP_PREFLIGHT_ROOT||path.resolve(__dirname,'..','..')); const platform=process.argv[2]||process.platform;
const binary=path.join(root,'src','backend','dist',platform==='win32'?'growthmap-sidecar.exe':'growthmap-sidecar');
const required=[binary,path.join(root,'src','frontend','out','index.html'),...['LICENSE','EULA.md','PRIVACY.md','THIRD_PARTY_NOTICES.md'].map(x=>path.join(root,x))];
const missing=required.filter(x=>!fs.statSync?.(x,{throwIfNoEntry:false})?.isFile());
if(missing.length){console.error('Desktop packaging preflight failed; missing required files:\n'+missing.map(x=>`- ${x}`).join('\n'));process.exit(1);}
if(platform!=='win32'){try{fs.accessSync(binary,fs.constants.X_OK);}catch{console.error(`Desktop packaging preflight failed; sidecar is not executable: ${binary}`);process.exit(1);}}
if(process.env.GROWTHMAP_COMMERCIAL_RELEASE==='1'){
 const drafts=['LICENSE','EULA.md','PRIVACY.md','THIRD_PARTY_NOTICES.md'].filter(x=>fs.readFileSync(path.join(root,x),'utf8').includes('REQUIRES LEGAL REVIEW'));
 const publicKey=path.join(root,'src','backend','desktop','license_public_key.pem');
 const invalidKey=!fs.existsSync(publicKey)||fs.readFileSync(publicKey,'utf8').includes('REPLACE_WITH_PRODUCTION')||!fs.readFileSync(publicKey,'utf8').includes('BEGIN PUBLIC KEY');
 if(drafts.length||invalidKey){console.error(`Commercial packaging blocked: ${drafts.length?'legal drafts require approval; ':''}${invalidKey?'production license public key is missing/placeholder':''}`);process.exit(1);}
}
console.log(`Desktop packaging preflight passed (${platform}): ${binary}`);
