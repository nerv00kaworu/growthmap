'use strict';
const fs=require('node:fs'),path=require('node:path'),childProcess=require('node:child_process');

function platformPath(platform){return platform==='win32'?path.win32:path;}
function candidate(executable,prefixArgs=[],source='PATH'){return {executable,prefixArgs,source};}
function probePython(value,{spawnSync=childProcess.spawnSync}={}){
 const result=spawnSync(value.executable,[...value.prefixArgs,'-c','import sqlite3,sys; assert sys.version_info >= (3, 10)'],{encoding:'utf8',windowsHide:true});
 return {ok:result.status===0,result};
}
function describeSpawn(result,value){
 const error=result?.error,stderr=String(result?.stderr||'').trim();
 return `executable=${JSON.stringify(value.executable)} prefixArgs=${JSON.stringify(value.prefixArgs)} status=${String(result?.status)} error=${error?`${error.code||error.name||'Error'}: ${error.message}`:'none'} stderr=${JSON.stringify(stderr)}`;
}
function pythonCandidates({env=process.env,platform=process.platform,backendRoot,fsImpl=fs}={}){
 const p=platformPath(platform),bin=platform==='win32'?'Scripts\\python.exe':'bin/python',values=[];
 const add=(value,prefixArgs=[],source='PATH',mustExist=false)=>{if(!value||mustExist&&!fsImpl.existsSync(value))return;values.push(candidate(value,prefixArgs,source));};
 add(env.GROWTHMAP_TEST_PYTHON,[],'GROWTHMAP_TEST_PYTHON');
 add(env.PYTHON,[],'PYTHON');
 if(env.VIRTUAL_ENV)add(p.resolve(env.VIRTUAL_ENV,bin),[],'VIRTUAL_ENV',true);
 if(platform==='win32'){
  if(env.Python3_ROOT_DIR)add(p.resolve(env.Python3_ROOT_DIR,'python.exe'),[],'Python3_ROOT_DIR',true);
  if(env.Python_ROOT_DIR)add(p.resolve(env.Python_ROOT_DIR,'python.exe'),[],'Python_ROOT_DIR',true);
 }
 if(backendRoot)add(p.resolve(backendRoot,'venv',bin),[],'repo venv',true);
 add('python',[],'PATH');add('python3',[],'PATH');
 if(platform==='win32')add('py',['-3'],'PATH py launcher');
 const seen=new Set();return values.filter(value=>{const key=JSON.stringify([value.executable,value.prefixArgs]);if(seen.has(key))return false;seen.add(key);return true;});
}
function resolvePython(options={}){
 const failures=[];
 for(const value of pythonCandidates(options)){const probe=probePython(value,options);if(probe.ok)return value;failures.push(describeSpawn(probe.result,value));}
 throw Error(`No supported Python interpreter was found. Probes: ${failures.join(' | ')}`);
}
function resolveBackendPython(defaultPython,{env=process.env,...options}={}){
 if(!env.GROWTHMAP_TEST_BACKEND_PYTHON)return defaultPython;
 const value=candidate(env.GROWTHMAP_TEST_BACKEND_PYTHON,[],'GROWTHMAP_TEST_BACKEND_PYTHON'),probe=probePython(value,options);
 if(probe.ok)return value;
 throw Error(`GROWTHMAP_TEST_BACKEND_PYTHON is unavailable or unsupported: ${describeSpawn(probe.result,value)}`);
}
function runPython(spawnSync,value,args,options){return spawnSync(value.executable,[...value.prefixArgs,...args],options);}
module.exports={pythonCandidates,probePython,resolvePython,resolveBackendPython,runPython,describeSpawn};
