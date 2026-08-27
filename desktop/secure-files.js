'use strict';
const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const fsIdentity=Symbol('windowsFileIdentity');
const WINDOWS_DIR_FSYNC_UNSUPPORTED=new Set(['EPERM','EINVAL','ENOTSUP','EOPNOTSUPP']);
const WINDOWS_NATIVE_POLICY_TIMEOUT_MS=30000;
function trustedPowerShell(env=process.env){const root=env.SystemRoot||env.WINDIR;if(typeof root!=='string'||!path.win32.isAbsolute(root))throw Error('Windows PowerShell path unavailable');return path.win32.join(root,'System32','WindowsPowerShell','v1.0','powershell.exe')}
const WINDOWS_POLICY=String.raw`
$ErrorActionPreference='Stop'
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices; using Microsoft.Win32.SafeHandles;
public static class GMFileIdentity {
 [StructLayout(LayoutKind.Sequential)] public struct Info { public uint attr; public System.Runtime.InteropServices.ComTypes.FILETIME c,a,w; public uint volume,sizeHigh,sizeLow,links,indexHigh,indexLow; }
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern SafeFileHandle CreateFile(string n, uint access, uint share, IntPtr sec, uint creation, uint flags, IntPtr template);
 [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandle(SafeFileHandle h, out Info i);
 [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetFileSecurity(string p,uint info,byte[] descriptor);
 public static void SetDacl(string p,byte[] descriptor) { const uint DACL=0x4,PROTECTED_DACL=0x80000000; if(!SetFileSecurity(p,DACL|PROTECTED_DACL,descriptor)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); }
 public static string Get(string p) { using(var h=CreateFile(p,0,7,IntPtr.Zero,3,0x02000000,IntPtr.Zero)){ if(h.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); Info i; if(!GetFileInformationByHandle(h,out i)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); if(i.volume==0 || (i.indexHigh==0 && i.indexLow==0)) throw new InvalidOperationException("identity"); return i.volume.ToString("X8")+":"+i.indexHigh.ToString("X8")+i.indexLow.ToString("X8"); } }
}
'@
$q=[Console]::In.ReadToEnd()|ConvertFrom-Json
$me=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$trusted=@($me,'S-1-5-18','S-1-5-32-544') # current user, LOCAL SYSTEM, BUILTIN Administrators
$danger=[Int64]([Security.AccessControl.FileSystemRights]::WriteData -bor [Security.AccessControl.FileSystemRights]::CreateFiles -bor [Security.AccessControl.FileSystemRights]::CreateDirectories -bor [Security.AccessControl.FileSystemRights]::AppendData -bor [Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Modify -bor [Security.AccessControl.FileSystemRights]::FullControl -bor [Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership)
$genericWrite=[Int64]0x40000000;$genericAll=[Int64]0x10000000
$out=@()
foreach($p in $q.paths){
 $i=Get-Item -LiteralPath $p -Force
 if(($i.Attributes -band [IO.FileAttributes]::ReparsePoint)-ne 0){throw 'reparse'}
 $a=$i.GetAccessControl([Security.AccessControl.AccessControlSections]::Access -bor [Security.AccessControl.AccessControlSections]::Owner)
 $owner=$a.Owner
 try{$ownerSid=([Security.Principal.NTAccount]$owner).Translate([Security.Principal.SecurityIdentifier]).Value}catch{try{$ownerSid=([Security.Principal.SecurityIdentifier]$owner).Value}catch{throw 'owner-translation'}}
 if($ownerSid -notin $trusted){throw 'owner'}
 foreach($r in $a.Access){
  try{$sid=$r.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value}catch{throw 'ace-translation'}
  $rights=[Int64]$r.FileSystemRights
  $dangerous=(($rights -band $danger)-ne 0) -or (($rights -band $genericWrite)-ne 0) -or (($rights -band $genericAll)-ne 0)
  if(($sid -notin $trusted) -and $r.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and $dangerous){throw 'dacl'}
 }
 $out+=@{path=$p;identity=[GMFileIdentity]::Get($p)}
}
@{identities=$out}|ConvertTo-Json -Compress -Depth 4
`;
function nativeWindowsPolicy(paths,runner=spawnSync,containerOnly=false,env=process.env){
 const encoded=Buffer.from(WINDOWS_POLICY,'utf16le').toString('base64');
 const r=runner(trustedPowerShell(env),['-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-EncodedCommand',encoded],{input:JSON.stringify({paths,...(containerOnly?{containerOnly:true}:{})}),encoding:'utf8',windowsHide:true,maxBuffer:1024*1024,timeout:WINDOWS_NATIVE_POLICY_TIMEOUT_MS});
 if(r.error){const code=/^[A-Z0-9_]{1,32}$/.test(String(r.error.code||''))?r.error.code:'unknown';throw Error(`Windows native secret-path policy unavailable or unsafe stage=spawn-${code}`)}
 if(r.status!==0){const status=Number.isInteger(r.status)&&r.status>=0&&r.status<=255?r.status:'unknown',signal=/^[A-Z0-9_]{1,32}$/.test(String(r.signal||''))?r.signal:'none';throw Error(`Windows native secret-path policy unavailable or unsafe stage=exit-${status}-${signal}`)}
 let value;try{value=JSON.parse(r.stdout)}catch{throw Error('Windows native secret-path policy unavailable or unsafe stage=json')}
 if(!value||!Array.isArray(value.identities)||value.identities.length!==paths.length)throw Error('Windows native secret-path policy unavailable or unsafe stage=schema');
 return value.identities.map((entry,index)=>{if(!entry||entry.path!==paths[index]||typeof entry.identity!=='string'||!/^[0-9A-F]{8}:[0-9A-F]{16}$/.test(entry.identity))throw Error('Windows native secret-path identity unavailable');return entry.identity});
}
function applyWindowsPrivateAcl(target,options={}){
 const script=String.raw`$ErrorActionPreference='Stop';Add-Type -TypeDefinition @'
using System;using System.Runtime.InteropServices;public static class GMPrivateDacl{[DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)]static extern bool SetFileSecurity(string p,uint i,byte[] d);public static void Set(string p,byte[] d){if(!SetFileSecurity(p,0x80000004,d))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());}}
'@;$q=[Console]::In.ReadToEnd()|ConvertFrom-Json;$me=[Security.Principal.WindowsIdentity]::GetCurrent().User;$trusted=@($me.Value,'S-1-5-18','S-1-5-32-544');$i=Get-Item -LiteralPath $q.path -Force;if(($i.Attributes -band [IO.FileAttributes]::ReparsePoint)-ne 0){throw 'reparse'};$a=$i.GetAccessControl([Security.AccessControl.AccessControlSections]::Access -bor [Security.AccessControl.AccessControlSections]::Owner);try{$ownerSid=([Security.Principal.NTAccount]$a.Owner).Translate([Security.Principal.SecurityIdentifier]).Value}catch{$ownerSid=([Security.Principal.SecurityIdentifier]$a.Owner).Value};if($ownerSid -notin $trusted){throw 'owner'};$inherit=if($i.PSIsContainer){[Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'}else{[Security.AccessControl.InheritanceFlags]::None};$a.SetAccessRuleProtection($true,$false);$seen=@{};foreach($r in @($a.Access)){$sid=$r.IdentityReference.Translate([Security.Principal.SecurityIdentifier]);if(!$seen.ContainsKey($sid.Value)){$a.PurgeAccessRules($sid);$seen[$sid.Value]=$true}};foreach($sid in @($me,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'),[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))){$a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,[Security.AccessControl.FileSystemRights]::FullControl,$inherit,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow))};[GMPrivateDacl]::Set([string]$q.path,$a.GetSecurityDescriptorBinaryForm())`;
 const encoded=Buffer.from(script,'utf16le').toString('base64'),r=(options.windowsRunner||spawnSync)(trustedPowerShell(options.env||process.env),['-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-EncodedCommand',encoded],{input:JSON.stringify({path:target}),encoding:'utf8',windowsHide:true,maxBuffer:1024*1024,timeout:WINDOWS_NATIVE_POLICY_TIMEOUT_MS});
 if(r.error||r.status!==0)throw Error('Windows private secret path initialization failed');
}
function bootstrapWindowsPrivateRoot(parent,directory,io=fs,options={}){
 const policy=options.windowsPolicy||nativeWindowsPolicy,runner=options.windowsRunner;
 const parentBefore=io.lstatSync(parent);if(parentBefore.isSymbolicLink()||!parentBefore.isDirectory())throw Error('Unsafe secret container');
 const before=policy([parent],runner,true);if(!Array.isArray(before)||before.length!==1)throw Error('Windows native secret-path identity unavailable');
 try{io.mkdirSync(directory,{mode:0o700})}catch(e){if(e.code==='EEXIST')throw Error('Windows private secret root initialization raced');throw e}
 applyWindowsPrivateAcl(directory,options);
 const after=policy([parent],runner,true);if(!Array.isArray(after)||after.length!==1||before[0]!==after[0])throw Error('Secret container replaced during initialization');
 policy([directory],runner);
}
function identity(s,platform){if(platform==='win32'){if(typeof s[fsIdentity]!=='string')throw Error('Windows native secret-path identity unavailable');return s[fsIdentity]}return `${s.dev}:${s.ino}`}
function secureFiles(trustedRoot,directory,io=fs,options={}){
 if(typeof directory!=='string'){options=io||{};io=directory||fs;directory=trustedRoot;}
 trustedRoot=path.resolve(trustedRoot);directory=path.resolve(directory);
 const relative=path.relative(trustedRoot,directory);
 if(relative==='..'||relative.startsWith(`..${path.sep}`)||path.isAbsolute(relative))throw Error('Secret directory escapes trusted root');
 const platform=options.platform||process.platform,hooks=options.hooks||{},windowsPolicy=options.windowsPolicy||nativeWindowsPolicy,maxReadBytes=options.maxReadBytes||1024*1024;
 const checkPosix=(s,kind)=>{if(s.isSymbolicLink()||(kind==='dir'?!s.isDirectory():!s.isFile())||s.uid!==process.geteuid()||(s.mode&0o077)!==0)throw Error(`Unsafe secret ${kind}`)};
 const verifyComponent=(p,kind='dir')=>{const s=io.lstatSync(p);if(platform==='win32'){if(s.isSymbolicLink()||(kind==='dir'?!s.isDirectory():!s.isFile()))throw Error(`Unsafe secret ${kind}`);const ids=windowsPolicy([p],options.windowsRunner);if(!Array.isArray(ids)||ids.length!==1||typeof ids[0]!=='string')throw Error('Windows native secret-path identity unavailable');s[fsIdentity]=ids[0]}else checkPosix(s,kind);return s};
 const components=()=>relative?relative.split(path.sep).filter(Boolean):[];
 const verifyDir=()=>{
  if(trustedRoot===directory&&!io.existsSync(trustedRoot)){
   if(platform==='win32')bootstrapWindowsPrivateRoot(path.dirname(trustedRoot),trustedRoot,io,{windowsPolicy,windowsRunner:options.windowsRunner});
   else{const parent=path.dirname(trustedRoot),before=io.lstatSync(parent);if(before.isSymbolicLink()||!before.isDirectory()||before.uid!==process.geteuid()||(before.mode&0o022)!==0)throw Error('Unsafe secret container');try{io.mkdirSync(trustedRoot,{mode:0o700})}catch(e){if(e.code!=='EEXIST')throw e;}const after=io.lstatSync(parent);if(before.dev!==after.dev||before.ino!==after.ino)throw Error('Secret container replaced during initialization');verifyComponent(trustedRoot);}
  }
  let current=trustedRoot;verifyComponent(current);
  for(const component of components()){
   const parentBefore=verifyComponent(current);current=path.join(current,component);
   try{verifyComponent(current)}catch(e){if(e.code!=='ENOENT')throw e;hooks.beforeMkdir?.(current);io.mkdirSync(current,{mode:0o700});const created=verifyComponent(current);hooks.afterMkdir?.(current);const createdAfter=verifyComponent(current);if(identity(created,platform)!==identity(createdAfter,platform))throw Error('Secret parent replaced during mkdir')}
   const parentAfter=verifyComponent(path.dirname(current));if(identity(parentBefore,platform)!==identity(parentAfter,platform))throw Error('Secret parent replaced during mkdir');
  }
  const realRoot=io.realpathSync(trustedRoot),realDir=io.realpathSync(directory),realRelative=path.relative(realRoot,realDir);
  if(realRelative==='..'||realRelative.startsWith(`..${path.sep}`)||path.isAbsolute(realRelative))throw Error('Secret directory escapes trusted root');
  return verifyComponent(directory);
 };
 const safe=name=>{if(!/^[A-Za-z0-9-]{1,80}\.(?:bin|recover)$/.test(name))throw Error('Unsafe secret filename');return path.join(directory,name)};
 const stableParent=(before,stage)=>{hooks[stage]?.(directory);const after=verifyDir();if(identity(before,platform)!==identity(after,platform))throw Error('Secret parent replaced')};
 const read=name=>{const parent=verifyDir(),flags=io.constants.O_RDONLY|(io.constants.O_NOFOLLOW||0),fd=io.openSync(safe(name),flags);try{const before=io.fstatSync(fd);if(platform==='win32'){if(!before.isFile())throw Error('Unsafe secret file');const ids=windowsPolicy([safe(name)],options.windowsRunner);if(!Array.isArray(ids)||ids.length!==1||typeof ids[0]!=='string')throw Error('Windows native secret-path identity unavailable');before[fsIdentity]=ids[0]}else checkPosix(before,'file');if(before.nlink!==1)throw Error('Unsafe secret file');if(before.size<0||before.size>maxReadBytes)throw Error('Secret file is too large');const data=io.readFileSync(fd);if(data.length>maxReadBytes)throw Error('Secret file is too large');const after=io.fstatSync(fd);if(platform==='win32'){const ids=windowsPolicy([safe(name)],options.windowsRunner);if(!Array.isArray(ids)||ids.length!==1||typeof ids[0]!=='string')throw Error('Windows native secret-path identity unavailable');after[fsIdentity]=ids[0]}if(identity(before,platform)!==identity(after,platform)||before.size!==after.size||before.mtimeMs!==after.mtimeMs)throw Error('Unstable secret file');stableParent(parent,'beforeReadReturn');return data}finally{io.closeSync(fd)}};
 const syncDir=()=>{const parent=verifyDir(),fd=io.openSync(directory,'r');try{try{io.fsyncSync(fd)}catch(e){if(platform!=='win32'||!WINDOWS_DIR_FSYNC_UNSUPPORTED.has(e.code))throw e}}finally{io.closeSync(fd)}stableParent(parent,'afterDirSync')};
 const write=(name,data)=>{const parent=verifyDir(),target=safe(name),tmp=`${target}.tmp-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`,fd=io.openSync(tmp,io.constants.O_CREAT|io.constants.O_EXCL|io.constants.O_WRONLY,0o600);try{if(platform==='win32'&&process.platform==='win32')applyWindowsPrivateAcl(tmp,{windowsRunner:options.windowsRunner});io.writeFileSync(fd,data);io.fsyncSync(fd)}finally{io.closeSync(fd)}try{stableParent(parent,'beforeRename');verifyComponent(tmp,'file');io.renameSync(tmp,target);stableParent(parent,'afterRename');verifyComponent(target,'file');syncDir()}catch(e){try{io.unlinkSync(tmp)}catch{}throw e}};
 const remove=name=>{const parent=verifyDir(),target=safe(name);try{read(name)}catch(e){if(e.code==='ENOENT')return;throw e}stableParent(parent,'beforeUnlink');io.unlinkSync(target);stableParent(parent,'afterUnlink');syncDir()};
 const exists=name=>{verifyDir();try{read(name);return true}catch(e){if(e.code==='ENOENT')return false;throw e}};
 const quarantine=name=>{const parent=verifyDir();read(name);stableParent(parent,'beforeUnlink');io.unlinkSync(safe(name));stableParent(parent,'afterUnlink');syncDir()};
 return{verifyDir,read,write,remove,exists,quarantine,list:()=>{verifyDir();return io.readdirSync(directory)}};
}
module.exports={secureFiles,nativeWindowsPolicy,bootstrapWindowsPrivateRoot,WINDOWS_POLICY,WINDOWS_NATIVE_POLICY_TIMEOUT_MS};
