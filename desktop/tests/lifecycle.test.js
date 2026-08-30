const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{EventEmitter}=require('node:events');const {createLifecycle,probeSpawnOptions,sidecarSpawnOptions,signalTree}=require('../lifecycle');
function child(pid=42){const c=new EventEmitter();c.pid=pid;c.exitCode=null;c.signalCode=null;c.kills=[];c.kill=s=>{c.kills.push(s);};return c;}
test('shutdown is single-flight, rejects new IPC and bounded-kills POSIX tree',async()=>{const c=child(),signals=[],l=createLifecycle({platform:'linux',graceMs:5,killMs:5});const original=process.kill;process.kill=(pid,s)=>signals.push([pid,s]);try{l.attach(c);let closes=0;await Promise.all([l.shutdown(()=>closes++),l.shutdown(()=>closes++)]);assert.equal(closes,1);assert.equal(l.acceptingIpc,false);assert.deepEqual(signals,[[-42,'SIGTERM'],[-42,'SIGKILL']]);}finally{process.kill=original;}});
test('startup retry cleanup uses trusted absolute taskkill with restricted env',async()=>{const c=child(),calls=[],l=createLifecycle({platform:'win32',env:{SystemRoot:'C:\\Windows',PATH:'hostile'},spawn:(...args)=>{calls.push(args);const p=new EventEmitter();p.once=()=>p;return p;},graceMs:1,killMs:1});l.attach(c);await l.cleanup(c);assert.equal(c.kills.length,0);assert.deepEqual(calls,[['C:\\Windows\\System32\\taskkill.exe',['/PID','42','/T','/F'],{stdio:'ignore',windowsHide:true,env:{SystemRoot:'C:\\Windows',WINDIR:'C:\\Windows'}}]]);});
test('Windows signal path uses trusted absolute taskkill and restricted env',()=>{const c=child(),calls=[];signalTree(c,'SIGTERM','win32',(...args)=>{calls.push(args);return Object.assign(new EventEmitter(),{once(){return this}})},{SystemRoot:'D:\\Windows',PATH:'hostile'});assert.deepEqual(calls,[['D:\\Windows\\System32\\taskkill.exe',['/PID','42','/T','/F'],{stdio:'ignore',windowsHide:true,env:{SystemRoot:'D:\\Windows',WINDIR:'D:\\Windows'}}]])});
test('confirmed Windows cleanup fails closed without trusted SystemRoot',async()=>{const c=child(),l=createLifecycle({platform:'win32',env:{PATH:'hostile'},spawn:()=>assert.fail('must not spawn'),graceMs:1,killMs:1});l.attach(c);await assert.rejects(l.cleanupConfirmed(),{code:'SIDECAR_STOP_UNCONFIRMED'});assert.equal(l.child,c)});
test('Windows cleanup does not taskkill an already-exited tracked PID',async()=>{
 const child=new EventEmitter();child.pid=4242;child.exitCode=0;child.signalCode=null;
 const calls=[];const fakeSpawn=(command,args)=>{calls.push([command,args]);const killer=new EventEmitter();setImmediate(()=>killer.emit('exit',0));return killer;};
 const lifecycle=createLifecycle({platform:'win32',env:{SystemRoot:'C:\\Windows'},spawn:fakeSpawn,graceMs:20,killMs:20});
 lifecycle.attach(child);await lifecycle.cleanup(child);
 assert.deepEqual(calls,[]);assert.equal(lifecycle.child,null);
});

test('confirmed Windows cleanup fails closed and retains child when taskkill nonzero or parent exit is unconfirmed',async()=>{for(const mode of ['taskkill','parent']){const c=child(),l=createLifecycle({platform:'win32',env:{SystemRoot:'C:\\Windows'},spawn:()=>{const p=new EventEmitter();setImmediate(()=>p.emit('exit',mode==='taskkill'?1:0));return p},graceMs:2,killMs:2});l.attach(c);if(mode==='parent')setTimeout(()=>{},1);await assert.rejects(l.cleanupConfirmed(),{code:'SIDECAR_STOP_UNCONFIRMED'});assert.equal(l.child,c)}});
test('confirmed Windows cleanup clears child only after taskkill exit 0 and parent exit are both confirmed',async()=>{const c=child(),l=createLifecycle({platform:'win32',env:{SystemRoot:'C:\\Windows'},spawn:()=>{const p=new EventEmitter();setImmediate(()=>{p.emit('exit',0);c.exitCode=0;c.emit('exit',0)});return p},graceMs:5,killMs:5});l.attach(c);assert.equal(await l.cleanupConfirmed(),true);assert.equal(l.child,null)});
test('already exited/crashed child needs no tree kill',async()=>{const c=child();c.exitCode=1;const l=createLifecycle({graceMs:1});l.attach(c);await l.cleanup(c);assert.deepEqual(c.kills,[]);});
test('confirmed Windows cleanup clears an exited tracked child without taskkill stale PID',async()=>{const c=child(),calls=[];c.exitCode=1;const l=createLifecycle({platform:'win32',env:{SystemRoot:'C:\\Windows'},spawn:(...args)=>{calls.push(args);throw Error('must not taskkill')}});l.attach(c);assert.equal(await l.cleanupConfirmed(),true);assert.equal(l.child,null);assert.deepEqual(calls,[])});

test('entitlement probes capture bounded output while production sidecars never expose stderr via ambient CI',()=>{
 assert.deepEqual(probeSpawnOptions('win32'),{detached:false,windowsHide:true,stdio:['ignore','pipe','pipe']});
 assert.deepEqual(sidecarSpawnOptions('win32'),{detached:false,windowsHide:true,stdio:['ignore','ignore','ignore']});
 const source=fs.readFileSync(path.join(__dirname,'../main.js'),'utf8'),e2e=fs.readFileSync(path.join(__dirname,'../e2e-main.js'),'utf8');
 assert.match(source,/--entitlement-status[\s\S]*probeSpawnOptions\(\)/);
 assert.match(e2e,/enableIsolatedE2EDiagnostics\(name=>phase\(name\)\)/);
 assert.doesNotMatch(source,/process\.env\.CI|GROWTHMAP_DESKTOP_E2E/);
 assert.match(source,/const spawnOptions=sidecarSpawnOptions\(\)/);
 assert.doesNotMatch(source,/spawnOptions\.stdio=\['ignore','ignore','pipe'\]/);
 assert.match(source,/lifecycle\.attach\(spawn\(executable\(\),\[\],\{env,\.\.\.spawnOptions\}\)\)/);
 assert.match(source,/if\(!child\.stdout\|\|!child\.stderr\)return reject/);
});

test('isolated E2E entrypoint capability explicitly enables bounded sidecar stderr and fixed stage reporting',()=>{
 const script="const l=require('./lifecycle'),stages=[];l.enableIsolatedE2EDiagnostics(name=>stages.push(name));l.reportIsolatedE2EStage('replacement-restart-prepare-enter');process.stdout.write(JSON.stringify({options:l.sidecarSpawnOptions('win32'),stages}))";
 const result=require('node:child_process').spawnSync(process.execPath,['-e',script],{cwd:path.resolve(__dirname,'..'),encoding:'utf8'});
 assert.equal(result.status,0,result.stderr);assert.deepEqual(JSON.parse(result.stdout),{options:{detached:false,windowsHide:true,stdio:['ignore','ignore','pipe']},stages:['replacement-restart-prepare-enter']});
});
test('isolated E2E stage reporter exceptions are fail-open and production default is inert',()=>{const script="const l=require('./lifecycle');l.reportIsolatedE2EStage('ignored');l.enableIsolatedE2EDiagnostics(()=>{throw Error('hostile')});l.reportIsolatedE2EStage('ignored-again');process.stdout.write('ok')";const result=require('node:child_process').spawnSync(process.execPath,['-e',script],{cwd:path.resolve(__dirname,'..'),encoding:'utf8'});assert.equal(result.status,0,result.stderr);assert.equal(result.stdout,'ok')});
