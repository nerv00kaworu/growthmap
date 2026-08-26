'use strict';
const fs=require('node:fs'),net=require('node:net'),os=require('node:os'),path=require('node:path'),{spawn,spawnSync}=require('node:child_process'),{chromium}=require('playwright-core');
const {launchArgs,pythonRunner,processTree,processIdentityKey,matchingProcessIdentities,timeoutDiagnostic,parseDevToolsWebSocket,assertE2EPackage}=require('./renderer-e2e-support');
if(process.platform!=='win32')throw new Error('Packaged renderer E2E must run on Windows');
if(process.env.CI!=='true')throw new Error('Renderer E2E is CI-only');
const root=path.resolve(__dirname,'..');
const runPython=pythonRunner({spawnSync});
const executable=process.env.GROWTHMAP_PACKAGED_EXE||path.join(root,'dist','win-unpacked','GrowthMap.exe');
const screenshot=process.env.GROWTHMAP_E2E_SCREENSHOT||path.join(root,'artifacts','growthmap-renderer.png');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const HARD_TIMEOUT_MS=7*60*1000;let activeChild=null,currentPhase='bootstrap';
function phase(name){currentPhase=name;console.log(`E2E phase: ${name}`);}
function killOwnedTree(child=activeChild){if(child?.pid)spawnSync('taskkill',['/PID',String(child.pid),'/T','/F'],{stdio:'ignore',windowsHide:true});}
const hardWatchdog=setTimeout(()=>{console.error(`E2E hard timeout after ${HARD_TIMEOUT_MS}ms; phase=${currentPhase}; childPid=${activeChild?.pid||'none'}; childExit=${activeChild?.exitCode??'null'}; childSignal=${activeChild?.signalCode||'none'}`);killOwnedTree();process.exit(124);},HARD_TIMEOUT_MS);
function port(){return new Promise((ok,no)=>{const s=net.createServer();s.once('error',no);s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>ok(p));});});}
function processSnapshot(rootPid){const value=processTree(rootPid);if(!Array.isArray(value))throw Error(`process tree inspection failed: ${value?.error||'unknown error'}`);return value;}
function mergeSnapshots(...snapshots){const byIdentity=new Map();for(const item of snapshots.flat())byIdentity.set(processIdentityKey(item),item);return [...byIdentity.values()];}
function survivingTree(snapshot){if(!snapshot.length)return [];const ids=[...new Set(snapshot.map(item=>Number(item.ProcessId)))];const q=`$ids=@(${ids.join(',')});@(Get-CimInstance Win32_Process|Where-Object{$ids -contains $_.ProcessId}|Select-Object ProcessId,Name,ParentProcessId,CreationDate,ExecutablePath)|ConvertTo-Json -Compress`;const r=spawnSync('powershell',['-NoProfile','-Command',q],{encoding:'utf8',windowsHide:true});if(r.status!==0)throw Error(`process tree inspection failed: ${(r.stderr||'').trim()}`);const text=(r.stdout||'').trim();if(!text)return [];const value=JSON.parse(text),current=Array.isArray(value)?value:[value];return matchingProcessIdentities(snapshot,current);}
async function waitForTreeGone(snapshot,timeout=20000){const deadline=Date.now()+timeout;let survivors=[];do{survivors=survivingTree(snapshot);if(!survivors.length)return;await sleep(250);}while(Date.now()<deadline);throw Error(`spawned process tree remained after close: ${JSON.stringify(survivors)}`);}
async function snapshot(page){return page.evaluate(()=>({url:location.href,title:document.title,text:(document.body?.innerText||'').slice(0,2000),html:(document.body?.innerHTML||'').slice(0,1000)})).catch(()=>({unavailable:true}));}
async function stageWait(run,name,predicate,timeout=30000){console.log(`E2E stage start: ${name}`);const deadline=Date.now()+timeout;while(Date.now()<deadline){if(run.child.exitCode!==null)throw Error(`${name}: app exited; child=${run.output().slice(-1500)}`);const state=await run.page.evaluate(predicate).catch(()=>null);if(state===true){console.log(`E2E stage pass: ${name}`);return;}if(state&&state.error)throw Error(`${name}: UI error=${state.error}; diagnostic=${JSON.stringify(await snapshot(run.page))}; child=${run.output().slice(-1500)}`);await sleep(250);}throw Error(`${name}: timeout; diagnostic=${JSON.stringify(await snapshot(run.page))}; child=${run.output().slice(-1500)}`);}
async function abortLaunch(child,browser,snapshot){
 await browser?.close().catch(()=>{});
 const targets=[...new Set([...(snapshot||[]).map(item=>item.ProcessId),child?.pid].filter(Boolean))].reverse();
 for(const pid of targets)spawnSync('taskkill',['/PID',String(pid),'/T','/F'],{stdio:'ignore',windowsHide:true});
 const deadline=Date.now()+20000;while(child?.exitCode===null&&Date.now()<deadline)await sleep(100);
 if(snapshot?.length)await waitForTreeGone(snapshot).catch(()=>{});
}
async function launch(userData,fixture,profileMode,{injectHydrationFailure=false,expectStartupFailure=false}={}){
 if(!['fresh','existing-free'].includes(profileMode))throw Error('invalid E2E profile mode');
 const debugPort=await port(),diagnosticPath=path.join(userData,'e2e-phases.log'),electronLogPath=path.join(userData,'electron.log');
 phase(`launch-${profileMode}${injectHydrationFailure?'-injected-failure':''}`);const child=spawn(executable,launchArgs({userData,debugPort,logPath:electronLogPath}),{env:{...process.env,CI:'true',GROWTHMAP_DESKTOP_E2E:'1',GROWTHMAP_E2E_PROFILE_MODE:profileMode,GROWTHMAP_E2E_USER_DATA:userData,GROWTHMAP_E2E_IMPORT_PATH:fixture,GROWTHMAP_E2E_DIAGNOSTIC_PATH:diagnosticPath,GROWTHMAP_E2E_INJECT_HYDRATION_FAILURE:injectHydrationFailure?'1':'0'},stdio:['ignore','pipe','pipe'],windowsHide:true});
 activeChild=child;let output='',directWebSocket=null,browser,tree=processSnapshot(child.pid);const capture=x=>{output+=x;directWebSocket=parseDevToolsWebSocket(output,debugPort);};child.stdout.on('data',capture);child.stderr.on('data',capture);
 try{
  const deadline=Date.now()+120000;
  while(Date.now()<deadline){if(child.exitCode!==null){if(expectStartupFailure)return {child,browser,page:null,tree,output:()=>output};throw Error(`app exited early: ${output.slice(-1500)}`);}try{browser=await chromium.connectOverCDP(directWebSocket||`http://127.0.0.1:${debugPort}`,{timeout:2000});break;}catch{await sleep(250);}}
  if(!browser){if(expectStartupFailure)return {child,browser,page:null,tree,output:()=>output};throw Error(JSON.stringify(await timeoutDiagnostic({child,debugPort,output,diagnosticPath,electronLogPath}),null,2));}
  let page;while(Date.now()<deadline&&!page){tree=mergeSnapshots(tree,processSnapshot(child.pid));if(child.exitCode!==null&&expectStartupFailure)return {child,browser,page:null,tree,output:()=>output};page=browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().startsWith('http://127.0.0.1:'));if(!page)await sleep(200);}
  if(!page){if(expectStartupFailure)return {child,browser,page:null,tree,output:()=>output};throw Error(`renderer page missing; child=${output.slice(-1500)}`);}
  const run={child,browser,page,tree,output:()=>output};if(!expectStartupFailure)await stageWait(run,'renderer-ready',()=>Boolean(document.querySelector('[data-testid="growthmap-title"]')&&document.querySelector('[data-testid="settings-menu-button"]')&&document.querySelector('[data-testid="database-workspace-button"]')),90000);return run;
 }catch(error){await abortLaunch(child,browser,tree);throw error;}
}
async function close(run){phase('close-app');await run.page.close();const deadline=Date.now()+20000;while(run.child.exitCode===null&&Date.now()<deadline)await sleep(100);if(run.child.exitCode===null)throw Error('GrowthMap.exe did not exit');await run.browser.close().catch(()=>{});await waitForTreeGone(run.tree);if(activeChild===run.child)activeChild=null;}
async function credentialProof(run,credential){
 const result=await run.page.evaluate(async credential=>{
  const provider=await fetch('/api/providers',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'E2E local credential provider',provider_type:'openai_compatible',endpoint:'http://127.0.0.1:9',secret_env_key:'GROWTHMAP_LLM_KEY_E2E',model_name:'fixture',capabilities:[],cost_level:'none',enabled:true})}).then(r=>r.json());
  await window.growthmapDesktop.secrets.set(provider.id,credential);const current=await fetch(`/api/providers/${provider.id}`,{credentials:'same-origin'}).then(r=>r.json());return {id:provider.id,revision:current.revision,status:current.credential_status,type:current.provider_type};
 },credential);if(result.type==='mock'||result.status!=='ready')throw Error(`credential authority set failed: ${JSON.stringify(result)}`);return result;
}
async function credentialCheckpoint(run,proof,label){
 const result=await run.page.evaluate(async proof=>{const current=await fetch(`/api/providers/${proof.id}`,{credentials:'same-origin'}).then(r=>r.json()),has=await window.growthmapDesktop.secrets.has(proof.id);return {type:current.provider_type,status:current.credential_status,revision:current.revision,has};},proof);console.log(`E2E credential checkpoint ${label}: ${JSON.stringify(result)}`);return result;
}
async function assertRestartCredential(run,proof,credential){
 const checkpoint=await credentialCheckpoint(run,proof,'full-restart'),denied=await run.page.evaluate(async({proof,credential})=>(await fetch(`/api/desktop/secrets/${proof.id}/hydrate`,{method:'PUT',credentials:'same-origin',headers:{'Content-Type':'application/json','X-GrowthMap-Hydration-Capability':'E'.repeat(43)},body:JSON.stringify({api_key:credential})})).status,{proof,credential}),result={...checkpoint,denied};
 if(result.type==='mock'||result.status!=='ready'||result.revision!==proof.revision||result.has!==true||result.denied!==403)throw Error(`restart hydration/seal proof failed: ${JSON.stringify(result)}`);
}
(async()=>{
 if(!fs.existsSync(executable))throw Error('packaged resources missing');
 const resources=path.join(path.dirname(executable),'resources');assertE2EPackage(path.join(resources,'app.asar'),resources);
 const userData=fs.mkdtempSync(path.join(os.tmpdir(),'growthmap-e2e-profile-'));
 const fixtureDirectory=fs.mkdtempSync(path.join(os.tmpdir(),'growthmap-e2e-input-')),fixture=path.join(fixtureDirectory,'fixture.sqlite');
 const helper=path.join(root,'scripts','create-e2e-fixture.py');
 let made=runPython([helper,fixture],{encoding:'utf8'});if(made.status!==0)throw Error(made.stderr);
 phase('fresh-launch');let run=await launch(userData,fixture,'fresh');
 try{
  await stageWait(run,'fresh-free',async()=>{const status=document.querySelector('[data-testid="entitlement-status"]')?.textContent||'';let entitlement;try{const response=await fetch('/api/desktop/entitlement');entitlement=response.ok?await response.json():{http_status:response.status};}catch(error){return {error:`entitlement request failed: ${error?.name||'Error'}`};}if(status.startsWith('Free ·')&&entitlement.state==='free'&&entitlement.valid===true&&entitlement.mutations_allowed===true)return true;if(status.includes('Read-only')||entitlement.state==='extraction')return {error:`unexpected entitlement: ui=${status}; state=${entitlement.state}; valid=${entitlement.valid}; mutations_allowed=${entitlement.mutations_allowed}; reason=${entitlement.reason}`};return false;},30000);
  for(const name of ['trial-marker.bin','installation-identity.bin','trial-state.json']){const target=path.join(userData,name);if(!fs.existsSync(target)||fs.statSync(target).size===0)throw Error(`fresh-free: missing initialized Free artifact ${name}`);}
  await run.page.getByTestId('settings-menu-button').click();
  await run.page.getByTestId('llm-provider-settings-button').click();
  await run.page.getByTestId('llm-provider-settings').waitFor();
  if(await run.page.getByTestId('database-workspace').count()||await run.page.getByTestId('database-management').count())throw Error('database controls leaked into LLM Provider settings');
  await run.page.getByTestId('llm-provider-settings-close').click();
  await run.page.getByTestId('database-workspace-button').click();
  await run.page.getByTestId('database-workspace').waitFor();
  const initialPath=await run.page.getByTestId('database-path').textContent();
  if(!initialPath||!initialPath.toLowerCase().endsWith('growthmap.db'))throw Error(`database workspace did not expose canonical path: ${initialPath}`);
  const beforeImport=await run.page.evaluate(async()=>{const health=await fetch('/api/health/deep',{credentials:'same-origin'});return {health:health.status,title:Boolean(document.querySelector('[data-testid="growthmap-title"]'))}});
  run.page.once('dialog',d=>d.accept());
  await run.page.getByTestId('database-import').click();
  await stageWait(run,'import-safely-unavailable',()=>{const e=document.querySelector('[data-testid="database-operation-message"]')?.textContent||'';return /failed|preserved/i.test(e);},90000);
  let afterImport;await stageWait(run,'import-refusal-health',async()=>{try{const health=await fetch('/api/health/deep',{credentials:'same-origin'});afterImport={health:health.status,title:Boolean(document.querySelector('[data-testid="growthmap-title"]'))};return afterImport.health===200&&afterImport.title;}catch(error){afterImport={health:'unavailable',title:Boolean(document.querySelector('[data-testid="growthmap-title"]')),error:error?.name||'Error'};return false;}},30000);if(beforeImport.health!==200||!beforeImport.title)throw Error(`broker-unavailable import precondition failed: ${JSON.stringify({beforeImport,afterImport})}`);
  const syntheticCredential=`e2e-${require('node:crypto').randomBytes(24).toString('base64url')}`,credentialProofResult=await credentialProof(run,syntheticCredential);await credentialCheckpoint(run,credentialProofResult,'after-set');
  await run.page.getByTestId('database-workspace').waitFor();
  await run.page.getByTestId('database-backup').click();
  await stageWait(run,'backup',()=>{const e=document.querySelector('[data-testid="database-operation-message"]')?.textContent||'';if(e.startsWith('✅'))return true;return e?{error:e.slice(0,300)}:false;},90000);
  const afterBackupCredential=await credentialCheckpoint(run,credentialProofResult,'after-backup-restart');if(afterBackupCredential.status!=='ready'||afterBackupCredential.revision!==credentialProofResult.revision||afterBackupCredential.has!==true)throw Error(`backup restart lost credential authority: ${JSON.stringify(afterBackupCredential)}`);
  fs.mkdirSync(path.dirname(screenshot),{recursive:true});await run.page.screenshot({path:screenshot,fullPage:true});
  await close(run);
  phase('restart-launch');run=await launch(userData,fixture,'existing-free');
  await assertRestartCredential(run,credentialProofResult,syntheticCredential);
  await stageWait(run,'restart-free',async()=>{const status=document.querySelector('[data-testid="entitlement-status"]')?.textContent||'';const response=await fetch('/api/desktop/entitlement');if(!response.ok)return {error:`entitlement HTTP ${response.status}`};const entitlement=await response.json();if(status.startsWith('Free ·')&&entitlement.state==='free'&&entitlement.valid===true&&entitlement.mutations_allowed===true)return true;return status.includes('Read-only')||entitlement.state==='extraction'?{error:`Free identity not preserved: ui=${status}; state=${entitlement.state}; valid=${entitlement.valid}; mutations_allowed=${entitlement.mutations_allowed}; reason=${entitlement.reason}`}:false;},30000);
  await close(run);
  phase('injected-failure-launch');run=await launch(userData,fixture,'existing-free',{injectHydrationFailure:true,expectStartupFailure:true});
  const failureDeadline=Date.now()+30000;while(run.child.exitCode===null&&Date.now()<failureDeadline)await sleep(200);if(run.child.exitCode===null)throw Error('injected hydration failure did not block/terminate startup');if(run.page)throw Error('injected hydration failure exposed a renderer page');if(run.output().includes(syntheticCredential))throw Error('credential echoed in hydration-failure diagnostic');await run.browser?.close().catch(()=>{});await waitForTreeGone(run.tree);
  console.log(`Packaged normal-startup, lazy-replacement failure, backup, credential restart and fail-closed lifecycle E2E passed; screenshot=${screenshot}`);
 }finally{phase('final-cleanup');if(run?.child.exitCode===null)killOwnedTree(run.child);activeChild=null;fs.rmSync(fixtureDirectory,{recursive:true,force:true});}
})().then(()=>{clearTimeout(hardWatchdog);}).catch(e=>{clearTimeout(hardWatchdog);killOwnedTree();console.error(e.stack||e);process.exit(1);});
