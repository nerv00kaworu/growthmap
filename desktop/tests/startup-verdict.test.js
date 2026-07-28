'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),cp=require('node:child_process'),path=require('node:path');
const {canonicalStartupVerdict,createStartupVerdict,startupVerdictEnv}=require('../startup-verdict');
const VECTOR={mode:'fresh',token:'0123456789abcdef'.repeat(4),nonce:'Win_SAFE-token_09-azAZ'.repeat(2),mac:'2fdcbbc1824a43ed234f23f911a38e71ae92536936b558b9dae2a56dee9f874d'};
test('fixed UTF-8/hex startup verdict vector is stable',()=>{
 assert.equal(canonicalStartupVerdict(VECTOR.mode,VECTOR.nonce),'growthmap-startup-v1:fresh:Win_SAFE-token_09-azAZWin_SAFE-token_09-azAZ');
 assert.deepEqual(createStartupVerdict(VECTOR),{mode:VECTOR.mode,nonce:VECTOR.nonce,mac:VECTOR.mac});
});
test('packaged-like policy to environment validates in Python with the identical token',()=>{
 const verdict=createStartupVerdict(VECTOR),env=startupVerdictEnv({verdict,token:VECTOR.token});
 assert.equal(env.GROWTHMAP_SESSION_TOKEN,VECTOR.token);
 const backend=path.resolve(__dirname,'../../src/backend');
 const python=process.env.PYTHON?path.resolve(process.env.PYTHON):(process.platform==='win32'?'python':'python3');
 const out=cp.spawnSync(python,['-c','from desktop.startup_verdict import verdict_validation; print(*verdict_validation())'],{cwd:backend,env:{...process.env,...env},encoding:'utf8'});
 assert.equal(out.status,0,out.stderr);assert.equal(out.stdout.trim(),'fresh valid');
});
