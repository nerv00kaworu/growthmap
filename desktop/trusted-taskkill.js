'use strict';
const path=require('node:path');
const {spawn:defaultSpawn}=require('node:child_process');

const INVALID_SEGMENT_CHAR=/[\x00-\x1f\x7f"<>:|?*]/;
const WINDOWS_DOS_DEVICE_NAME=/^(?:CON|PRN|AUX|NUL|CLOCK\$|COM[1-9¹²³]|LPT[1-9¹²³])$/i;

function isWindowsDosDeviceName(segment){
 // Win32 ignores spaces immediately before the first extension separator when
 // resolving DOS device aliases (for example, `CON .txt`).
 return WINDOWS_DOS_DEVICE_NAME.test(segment.split('.',1)[0].replace(/ +$/,''));
}

function trustedWindowsRoot(env=process.env){
 const raw=env&&env.SystemRoot;
 if(typeof raw!=='string'||!raw)throw new Error('Trusted Windows SystemRoot is unavailable');
 // Accept only canonical DOS drive-absolute paths. In particular, do not let
 // win32.normalize reinterpret UNC/device, root-relative, drive-relative, mixed
 // separator, repeated-separator, or dot-segment input.
 if(!/^[A-Za-z]:\\/.test(raw)||raw.includes('/')||raw.endsWith('\\'))throw new Error('Trusted Windows SystemRoot is invalid');
 const segments=raw.slice(3).split('\\');
 if(!segments.length||segments.some(segment=>!segment||segment==='.'||segment==='..'||INVALID_SEGMENT_CHAR.test(segment)||/[ .]$/.test(segment)||isWindowsDosDeviceName(segment)))throw new Error('Trusted Windows SystemRoot is invalid');
 const root=`${raw[0].toUpperCase()}:\\${segments.join('\\')}`;
 if(path.win32.normalize(root)!==root||path.win32.parse(root).root!==`${root.slice(0,2)}\\`)throw new Error('Trusted Windows SystemRoot is invalid');
 return root;
}
function resolveTrustedTaskkill(env=process.env){return path.win32.join(trustedWindowsRoot(env),'System32','taskkill.exe');}
function spawnTrustedTaskkill(pid,{spawn=defaultSpawn,env=process.env,stdio='ignore'}={}){
 const root=trustedWindowsRoot(env),executable=path.win32.join(root,'System32','taskkill.exe');
 return spawn(executable,['/PID',String(pid),'/T','/F'],{stdio,windowsHide:true,env:{SystemRoot:root,WINDIR:root}});
}
module.exports={trustedWindowsRoot,resolveTrustedTaskkill,spawnTrustedTaskkill};
