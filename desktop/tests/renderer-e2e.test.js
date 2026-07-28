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

test('isolated builder config replaces production exclusion and production config remains closed',()=>{
 const pkg=require('../package.json'),e2e=require('../scripts/e2e-builder-config');
 assert.equal(e2e.extraMetadata.main,'e2e-main.js');assert(e2e.files.includes('e2e-main.js'));assert(e2e.files.includes('e2e-commercial-config.js'));assert(!e2e.files.includes('!e2e-main.js'));
 assert(e2e.extraResources.some(x=>x.from==='e2e/commercial-config.json'&&x.to==='commercial-config.json'));
 assert(pkg.build.files.includes('!e2e-main.js'));assert(!pkg.build.files.includes('e2e-main.js'));assert(!pkg.build.files.includes('e2e-commercial-config.js'));
 assert.equal(pkg.main,'main.js');assert.match(pkg.scripts['dist:win:e2e'],/--config scripts\/e2e-builder-config\.js/);
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
