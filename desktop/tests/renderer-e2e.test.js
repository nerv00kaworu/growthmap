'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),http=require('node:http'),os=require('node:os'),path=require('node:path');
const {launchArgs,probeVersion,timeoutDiagnostic}=require('../scripts/renderer-e2e-support');

test('packaged E2E launch passes Chromium debug port directly and enables file logging',()=>{
 const args=launchArgs({userData:'C:\\temp\\profile',debugPort:43123,logPath:'C:\\temp\\electron.log'});
 assert.deepEqual(args,['--user-data-dir=C:\\temp\\profile','--remote-debugging-port=43123','--enable-logging','--log-file=C:\\temp\\electron.log']);
 const source=fs.readFileSync(path.join(__dirname,'../scripts/renderer-e2e.js'),'utf8');
 assert.match(source,/launchArgs\(\{userData,debugPort,logPath:electronLogPath\}\)/);
 assert.doesNotMatch(source,/GROWTHMAP_E2E_DEBUG_PORT/);
});

test('packaged E2E keeps import input outside the fresh profile and verifies trial writability',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../scripts/renderer-e2e.js'),'utf8'),entrypoint=fs.readFileSync(path.join(__dirname,'../e2e-main.js'),'utf8');
 assert.match(source,/growthmap-e2e-profile-/);assert.match(source,/growthmap-e2e-input-/);assert.doesNotMatch(source,/path\.join\(userData,'fixture\.sqlite'\)/);
 assert.match(source,/fresh-trial/);assert.match(source,/restart-trial/);assert.match(source,/mutations_allowed===true/);assert.match(source,/trial-marker\.bin/);assert.match(source,/installation-identity\.bin/);assert.match(source,/trial-state\.json/);
 assert.match(entrypoint,/E2E import fixture must be outside userData/);
});

test('import waits for production reload and authenticated replacement lifecycle',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../scripts/renderer-e2e.js'),'utf8');
 const start=source.indexOf("const oldSessionRequest");
 const end=source.indexOf("const agentPortEntry",start);
 const block=source.slice(start,end);
 assert.doesNotMatch(block,/waitForEvent\('domcontentloaded'/);
 assert.match(block,/preImportDocumentOrigin/);
 assert.match(block,/performance\.timeOrigin===beforeOrigin/);
 assert.match(block,/await run\.page\.getByTestId\('database-import'\)\.click\(\);/);
 assert.match(block,/import-rebootstrap/);
 assert.match(block,/new-session projects HTTP/);
 assert.match(block,/new-session subtree HTTP/);
 assert.match(block,/retired projects=401/);
 assert.match(block,/current projects=200/);
 assert.match(block,/post-import-fresh-trial/);
 assert.doesNotMatch(block,/force:\s*true|removeAttribute\(['"]disabled|document\.cookie|sessionStorage|localStorage|Authorization/);
});

test('packaged Agent Port fixture and harness semantically assert selectable current/stale implementation evidence',()=>{
 const {assertReadbackText}=require('../scripts/renderer-e2e-support'),target='22222222-2222-4222-8222-222222222222';
 const evidence=['digest aaaaaaaaaaaa','commits: ["abc123"]','files: ["src/feature.py"]','tests: [{"name":"packaged integration","status":"passed"}]','decisions: ["reuse strict v1 wire"]','risks: ["platform availability"]','todos: ["fresh review"]','evidence: [{"name":"diff","status":"verified","detail":"clean"}]'].join('\n');
 for(const [summary,state] of [['Packaged current implementation','current r1'],['Packaged stale implementation','stale · current r2']])assert.equal(assertReadbackText(`${summary}\n${state}\ntarget ${target}\n${evidence}`,{summary,state,target}),true);
 assert.throws(()=>assertReadbackText(`Packaged current implementation\ncurrent r1\ntarget ${target}`,{summary:'Packaged current implementation',state:'current r1',target}),/missing digest/);
 const fixture=fs.readFileSync(path.join(__dirname,'../scripts/create-e2e-fixture.py'),'utf8'),source=fs.readFileSync(path.join(__dirname,'../scripts/renderer-e2e.js'),'utf8');
 assert.match(fixture,/Packaged current implementation/);assert.match(fixture,/Packaged stale implementation/);assert.match(source,/top-about-growthmap-button/);assert.match(source,/月影塵 \(nerv00kaworu\)/);assert.match(source,/未知發行者/);assert.match(source,/manual-payment-visible/);assert.match(source,/0x81d30e175a22c1c2f78b3db6fc0600a6e1cb3591/);assert.match(source,/getByTestId\('agent-port-panel'\)/);assert.match(source,/agent-readbacks-loaded/);assert.match(source,/querySelectorAll\('\[data-testid="agent-readback-card"\]'\)/);assert.match(source,/activity expected 2 readbacks/);assert.match(source,/getByRole\('button',\{name:'22222222-2222-4222-8222-222222222222'\}\)\.click/);assert.match(source,/assertReadbackText/);
});

test('Agent Port harness accepts enabled production root invariant when root text is absent',async()=>{
 const {activateProjectForAgentPort}=require('../scripts/renderer-e2e-support'),calls=[],projectId='11111111-1111-4111-8111-111111111111';
 const entry={waitFor:async options=>{assert.deepEqual(options,{state:'visible',timeout:30000});calls.push('entry-visible');},isEnabled:async()=>{calls.push('entry-enabled');return true;}};
 const page={getByRole:()=>({selectOption:async option=>calls.push(`select:${option.value}`),inputValue:async()=>{calls.push('selected-value');return projectId;}}),getByText:()=>{throw Error('root absent');},getByTitle:()=>({click:async()=>calls.push('more-click')}),getByTestId:()=>entry};
 assert.equal(await activateProjectForAgentPort(page,{projectId,projectName:'Desktop Fixture'}),entry);
 assert.deepEqual(calls,[`select:${projectId}`,'selected-value','more-click','entry-visible','entry-enabled']);
 const source=fs.readFileSync(path.join(__dirname,'../scripts/renderer-e2e.js'),'utf8'),activateAt=source.indexOf('activateProjectForAgentPort(run.page'),activationBlock=source.slice(activateAt,source.indexOf("getByTestId('agent-port-panel')",activateAt));
 assert.ok(source.indexOf("stageWait(run,'import'")<activateAt);assert.doesNotMatch(activationBlock,/force:\s*true|removeAttribute\(['"]disabled|\.evaluate\(/);
});

test('Agent Port harness fails closed when no imported project was selected',async()=>{
 const {activateProjectForAgentPort}=require('../scripts/renderer-e2e-support');await assert.rejects(activateProjectForAgentPort({}, {projectId:'',projectName:'Desktop Fixture'}),/requires an imported project selection/);
});

function diagnosticPage({projectId,entry,calls,projectsStatus=200,projectsBody,subtreeStatus=200,subtreeBody='{"id":"root"}'}){
 const response=(status,body)=>({status:()=>status,text:async()=>body,ok:()=>status>=200&&status<300});
 return {getByRole:()=>({selectOption:async()=>calls.push('select'),inputValue:async()=>{calls.push('value-match');return projectId;}}),getByTitle:()=>({click:async()=>calls.push('more-click')}),getByTestId:id=>id==='agent-port-menu-entry'?entry:{allTextContents:async()=>{calls.push('visible-errors');return ['⚠️ API 503'];}},url:()=> 'http://127.0.0.1:43123/',request:{get:async url=>{if(url.endsWith('/api/projects')){calls.push('projects-diagnostic');return response(projectsStatus,projectsBody);}calls.push('subtree-diagnostic');return response(subtreeStatus,subtreeBody);}}};
}

test('Agent Port harness diagnoses failing subtree without clicking disabled entry',async()=>{
 const {activateProjectForAgentPort}=require('../scripts/renderer-e2e-support'),calls=[],projectId='11111111-1111-4111-8111-111111111111';let now=0;
 const entry={waitFor:async()=>calls.push('entry-visible'),isEnabled:async()=>{calls.push('entry-disabled');return false;},click:()=>{throw Error('disabled entry clicked');}};
 const projectsBody=JSON.stringify([{id:projectId,root_node_id:'22222222-2222-4222-8222-222222222222'}]),page=diagnosticPage({projectId,entry,calls,projectsBody,subtreeStatus:503,subtreeBody:'sidecar unavailable'}),clock={now:()=>now,sleep:async ms=>{calls.push('bounded-sleep');now+=ms;}};
 await assert.rejects(activateProjectForAgentPort(page,{projectId,projectName:'Desktop Fixture',timeout:5,clock}),error=>{assert.match(error.message,/"selectedProject":"11111111/);assert.match(error.message,/API 503/);assert.match(error.message,/"subtree":\{"status":503,"body":"sidecar unavailable"/);return true;});
 assert.deepEqual(calls,['select','value-match','more-click','entry-visible','entry-disabled','bounded-sleep','value-match','visible-errors','projects-diagnostic','subtree-diagnostic']);
});

test('Agent Port harness boundedly rejects when subtree succeeds but root invariant stays disabled',async()=>{
 const {activateProjectForAgentPort}=require('../scripts/renderer-e2e-support'),calls=[],projectId='11111111-1111-4111-8111-111111111111';let now=0;
 const entry={waitFor:async()=>{},isEnabled:async()=>false,click:()=>{throw Error('disabled entry clicked');}},projectsBody=JSON.stringify([{id:projectId,root_node_id:'22222222-2222-4222-8222-222222222222'}]),page=diagnosticPage({projectId,entry,calls,projectsBody,subtreeBody:'{"id":"22222222-2222-4222-8222-222222222222","title":"Desktop Fixture Root"}'}),clock={now:()=>now,sleep:async ms=>{now+=ms;}};
 await assert.rejects(activateProjectForAgentPort(page,{projectId,projectName:'Desktop Fixture',timeout:5,clock}),error=>{assert.match(error.message,/"subtree":\{"status":200/);assert.match(error.message,/Desktop Fixture Root/);return true;});
});

test('CDP version probe records HTTP response and connection errors',async()=>{
 const server=http.createServer((request,response)=>{assert.equal(request.url,'/json/version');response.writeHead(200,{'content-type':'application/json'});response.end('{"Browser":"test"}');});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const port=server.address().port,good=await probeVersion(port);
 assert.equal(good.statusCode,200);assert.equal(good.body,'{"Browser":"test"}');
 await new Promise(resolve=>server.close(resolve));
 const bad=await probeVersion(port,100);
 assert.equal(typeof bad.error,'string');assert.ok(bad.error.trim());assert.doesNotMatch(bad.error,/\r|\n/);
 assert.match(bad.error,/ECONNREFUSED|ECONNRESET|socket hang up/);
});

test('CDP timeout diagnostic includes process state, tree, streams, probe, phases and Electron log',async()=>{
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),'gm-e2e-diagnostic-')),phases=path.join(directory,'phases.log'),electronLog=path.join(directory,'electron.log');
 fs.writeFileSync(phases,'entrypoint-loaded\n');fs.writeFileSync(electronLog,'chromium-log\n');
 const diagnostic=await timeoutDiagnostic({child:{pid:991337,exitCode:null,signalCode:null,killed:false},debugPort:1,output:'app-output',diagnosticPath:phases,electronLogPath:electronLog});
 assert.equal(diagnostic.message,'CDP timeout');assert.equal(diagnostic.pid,991337);assert.equal(diagnostic.exitCode,null);
 assert.ok(diagnostic.processTree);assert.match(diagnostic.probe.error,/ECONNREFUSED|EACCES/);assert.equal(diagnostic.stdoutStderr,'app-output');assert.match(diagnostic.phases,/entrypoint-loaded/);assert.match(diagnostic.electronLog,/chromium-log/);
});

test('isolated builder config replaces production exclusion and exports only builder keys',()=>{
 const pkg=require('../package.json'),e2e=require('../scripts/e2e-builder-config'),support=require('../scripts/e2e-config-support');
 assert.deepEqual(Object.keys(e2e).sort(),[...Object.keys(pkg.build),'extraMetadata'].sort());
 assert.deepEqual(Object.keys(support).sort(),['generateE2ECommercialConfig','sha256']);
 assert.equal(e2e.generateE2ECommercialConfig,undefined);assert.equal(e2e.sha256,undefined);
 assert.equal(e2e.extraMetadata.main,'e2e-main.js');assert(e2e.files.includes('e2e-main.js'));assert(e2e.files.includes('e2e-commercial-config.js'));assert(!e2e.files.includes('!e2e-main.js'));
 assert(e2e.extraResources.some(x=>path.isAbsolute(x.from)&&x.to==='commercial-config.json'));
 assert(pkg.build.files.includes('!e2e-main.js'));assert(!pkg.build.files.includes('e2e-main.js'));assert(!pkg.build.files.includes('e2e-commercial-config.js'));
 assert.equal(pkg.main,'main.js');assert.match(pkg.scripts['dist:win:e2e'],/--config scripts\/e2e-builder-config\.js/);
});

test('builder hashes exact packaged E2E key bytes for LF and CRLF checkouts',()=>{
 const {generateE2ECommercialConfig,sha256}=require('../scripts/e2e-config-support'),templatePath=path.join(__dirname,'../e2e/commercial-config.json');
 for(const newline of ['\n','\r\n']){
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'gm-e2e-builder-test-')),keyPath=path.join(directory,'source.pem'),resourcesPath=path.join(directory,'resources');
  fs.writeFileSync(keyPath,['-----BEGIN PUBLIC KEY-----','test-key-bytes','-----END PUBLIC KEY-----',''].join(newline),'utf8');
  const generated=generateE2ECommercialConfig({templatePath,keyPath,outputDirectory:path.join(directory,'generated')});
  const configResource=path.join(resourcesPath,'commercial-config.json'),keyResource=path.join(resourcesPath,generated.config.licensePublicKeyResource);
  fs.mkdirSync(path.dirname(keyResource),{recursive:true});fs.copyFileSync(generated.configPath,configResource);fs.copyFileSync(generated.keyPath,keyResource);
  const packagedConfig=JSON.parse(fs.readFileSync(configResource,'utf8'));
  assert.equal(packagedConfig.licensePublicKeySha256,sha256(fs.readFileSync(keyResource)));
  assert.deepEqual(fs.readFileSync(keyResource),fs.readFileSync(keyPath));
 }
});

test('DevTools websocket parser accepts only requested loopback port and browser target',()=>{
 const {parseDevToolsWebSocket}=require('../scripts/renderer-e2e-support');
 const valid='ws://127.0.0.1:43123/devtools/browser/f88db40d-e8a1-4639-ae7c-a2940918540b';
 assert.equal(parseDevToolsWebSocket(`noise\nDevTools listening on ${valid}\n`,43123),valid);
 for(const output of [
  'DevTools listening on ws://127.0.0.1:43124/devtools/browser/f88db40d-e8a1-4639-ae7c-a2940918540b',
  'DevTools listening on ws://evil.test:43123/devtools/browser/f88db40d-e8a1-4639-ae7c-a2940918540b',
  'DevTools listening on ws://127.0.0.1:43123/devtools/page/f88db40d-e8a1-4639-ae7c-a2940918540b',
 ])assert.equal(parseDevToolsWebSocket(output,43123),null);
});
