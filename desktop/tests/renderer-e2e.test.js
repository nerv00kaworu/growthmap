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
 assert.match(source,/process\.env\.GROWTHMAP_TEST_PYTHON\|\|process\.env\.PYTHON\|\|'python'/);assert.doesNotMatch(source,/spawnSync\('python',\[helper,fixture\]/);
 assert.match(source,/fresh-trial/);assert.match(source,/restart-trial/);assert.match(source,/mutations_allowed===true/);assert.match(source,/trial-marker\.bin/);assert.match(source,/installation-identity\.bin/);assert.match(source,/trial-state\.json/);
 assert.match(entrypoint,/E2E import fixture must be outside userData/);
});

test('packaged E2E pins canonical fixture reads and Markdown through same-origin app API',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../scripts/renderer-e2e.js'),'utf8');
 assert.match(source,/fetch\(url,\{credentials:'same-origin'/);
 for(const route of ['/api/projects/fixture','/api/nodes/root','/api/nodes/child','/api/projects/fixture/nodes','/api/projects/fixture/edges?relation_type=child_of','/api/nodes/root/blocks','/api/projects/fixture/export'])assert.ok(source.includes(route),route);
 for(const token of ['fixture-edge','from_node_id','to_node_id','child_of','fixture body','import-canonical-api','restart-canonical-api','restore-canonical-api'])assert.ok(source.includes(token),token);
 const assertionBody=source.slice(source.indexOf('async function assertCanonicalFixture'),source.indexOf('(async()=>'));
 assert.doesNotMatch(assertionBody,/sqlite3|fixture\.sqlite|growthmap\.db/);
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
