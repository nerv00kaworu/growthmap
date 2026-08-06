'use strict';
const fs=require('node:fs'),http=require('node:http'),path=require('node:path'),{spawnSync}=require('node:child_process');
function launchArgs({userData,debugPort,logPath}){return [`--user-data-dir=${userData}`,`--remote-debugging-port=${debugPort}`,'--enable-logging',`--log-file=${logPath}`];}
function pythonRunner({spawnSync,env=process.env}){
 const interpreter=env.GROWTHMAP_TEST_PYTHON||env.PYTHON||'python';
 const run=(args,options)=>spawnSync(interpreter,args,options);run.interpreter=interpreter;return run;
}
function processTree(rootPid){
 const q=`$root=${Number(rootPid)};$all=Get-CimInstance Win32_Process;$seen=@($root);do{$before=$seen.Count;$seen+=@($all|Where-Object{$seen -contains $_.ParentProcessId}|ForEach-Object ProcessId);$seen=@($seen|Sort-Object -Unique)}while($seen.Count -gt $before);$all|Where-Object{$seen -contains $_.ProcessId}|Select-Object ProcessId,ParentProcessId,Name,CommandLine|ConvertTo-Json -Compress`;
 const r=spawnSync('powershell',['-NoProfile','-Command',q],{encoding:'utf8',windowsHide:true});
 if(r.status!==0)return {error:(r.stderr||`powershell exit ${r.status}`).trim()};
 try{const value=JSON.parse(r.stdout||'[]');return Array.isArray(value)?value:[value];}catch(error){return {error:`invalid process tree JSON: ${error.message}`,stdout:(r.stdout||'').trim()};}
}
function parseDevToolsWebSocket(output,expectedPort){
 const matches=String(output).matchAll(/DevTools listening on (ws:\/\/[^\s]+)/g);let accepted=null;
 for(const match of matches){try{const url=new URL(match[1]);if(url.protocol==='ws:'&&url.hostname==='127.0.0.1'&&Number(url.port)===Number(expectedPort)&&/^\/devtools\/browser\/[0-9a-f-]+$/i.test(url.pathname)&&!url.username&&!url.password&&!url.search&&!url.hash)accepted=url.href;}catch{}}
 return accepted;
}
function probeVersion(debugPort,timeout=2000){return new Promise(resolve=>{
 const request=http.get({hostname:'127.0.0.1',port:debugPort,path:'/json/version',timeout},response=>{let body='';response.setEncoding('utf8');response.on('data',chunk=>body+=chunk);response.on('end',()=>resolve({statusCode:response.statusCode,body:body.slice(0,4000)}));});
 request.on('timeout',()=>request.destroy(new Error(`timeout after ${timeout}ms`)));
 request.on('error',error=>resolve({error:`${error.code||error.name}: ${error.message}`}));
 });
}
function tail(file,max=8000){try{const value=fs.readFileSync(file,'utf8');return value.slice(-max);}catch(error){return `<unavailable: ${error.code||error.message}>`;}}
async function timeoutDiagnostic({child,debugPort,output,diagnosticPath,electronLogPath}){return {
  message:'CDP timeout',pid:child.pid,exitCode:child.exitCode,signalCode:child.signalCode,killed:child.killed,
  processTree:processTree(child.pid),probe:await probeVersion(debugPort),stdoutStderr:String(output).slice(-8000),
  phases:tail(diagnosticPath),electronLog:tail(electronLogPath),
 };}
function assertE2EPackage(asarPath,resourcesPath=path.dirname(asarPath)){
 const asar=require('@electron/asar'),entries=asar.listPackage(asarPath).map(value=>value.replace(/^[/\\]/,''));
 for(const entry of ['e2e-main.js','e2e-commercial-config.js'])if(!entries.includes(entry))throw Error(`E2E app.asar is missing ${entry}`);
 const metadata=JSON.parse(asar.extractFile(asarPath,'package.json').toString('utf8'));
 if(metadata.main!=='e2e-main.js')throw Error(`E2E app.asar main must be e2e-main.js, got ${JSON.stringify(metadata.main)}`);
 const configPath=path.join(resourcesPath,'commercial-config.json'),config=JSON.parse(fs.readFileSync(configPath,'utf8'));
 if(config.publisherStatus!=='E2E_ONLY'||config.activationApiOrigin||config.purchasePortalOrigin||config.purchasePortalUrl||config.updateUrl||config.updateOrigin)throw Error('E2E commercial config endpoint settings are invalid');
 const key=path.resolve(resourcesPath,config.licensePublicKeyResource),root=`${path.resolve(resourcesPath)}${path.sep}`;
 if(!key.startsWith(root)||!fs.existsSync(key))throw Error('E2E commercial public key is missing or outside resources');
 const hash=require('node:crypto').createHash('sha256').update(fs.readFileSync(key)).digest('hex');if(hash!==config.licensePublicKeySha256)throw Error('E2E commercial public key hash mismatch');
 return {metadata,config};
}
module.exports={launchArgs,pythonRunner,processTree,probeVersion,parseDevToolsWebSocket,tail,timeoutDiagnostic,assertE2EPackage};
