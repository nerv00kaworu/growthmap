'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {trustedWindowsRoot,resolveTrustedTaskkill,spawnTrustedTaskkill}=require('../trusted-taskkill');

test('accepts canonical DOS drive-absolute roots and normalizes drive-letter case',()=>{
 assert.equal(trustedWindowsRoot({SystemRoot:'C:\\Windows'}),'C:\\Windows');
 assert.equal(trustedWindowsRoot({SystemRoot:'d:\\Windows'}),'D:\\Windows');
 assert.equal(resolveTrustedTaskkill({SystemRoot:'D:\\Windows'}),'D:\\Windows\\System32\\taskkill.exe');
});

test('spawns the absolute executable with the restricted trusted environment',()=>{
 let call;const child={};
 const result=spawnTrustedTaskkill(42,{env:{SystemRoot:'d:\\Windows',PATH:'hostile',WINDIR:'C:\\evil'},stdio:'pipe',spawn:(...args)=>(call=args,child)});
 assert.equal(result,child);
 assert.deepEqual(call,['D:\\Windows\\System32\\taskkill.exe',['/PID','42','/T','/F'],{stdio:'pipe',windowsHide:true,env:{SystemRoot:'D:\\Windows',WINDIR:'D:\\Windows'}}]);
});

test('fails closed for hostile or non-canonical SystemRoot values',()=>{
 const hostile=[
  undefined,'','Windows',                         // missing / relative
  '\\Windows','C:Windows','C:\\',              // root-relative / drive-relative / root-only
  '\\\\server\\share\\Windows',              // UNC
  '\\\\?\\C:\\Windows','\\\\.\\C:\\Windows', // device namespaces
  'C:/Windows','C:\\Windows/Temp',              // forward or mixed separators
  'C:\\\\Windows','C:\\Windows\\',          // repeated / trailing separator
  'C:\\foo\\.\\Windows','C:\\foo\\..\\Windows',
  'C:\\Bad.\\Windows','C:\\Bad \\Windows', // trailing dot / space segment
  'C:\\Bad:ads\\Windows','C:\\Bad\0Root','C:\\Bad"Root',
  'C:\\Bad\x01Root','C:\\Bad\x7fRoot',
 ];
 for(const SystemRoot of hostile)assert.throws(()=>resolveTrustedTaskkill({SystemRoot}),/SystemRoot/,String(SystemRoot));
});

test('rejects DOS reserved device names case-insensitively in every path segment',()=>{
 const devices=['CON','PRN','AUX','NUL','CLOCK$'];
 for(const prefix of ['COM','LPT'])for(const suffix of ['1','2','3','4','5','6','7','8','9','¹','²','³'])devices.push(prefix+suffix);
 const hostile=[];
 for(const device of devices){
  hostile.push(`C:\\${device}\\Windows`);
  hostile.push(`C:\\Parent\\${device.toLowerCase()}`);
  hostile.push(`C:\\Parent\\${device}.txt\\Windows`);
  hostile.push(`C:\\Parent\\${device.toLowerCase()}.multiple.extensions`);
  hostile.push(`C:\\Parent\\${device} .txt\\Windows`);
  hostile.push(`C:\\Parent\\${device.toLowerCase()}  .multiple.extensions`);
 }
 for(const SystemRoot of hostile)assert.throws(()=>trustedWindowsRoot({SystemRoot}),/SystemRoot/,SystemRoot);
});

test('accepts names that only resemble DOS reserved device names',()=>{
 const ordinary=['console','com10','lpt10','auxiliary','conifer','prnter','nulled','clock','clock$$','xCOM1','LPT1x','COM⁴','LPT⁹','console .txt','com10 .txt','auxiliary .txt'];
 for(const segment of ordinary){
  const SystemRoot=`c:\\Parent\\${segment}`;
  assert.equal(trustedWindowsRoot({SystemRoot}),`C:\\Parent\\${segment}`);
 }
});
