'use strict';
const fs=require('node:fs'),path=require('node:path');
const {parseStrictJson}=require('./strict-json');
const FILE='database-workspace.json',SCHEMA=1,CLOUD_SEGMENTS=new Set(['onedrive','dropbox','google drive','icloud drive']);
function manifestPath(userData){return path.join(userData,FILE);}
function validateWorkspaceDirectory(input,{platform=process.platform,fsImpl=fs}={}){
 if(typeof input!=='string'||!input.trim())throw Error('database workspace path is required');
 const resolved=path.resolve(input);
 if(platform==='win32'){
  if(/^\\\\/.test(input)||/^\\\\[?.]\\/.test(input))throw Error('UNC and WSL database workspaces are not allowed');
  const parsed=path.win32.parse(resolved);if(!/^[A-Za-z]:\\$/.test(parsed.root))throw Error('database workspace must be on a local Windows drive');
  const lower=resolved.toLowerCase().split(/[\\/]+/);if(lower.some(segment=>CLOUD_SEGMENTS.has(segment)))throw Error('cloud-synchronized database workspaces are not allowed');
 }
 const stat=fsImpl.lstatSync(resolved);if(!stat.isDirectory()||stat.isSymbolicLink())throw Error('database workspace must be a real directory');
 const real=fsImpl.realpathSync(resolved);if(platform==='win32'&&/^\\\\/.test(real))throw Error('network database workspaces are not allowed');
 return real;
}
function readWorkspace(userData,{fsImpl=fs}={}){
 const fallback=path.resolve(userData),file=manifestPath(userData);if(!fsImpl.existsSync(file))return {directory:fallback,databasePath:path.join(fallback,'growthmap.db'),isDefault:true};
 try{const doc=parseStrictJson(fsImpl.readFileSync(file,'utf8'));if(Object.keys(doc).sort().join('\0')!=='directory\0schemaVersion'||doc.schemaVersion!==SCHEMA)throw Error();const directory=validateWorkspaceDirectory(doc.directory,{fsImpl});return {directory,databasePath:path.join(directory,'growthmap.db'),isDefault:directory===fallback};}catch{throw Error('Saved database workspace is invalid; GrowthMap refuses to guess a database path');}
}
function writeWorkspace(userData,directory,{fsImpl=fs}={}){
 const safe=validateWorkspaceDirectory(directory,{fsImpl}),file=manifestPath(userData),temp=`${file}.tmp-${process.pid}-${Date.now()}`;fsImpl.writeFileSync(temp,JSON.stringify({schemaVersion:SCHEMA,directory:safe},null,2),{encoding:'utf8',mode:0o600,flag:'wx'});fsImpl.renameSync(temp,file);return safe;
}
module.exports={validateWorkspaceDirectory,readWorkspace,writeWorkspace,manifestPath};
