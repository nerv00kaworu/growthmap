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

test('packaged E2E has an independent hard deadline with phase evidence and owned-tree cleanup',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../scripts/renderer-e2e.js'),'utf8');
 assert.match(source,/const HARD_TIMEOUT_MS=7\*60\*1000/);assert.match(source,/E2E hard timeout after \$\{HARD_TIMEOUT_MS\}ms; phase=\$\{currentPhase\}/);assert.match(source,/process\.exit\(124\)/);assert.match(source,/function killOwnedTree\(child=activeChild\)/);assert.doesNotMatch(source,/taskkill.*\/IM/is);
});

test('packaged E2E pre-return launch failures close CDP and kill only the spawned process tree',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../scripts/renderer-e2e.js'),'utf8');
 assert.match(source,/async function abortLaunch\(child,browser,pids\)/);
 assert.match(source,/browser\?\.close\(\)\.catch/);
 assert.match(source,/taskkill.*\/PID.*String\(pid\).*\/T.*\/F/s);
 assert.match(source,/catch\(error\)\{await abortLaunch\(child,browser,pids\);throw error;\}/);
 assert.doesNotMatch(source,/taskkill.*\/IM|growthmap-sidecar\.exe.*taskkill/is);
});

test('packaged E2E keeps import input outside the fresh profile and verifies Free writability',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../scripts/renderer-e2e.js'),'utf8'),entrypoint=fs.readFileSync(path.join(__dirname,'../e2e-main.js'),'utf8');
 assert.match(source,/growthmap-e2e-profile-/);assert.match(source,/growthmap-e2e-input-/);assert.doesNotMatch(source,/path\.join\(userData,'fixture\.sqlite'\)/);
 assert.match(source,/let made=runPython\(\[helper,fixture\]/);assert.doesNotMatch(source,/spawnSync\(['"]python['"]/);
 assert.match(source,/fresh-free/);assert.match(source,/restart-free/);assert.match(source,/mutations_allowed===true/);assert.match(source,/trial-marker\.bin/);assert.match(source,/installation-identity\.bin/);assert.match(source,/trial-state\.json/);
 assert.match(source,/launch\(userData,fixture,'fresh'\)/);assert.match(source,/launch\(userData,fixture,'existing-free'\)/);assert.match(source,/GROWTHMAP_E2E_PROFILE_MODE:profileMode/);
 assert.match(entrypoint,/E2E import fixture must be outside userData/);
 const bind=entrypoint.indexOf("app.setPath('userData',realProfile)"),production=entrypoint.indexOf("require('./main')");assert.ok(bind>=0&&bind<production,'test profile must bind before production main loads');
 assert.match(entrypoint,/direct real system-temp child/);assert.match(entrypoint,/profileMode==='fresh'/);assert.match(entrypoint,/Existing-Free E2E profile is missing lifecycle artifact/);for(const artifact of ['trial-marker.bin','installation-identity.bin','trial-state.json','growthmap.db','database-workspace.json','update-pending.json','migration-authorization.json','backups'])assert.ok(entrypoint.includes(artifact),artifact);
 assert.doesNotMatch(fs.readFileSync(path.join(__dirname,'../main.js'),'utf8'),/GROWTHMAP_E2E_USER_DATA|growthmap-e2e-profile-/);
});

test('packaged E2E proves broker-unavailable import is isolated from normal app health, backup, and restart',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../scripts/renderer-e2e.js'),'utf8');
 for(const token of ['import-safely-unavailable','beforeImport','afterImport','/api/health/deep','database-backup','restart-free','assertRestartCredential'])assert.ok(source.includes(token),token);
 assert.doesNotMatch(source,/import-canonical-api|restore-canonical-api|mutated-restart/);
});

test('Python runner resolves once and uses the same supplied interpreter for every subprocess',()=>{
 const {pythonRunner}=require('../scripts/renderer-e2e-support'),calls=[];
 const run=pythonRunner({env:{GROWTHMAP_TEST_PYTHON:'C:\\qa\\python.exe',PYTHON:'C:\\other\\python.exe'},spawnSync:(...args)=>{calls.push(args);return{status:0}}});
 assert.equal(run.interpreter,'C:\\qa\\python.exe');calls.length=0;run(['fixture.py','fixture.sqlite'],{encoding:'utf8'});run(['-c','mutate','growthmap.db'],{encoding:'utf8'});
 assert.deepEqual(calls.map(call=>call[0]),['C:\\qa\\python.exe','C:\\qa\\python.exe']);
 assert.deepEqual(calls.map(call=>call[1][0]),['fixture.py','-c']);
});

test('Windows GitHub runner resolves setup-python root and uses launcher prefix semantics',()=>{
 const {resolvePython,runPython}=require('../scripts/python-interpreter'),calls=[],root='C:\\hostedtoolcache\\windows\\Python\\3.12.4\\x64',exe=`${root}\\python.exe`;
 const spawnSync=(...args)=>{calls.push(args);return{status:args[0]===exe?0:1,stderr:''}};
 const resolved=resolvePython({platform:'win32',env:{CI:'true',Python3_ROOT_DIR:root},backendRoot:'D:\\a\\GrowthMap\\GrowthMap\\src\\backend',fsImpl:{existsSync:value=>value===exe},spawnSync});
 assert.deepEqual(resolved,{executable:exe,prefixArgs:[],source:'Python3_ROOT_DIR'});
 runPython(spawnSync,resolved,['fixture.py'],{});assert.deepEqual(calls.at(-1).slice(0,2),[exe,['fixture.py']]);
 const launcherCalls=[],launcher=resolvePython({platform:'win32',env:{},fsImpl:{existsSync:()=>false},spawnSync:(command,args)=>{launcherCalls.push([command,args]);return{status:command==='py'?0:1,stderr:''}}});
 assert.deepEqual(launcher.prefixArgs,['-3']);assert.deepEqual(launcherCalls.at(-1),['py',['-3','-c','import sqlite3,sys; assert sys.version_info >= (3, 10)']]);
});

test('backend override must probe successfully and null spawn diagnostics expose the spawn error',()=>{
 const {resolveBackendPython}=require('../scripts/python-interpreter'),fallback={executable:'python',prefixArgs:[],source:'PATH'};
 assert.throws(()=>resolveBackendPython(fallback,{env:{GROWTHMAP_TEST_BACKEND_PYTHON:'C:\\missing\\python.exe'},spawnSync:()=>({status:null,stderr:'',error:Object.assign(new Error('file not found'),{code:'ENOENT'})})}),error=>{
  assert.match(error.message,/status=null/);assert.match(error.message,/ENOENT: file not found/);assert.match(error.message,/C:\\\\missing\\\\python\.exe/);assert.match(error.message,/stderr=""/);return true;
 });
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
