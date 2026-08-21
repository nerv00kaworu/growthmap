const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{EventEmitter}=require('node:events');const {createLifecycle,probeSpawnOptions,sidecarSpawnOptions}=require('../lifecycle');
function child(pid=42){const c=new EventEmitter();c.pid=pid;c.exitCode=null;c.signalCode=null;c.kills=[];c.kill=s=>{c.kills.push(s);};return c;}
test('shutdown is single-flight, rejects new IPC and bounded-kills POSIX tree',async()=>{const c=child(),signals=[],l=createLifecycle({platform:'linux',graceMs:5,killMs:5});const original=process.kill;process.kill=(pid,s)=>signals.push([pid,s]);try{l.attach(c);let closes=0;await Promise.all([l.shutdown(()=>closes++),l.shutdown(()=>closes++)]);assert.equal(closes,1);assert.equal(l.acceptingIpc,false);assert.deepEqual(signals,[[-42,'SIGTERM'],[-42,'SIGKILL']]);}finally{process.kill=original;}});
test('startup retry cleanup terminates each failed Windows process tree once',async()=>{const c=child(),calls=[],l=createLifecycle({platform:'win32',spawn:(_x,args)=>{calls.push(args);const p=new EventEmitter();p.once=()=>p;return p;},graceMs:1,killMs:1});l.attach(c);await l.cleanup(c);assert.equal(c.kills.length,0);assert.equal(calls.length,1);assert.deepEqual(calls[0],['/PID','42','/T','/F']);});
test('Windows cleanup always awaits taskkill tree even after bootloader parent exits',async()=>{
 const child=new EventEmitter();child.pid=4242;child.exitCode=0;child.signalCode=null;
 const calls=[];const fakeSpawn=(command,args)=>{calls.push([command,args]);const killer=new EventEmitter();setImmediate(()=>killer.emit('exit',0));return killer;};
 const lifecycle=createLifecycle({platform:'win32',spawn:fakeSpawn,graceMs:20,killMs:20});
 lifecycle.attach(child);await lifecycle.cleanup(child);
 assert.deepEqual(calls,[['taskkill',['/PID','4242','/T','/F']]]);
});

test('already exited/crashed child needs no tree kill',async()=>{const c=child();c.exitCode=1;const l=createLifecycle({graceMs:1});l.attach(c);await l.cleanup(c);assert.deepEqual(c.kills,[]);});

test('entitlement probes capture bounded output while production sidecars never expose stderr via ambient CI',()=>{
 assert.deepEqual(probeSpawnOptions('win32'),{detached:false,windowsHide:true,stdio:['ignore','pipe','pipe']});
 assert.deepEqual(sidecarSpawnOptions('win32'),{detached:false,windowsHide:true,stdio:['ignore','ignore','ignore']});
 const source=fs.readFileSync(path.join(__dirname,'../main.js'),'utf8');
 assert.match(source,/--entitlement-status[\s\S]*probeSpawnOptions\(\)/);
 assert.match(source,/const spawnOptions=sidecarSpawnOptions\(\)/);
 assert.doesNotMatch(source,/process\.env\.CI|spawnOptions\.stdio=\['ignore','ignore','pipe'\]/);
 assert.match(source,/lifecycle\.attach\(spawn\(executable\(\),\[\],\{env,\.\.\.spawnOptions\}\)\)/);
 assert.match(source,/if\(!child\.stdout\|\|!child\.stderr\)return reject/);
});
