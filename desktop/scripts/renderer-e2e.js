'use strict';
const fs=require('node:fs'),net=require('node:net'),os=require('node:os'),path=require('node:path'),{spawn,spawnSync}=require('node:child_process'),{chromium}=require('playwright-core');
const {launchArgs,pythonRunner,timeoutDiagnostic,parseDevToolsWebSocket,assertE2EPackage}=require('./renderer-e2e-support');
if(process.platform!=='win32')throw new Error('Packaged renderer E2E must run on Windows');
if(process.env.CI!=='true')throw new Error('Renderer E2E is CI-only');
const root=path.resolve(__dirname,'..');
const runPython=pythonRunner({spawnSync});
const executable=process.env.GROWTHMAP_PACKAGED_EXE||path.join(root,'dist','win-unpacked','GrowthMap.exe');
const screenshot=process.env.GROWTHMAP_E2E_SCREENSHOT||path.join(root,'artifacts','growthmap-renderer.png');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function port(){return new Promise((ok,no)=>{const s=net.createServer();s.once('error',no);s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>ok(p));});});}
function descendants(rootPid){const q=`$root=${rootPid};$all=Get-CimInstance Win32_Process;$seen=@($root);do{$before=$seen.Count;$seen+=@($all|Where-Object{$seen -contains $_.ParentProcessId}|ForEach-Object ProcessId);$seen=@($seen|Sort-Object -Unique)}while($seen.Count -gt $before);$seen -join ','`;const r=spawnSync('powershell',['-NoProfile','-Command',q],{encoding:'utf8',windowsHide:true});return (r.stdout||'').trim().split(',').filter(Boolean).map(Number);}
function survivingTree(pids){const q=`$ids=@(${pids.join(',')});@(Get-CimInstance Win32_Process|Where-Object{$ids -contains $_.ProcessId}|Select-Object ProcessId,Name,ParentProcessId)|ConvertTo-Json -Compress`;const r=spawnSync('powershell',['-NoProfile','-Command',q],{encoding:'utf8',windowsHide:true});if(r.status!==0)throw Error(`process tree inspection failed: ${(r.stderr||'').trim()}`);const text=(r.stdout||'').trim();if(!text)return [];const parsed=JSON.parse(text);return Array.isArray(parsed)?parsed:[parsed];}
async function waitForTreeGone(pids,timeout=20000){const deadline=Date.now()+timeout;let survivors=[];do{survivors=survivingTree(pids);if(!survivors.length)return;await sleep(250);}while(Date.now()<deadline);throw Error(`spawned process tree remained after close: ${JSON.stringify(survivors)}`);}
async function snapshot(page){return page.evaluate(()=>({url:location.href,title:document.title,text:(document.body?.innerText||'').slice(0,2000),html:(document.body?.innerHTML||'').slice(0,1000)})).catch(()=>({unavailable:true}));}
async function stageWait(run,name,predicate,timeout=30000){console.log(`E2E stage start: ${name}`);const deadline=Date.now()+timeout;while(Date.now()<deadline){if(run.child.exitCode!==null)throw Error(`${name}: app exited; child=${run.output().slice(-1500)}`);const state=await run.page.evaluate(predicate).catch(()=>null);if(state===true){console.log(`E2E stage pass: ${name}`);return;}if(state&&state.error)throw Error(`${name}: UI error=${state.error}; diagnostic=${JSON.stringify(await snapshot(run.page))}; child=${run.output().slice(-1500)}`);await sleep(250);}throw Error(`${name}: timeout; diagnostic=${JSON.stringify(await snapshot(run.page))}; child=${run.output().slice(-1500)}`);}
async function launch(userData,fixture,profileMode){if(!['fresh','existing-free'].includes(profileMode))throw Error('invalid E2E profile mode');const debugPort=await port(),diagnosticPath=path.join(userData,'e2e-phases.log'),electronLogPath=path.join(userData,'electron.log');const child=spawn(executable,launchArgs({userData,debugPort,logPath:electronLogPath}),{env:{...process.env,CI:'true',GROWTHMAP_DESKTOP_E2E:'1',GROWTHMAP_E2E_PROFILE_MODE:profileMode,GROWTHMAP_E2E_USER_DATA:userData,GROWTHMAP_E2E_IMPORT_PATH:fixture,GROWTHMAP_E2E_DIAGNOSTIC_PATH:diagnosticPath},stdio:['ignore','pipe','pipe'],windowsHide:true});let output='',directWebSocket=null;const capture=x=>{output+=x;directWebSocket=parseDevToolsWebSocket(output,debugPort);};child.stdout.on('data',capture);child.stderr.on('data',capture);let browser;const deadline=Date.now()+120000;while(Date.now()<deadline){if(child.exitCode!==null)throw Error(`app exited early: ${output.slice(-1500)}`);try{browser=await chromium.connectOverCDP(directWebSocket||`http://127.0.0.1:${debugPort}`,{timeout:2000});break;}catch{await sleep(250);}}if(!browser)throw Error(JSON.stringify(await timeoutDiagnostic({child,debugPort,output,diagnosticPath,electronLogPath}),null,2));let page;while(Date.now()<deadline&&!page){page=browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().startsWith('http://127.0.0.1:'));if(!page)await sleep(200);}if(!page)throw Error(`renderer page missing; child=${output.slice(-1500)}`);const run={child,browser,page,tree:descendants(child.pid),output:()=>output};await stageWait(run,'renderer-ready',()=>Boolean(document.querySelector('[data-testid="growthmap-title"]')&&document.querySelector('[data-testid="desktop-settings-button"]')),90000);return run;}
async function close(run){await run.page.close();const deadline=Date.now()+20000;while(run.child.exitCode===null&&Date.now()<deadline)await sleep(100);if(run.child.exitCode===null)throw Error('GrowthMap.exe did not exit');await run.browser.close().catch(()=>{});await waitForTreeGone(run.tree);}
async function assertCanonicalFixture(run,stage,expectedProjectName){
 const result=await run.page.evaluate(async({expectedProjectName})=>{
  const request=async(url,kind='json')=>{const response=await fetch(url,{credentials:'same-origin',headers:{Accept:kind==='text'?'text/markdown':'application/json'}});const body=kind==='text'?await response.text():await response.json().catch(async()=>({unparseable:await response.text().catch(()=>'<unreadable>')}));if(!response.ok)throw Error(`${url} HTTP ${response.status}: ${JSON.stringify(body).slice(0,500)}`);return body;};
  try{
   const project=await request('/api/projects/fixture'),root=await request('/api/nodes/root'),child=await request('/api/nodes/child');
   const nodes=await request('/api/projects/fixture/nodes'),edges=await request('/api/projects/fixture/edges?relation_type=child_of'),blocks=await request('/api/nodes/root/blocks'),markdown=await request('/api/projects/fixture/export','text');
   const failures=[];
   if(project.id!=='fixture'||project.name!==expectedProjectName||project.root_node_id!=='root')failures.push(`project=${JSON.stringify(project)}`);
   if(root.id!=='root'||root.project_id!=='fixture'||root.title!=='Root')failures.push(`root=${JSON.stringify(root)}`);
   if(child.id!=='child'||child.project_id!=='fixture'||child.title!=='Child')failures.push(`child=${JSON.stringify(child)}`);
   if(!nodes.some(node=>node.id==='root'&&node.title==='Root')||!nodes.some(node=>node.id==='child'&&node.title==='Child'))failures.push(`node-list=${JSON.stringify(nodes)}`);
   if(!edges.some(edge=>edge.id==='fixture-edge'&&edge.from_node_id==='root'&&edge.to_node_id==='child'&&edge.relation_type==='child_of'))failures.push(`edges=${JSON.stringify(edges)}`);
   if(!blocks.some(block=>block.id==='block'&&block.node_id==='root'&&block.content?.body==='fixture body'))failures.push(`blocks=${JSON.stringify(blocks)}`);
   for(const token of [expectedProjectName,'Root','Child','fixture body'])if(!markdown.includes(token))failures.push(`markdown missing ${JSON.stringify(token)}: ${markdown.slice(0,1000)}`);
   return failures.length?{error:failures.join('; ')}:{ok:true};
  }catch(error){return {error:error?.stack||String(error)};}
 },{expectedProjectName});
 if(!result?.ok)throw Error(`${stage}: packaged same-origin API fixture assertion failed: ${result?.error||JSON.stringify(result)}; diagnostic=${JSON.stringify(await snapshot(run.page))}; child=${run.output().slice(-1500)}`);
 console.log(`E2E stage pass: ${stage}`);
}
(async()=>{
 if(!fs.existsSync(executable))throw Error('packaged resources missing');
 const resources=path.join(path.dirname(executable),'resources');assertE2EPackage(path.join(resources,'app.asar'),resources);
 const userData=fs.mkdtempSync(path.join(os.tmpdir(),'growthmap-e2e-profile-'));
 const fixtureDirectory=fs.mkdtempSync(path.join(os.tmpdir(),'growthmap-e2e-input-')),fixture=path.join(fixtureDirectory,'fixture.sqlite');
 const helper=path.join(root,'scripts','create-e2e-fixture.py');
 let made=runPython([helper,fixture],{encoding:'utf8'});if(made.status!==0)throw Error(made.stderr);
 let run=await launch(userData,fixture,'fresh');
 try{
  await stageWait(run,'fresh-free',async()=>{const status=document.querySelector('[data-testid="entitlement-status"]')?.textContent||'';let entitlement;try{const response=await fetch('/api/desktop/entitlement');entitlement=response.ok?await response.json():{http_status:response.status};}catch(error){return {error:`entitlement request failed: ${error?.name||'Error'}`};}if(status.startsWith('Free ·')&&entitlement.state==='free'&&entitlement.valid===true&&entitlement.mutations_allowed===true)return true;if(status.includes('Read-only')||entitlement.state==='extraction')return {error:`unexpected entitlement: ui=${status}; state=${entitlement.state}; valid=${entitlement.valid}; mutations_allowed=${entitlement.mutations_allowed}; reason=${entitlement.reason}`};return false;},30000);
  for(const name of ['trial-marker.bin','installation-identity.bin','trial-state.json']){const target=path.join(userData,name);if(!fs.existsSync(target)||fs.statSync(target).size===0)throw Error(`fresh-free: missing initialized Free artifact ${name}`);}
  await run.page.getByTestId('desktop-settings-button').click();
  await run.page.getByTestId('llm-provider-settings').waitFor();
  if(await run.page.getByTestId('database-workspace').count()||await run.page.getByTestId('database-management').count())throw Error('database controls leaked into LLM Provider settings');
  await run.page.getByTestId('llm-provider-settings-close').click();
  await run.page.getByTestId('database-workspace-button').click();
  await run.page.getByTestId('database-workspace').waitFor();
  const initialPath=await run.page.getByTestId('database-path').textContent();
  if(!initialPath||!initialPath.toLowerCase().endsWith('growthmap.db'))throw Error(`database workspace did not expose canonical path: ${initialPath}`);
  run.page.once('dialog',d=>d.accept());
  await run.page.getByTestId('database-import').click();
  await stageWait(run,'import',()=>{const t=document.body.innerText;if(t.includes('Desktop Fixture'))return true;const e=document.querySelector('[data-testid="database-operation-message"]')?.textContent||'';return e?{error:e.slice(0,300)}:false;},90000);
  await assertCanonicalFixture(run,'import-canonical-api','Desktop Fixture');
  await run.page.getByTestId('database-workspace-button').click();
  await run.page.getByTestId('database-workspace').waitFor();
  await run.page.getByTestId('database-backup').click();
  await stageWait(run,'backup',()=>{const e=document.querySelector('[data-testid="database-operation-message"]')?.textContent||'';if(e.startsWith('✅'))return true;return e?{error:e.slice(0,300)}:false;},90000);
  fs.mkdirSync(path.dirname(screenshot),{recursive:true});await run.page.screenshot({path:screenshot,fullPage:true});
  await close(run);
  made=runPython(['-c',`import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);c.execute("update projects set name='Mutated Fixture'");c.commit();c.close()`,path.join(userData,'growthmap.db')],{encoding:'utf8'});if(made.status!==0)throw Error(made.stderr);
  run=await launch(userData,fixture,'existing-free');
  await stageWait(run,'restart-free',async()=>{const status=document.querySelector('[data-testid="entitlement-status"]')?.textContent||'';const response=await fetch('/api/desktop/entitlement');if(!response.ok)return {error:`entitlement HTTP ${response.status}`};const entitlement=await response.json();if(status.startsWith('Free ·')&&entitlement.state==='free'&&entitlement.valid===true&&entitlement.mutations_allowed===true)return true;return status.includes('Read-only')||entitlement.state==='extraction'?{error:`Free identity not preserved: ui=${status}; state=${entitlement.state}; valid=${entitlement.valid}; mutations_allowed=${entitlement.mutations_allowed}; reason=${entitlement.reason}`}:false;},30000);
  await stageWait(run,'mutated-restart',()=>document.body.innerText.includes('Mutated Fixture'),90000);
  await assertCanonicalFixture(run,'restart-canonical-api','Mutated Fixture');
  await run.page.getByTestId('database-workspace-button').click();
  await run.page.getByTestId('database-workspace').waitFor();
  run.page.once('dialog',d=>d.accept());
  await run.page.getByTestId('database-restore').first().click();
  await stageWait(run,'restore',()=>{const t=document.body.innerText;if(t.includes('Desktop Fixture')&&!t.includes('Mutated Fixture'))return true;const e=document.querySelector('[data-testid="database-operation-message"]')?.textContent||'';return e&&!e.startsWith('✅')?{error:e.slice(0,300)}:false;},90000);
  await assertCanonicalFixture(run,'restore-canonical-api','Desktop Fixture');
  await close(run);
  console.log(`Packaged database roundtrip/lifecycle E2E passed; screenshot=${screenshot}`);
 }finally{if(run?.child.exitCode===null)spawnSync('taskkill',['/PID',String(run.child.pid),'/T','/F'],{windowsHide:true});fs.rmSync(fixtureDirectory,{recursive:true,force:true});}
})().catch(e=>{console.error(e.stack||e);process.exit(1);});
