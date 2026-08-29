$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Text;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class GrowthMapNativeEvidence {
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern SafeFileHandle CreateFileW(string p,uint access,uint share,IntPtr sa,uint disposition,uint flags,IntPtr template);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetFileInformationByHandle(SafeFileHandle h,int cls,IntPtr info,uint size);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool FlushFileBuffers(SafeFileHandle h);
  [StructLayout(LayoutKind.Sequential)] public struct FILETIME { public uint Low; public uint High; }
  [StructLayout(LayoutKind.Sequential)] public struct Info { public uint Attributes; public FILETIME Creation, Access, Write; public uint VolumeSerial, SizeHigh, SizeLow, NumberOfLinks, FileIndexHigh, FileIndexLow; }
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool GetFileInformationByHandle(SafeFileHandle handle, out Info info);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern uint GetFinalPathNameByHandleW(SafeFileHandle handle, StringBuilder path, uint length, uint flags);
  public static SafeFileHandle OpenOwner(string p) { var h=CreateFileW(p,0x80010000,1,IntPtr.Zero,3,0x00200000,IntPtr.Zero); if(h.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); return h; }
  public static void Rename(SafeFileHandle h,string target) { byte[] n=Encoding.Unicode.GetBytes(target); int head=20; IntPtr p=Marshal.AllocHGlobal(head+n.Length+2); try { for(int x=0;x<head+n.Length+2;x++) Marshal.WriteByte(p,x,0); Marshal.WriteIntPtr(p,8,IntPtr.Zero); Marshal.WriteInt32(p,16,n.Length); Marshal.Copy(n,0,IntPtr.Add(p,head),n.Length); if(!SetFileInformationByHandle(h,3,p,(uint)(head+n.Length+2))) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); } finally { Marshal.FreeHGlobal(p); } }
  public static void FlushDirectory(string p) { using(var h=CreateFileW(p,0x40000000,7,IntPtr.Zero,3,0x02000000|0x20000000,IntPtr.Zero)) { if(h.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); if(!FlushFileBuffers(h)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); } }
  public static Info GetInfo(SafeFileHandle handle) { Info i; if (!GetFileInformationByHandle(handle, out i)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); return i; }
  public static string FinalPath(SafeFileHandle handle) { var b=new StringBuilder(32768); uint n=GetFinalPathNameByHandleW(handle,b,(uint)b.Capacity,0); if(n==0 || n>=b.Capacity) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); return b.ToString(); }
}
'@
$Protocol = 1
function Send-Value($value) { [Console]::Out.WriteLine(($value | ConvertTo-Json -Compress -Depth 6)); [Console]::Out.Flush() }
function Fail([string]$stage) { Send-Value @{protocolVersion=$Protocol;error=@{code='NATIVE_EVIDENCE_REJECTED';stage=$stage}}; exit 41 }
function Canon([string]$p) {
  if ([string]::IsNullOrWhiteSpace($p) -or $p.Length -gt 32767) { throw 'path' }
  $f=[IO.Path]::GetFullPath($p)
  if (-not [IO.Path]::IsPathRooted($f) -or $f.StartsWith('\\') -or $f.StartsWith('\\?\UNC\') -or $f.StartsWith('\\.\')) { throw 'boundary' }
  return $f.TrimEnd([IO.Path]::DirectorySeparatorChar)
}
function Final-Canon($h) { $p=[GrowthMapNativeEvidence]::FinalPath($h); if($p.StartsWith('\\?\UNC\')){throw 'network'}; if($p.StartsWith('\\?\')){$p=$p.Substring(4)}; return Canon $p }
function Identity($info,[string]$p) { @{platform='win32';volumeSerial=('{0:X8}' -f $info.VolumeSerial);fileIndex=('{0:X8}{1:X8}' -f $info.FileIndexHigh,$info.FileIndexLow)} }
function Validate-Info($info) {
  $reparse=[uint32]0x400; $directory=[uint32]0x10; $device=[uint32]0x40
  if(($info.Attributes -band ($reparse -bor $directory -bor $device)) -ne 0 -or $info.NumberOfLinks -ne 1 -or $info.VolumeSerial -eq 0 -or ($info.FileIndexHigh -eq 0 -and $info.FileIndexLow -eq 0)){throw 'unsafe'}
}
function Validate-Ancestors([string]$p) {
  $current=[IO.Path]::GetDirectoryName($p)
  while(-not [string]::IsNullOrEmpty($current)) {
    $attributes=[IO.File]::GetAttributes($current)
    if(($attributes -band [IO.FileAttributes]::ReparsePoint)-ne 0){throw 'ancestor-reparse'}
    $parent=[IO.Directory]::GetParent($current)
    if($null -eq $parent){break}
    $current=$parent.FullName
  }
}
function Validate-Acl([string]$p) {
  Validate-Ancestors $p
  $me=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $trusted=@($me,'S-1-5-18','S-1-5-32-544')
  $danger=[Int64]([Security.AccessControl.FileSystemRights]::WriteData -bor [Security.AccessControl.FileSystemRights]::CreateFiles -bor [Security.AccessControl.FileSystemRights]::CreateDirectories -bor [Security.AccessControl.FileSystemRights]::AppendData -bor [Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Modify -bor [Security.AccessControl.FileSystemRights]::FullControl -bor [Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership)
  foreach($x in @([IO.Path]::GetDirectoryName($p),$p)) {
    $item=Get-Item -LiteralPath $x -Force
    if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint)-ne 0){throw 'reparse'}
    $acl=$item.GetAccessControl([Security.AccessControl.AccessControlSections]::Access -bor [Security.AccessControl.AccessControlSections]::Owner)
    try{$owner=([Security.Principal.NTAccount]$acl.Owner).Translate([Security.Principal.SecurityIdentifier]).Value}catch{$owner=([Security.Principal.SecurityIdentifier]$acl.Owner).Value}
    if($owner -notin $trusted){throw 'owner'}
    foreach($r in $acl.Access){$sid=$r.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value;$rights=[Int64]$r.FileSystemRights;if($sid -notin $trusted -and $r.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and ((($rights -band $danger)-ne 0) -or (($rights -band [Int64]0x40000000)-ne 0) -or (($rights -band [Int64]0x10000000)-ne 0))){throw 'acl'}}
  }
}
function Evidence($stream) {
  $stream.Position=0; $sha=[Security.Cryptography.SHA256]::Create()
  try{$hash=$sha.ComputeHash($stream)}finally{$sha.Dispose()}
  $stream.Position=0
  @{sha256=([BitConverter]::ToString($hash).Replace('-','').ToLowerInvariant());size=[Int64]$stream.Length}
}
function Same-Identity($a,$b) { $a.VolumeSerial -eq $b.VolumeSerial -and $a.FileIndexHigh -eq $b.FileIndexHigh -and $a.FileIndexLow -eq $b.FileIndexLow }
$liveStream=$null;$newStream=$null;$liveHandle=$null;$newHandle=$null
try {
 $line=[Console]::In.ReadLine();if($null-eq$line-or$line.Length-gt 65536){Fail 'request'}
 try{$q=$line|ConvertFrom-Json}catch{Fail 'request'}
 $keys=@($q.PSObject.Properties.Name|Sort-Object);$installKeys=@('capture','expectedNew','expectedOld','live','mode','old','operation','protocolVersion','staging','transitionId')|Sort-Object;$renameKeys=@('action','databasePath','expected','operation','protocolVersion','transitionId')|Sort-Object
 if($q.operation-eq'rename-exact'){if(($keys-join'|')-ne($renameKeys-join'|')-or$q.transitionId-notmatch'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'){Fail 'request'};try{$db=Canon([string]$q.databasePath);$old=$db+'.gm-old-'+$q.transitionId;$failed=$db+'.gm-failed-'+$q.transitionId;$quarantine=$old+'.quarantine';if($q.action-eq'rollback-live-to-failed'){$from=$db;$to=$failed}elseif($q.action-eq'rollback-old-to-live'){$from=$old;$to=$db}elseif($q.action-eq'cleanup-old-to-quarantine'){$from=$old;$to=$quarantine}else{throw'action'};if([IO.Path]::GetDirectoryName($from)-ine[IO.Path]::GetDirectoryName($to)-or[IO.File]::Exists($to)-or[IO.Directory]::Exists($to)){throw'target'};$h=[GrowthMapNativeEvidence]::OpenOwner($from);$s=[IO.FileStream]::new($h,[IO.FileAccess]::Read,4096,$false);$i=[GrowthMapNativeEvidence]::GetInfo($h);Validate-Info $i;if((Final-Canon $h)-ine$from){throw'final'};Validate-Acl $from;$e=Evidence $s;if($e.sha256-ne$q.expected.sha256-or$e.size-ne$q.expected.size){throw'evidence'};[GrowthMapNativeEvidence]::Rename($h,$to);[GrowthMapNativeEvidence]::FlushDirectory([IO.Path]::GetDirectoryName($to));if((Final-Canon $h)-ine$to){throw'final'};Send-Value @{protocolVersion=$Protocol;ok=$true;phase='rename-durable';record=@{identity=(Identity $i $to);evidence=(Evidence $s)}};exit 0}catch{Fail 'rename'}}
 if($null-eq$q-or($keys-join'|')-ne($installKeys-join'|')-or$q.protocolVersion-ne$Protocol-or$q.operation-ne'install'-or$q.transitionId-notmatch'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'-or$q.mode-notin@('managed-restore','foreign-import')){Fail 'request'}
 try{$live=Canon([string]$q.live);$staging=Canon([string]$q.staging);$old=Canon([string]$q.old);$capture=Canon([string]$q.capture)}catch{Fail 'path'}
 if($old-ine($live+'.gm-old-'+$q.transitionId)-or$staging-ine($live+'.gm-new-'+$q.transitionId)-or$capture-ine($staging+'.capture')-or[IO.Path]::GetDirectoryName($live)-ine[IO.Path]::GetDirectoryName($old)-or[IO.File]::Exists($old)-or[IO.Directory]::Exists($old)-or[IO.File]::Exists($capture)-or[IO.Directory]::Exists($capture)){Fail 'derived'}
 try{
  $liveHandle=[GrowthMapNativeEvidence]::OpenOwner($live);$newHandle=[GrowthMapNativeEvidence]::OpenOwner($staging)
  $liveStream=[IO.FileStream]::new($liveHandle,[IO.FileAccess]::Read,4096,$false);$newStream=[IO.FileStream]::new($newHandle,[IO.FileAccess]::Read,4096,$false)
  $li=[GrowthMapNativeEvidence]::GetInfo($liveHandle);$ni=[GrowthMapNativeEvidence]::GetInfo($newHandle);Validate-Info $li;Validate-Info $ni
  if((Final-Canon $liveHandle)-ine$live-or(Final-Canon $newHandle)-ine$staging){throw'final'};Validate-Acl $live;Validate-Acl $staging
  $le=Evidence $liveStream;$ne=Evidence $newStream
  if(($null-ne$q.expectedOld-and($le.sha256-ne$q.expectedOld.sha256-or$le.size-ne$q.expectedOld.size))-or$ne.sha256-ne$q.expectedNew.sha256-or$ne.size-ne$q.expectedNew.size){throw'evidence'}
 }catch{Fail 'validate'}
 Send-Value @{protocolVersion=$Protocol;ready=$true;phase='prepared';old=@{identity=(Identity $li $live);evidence=$le};new=@{identity=(Identity $ni $staging);evidence=$ne}}
 $commit=[Console]::In.ReadLine();if($commit-ne('{"protocolVersion":1,"command":"commit-install"}')){Fail 'commit'}
 try{
  [GrowthMapNativeEvidence]::Rename($liveHandle,$old);if((Final-Canon $liveHandle)-ine$old){throw'old-final'}
  [GrowthMapNativeEvidence]::FlushDirectory([IO.Path]::GetDirectoryName($live));Send-Value @{protocolVersion=$Protocol;ok=$true;phase='old-durable'}
  [GrowthMapNativeEvidence]::Rename($newHandle,$live);if((Final-Canon $newHandle)-ine$live){throw'live-final'}
  [GrowthMapNativeEvidence]::FlushDirectory([IO.Path]::GetDirectoryName($live))
  $le=Evidence $liveStream;$ne=Evidence $newStream
  Send-Value @{protocolVersion=$Protocol;ok=$true;phase='installed-durable';old=@{identity=(Identity $li $old);evidence=$le};live=@{identity=(Identity $ni $live);evidence=$ne}}
 }catch{Fail 'mutation'}
}catch{Fail 'internal'}finally{if($liveStream){$liveStream.Dispose()};if($newStream){$newStream.Dispose()};if($liveHandle){$liveHandle.Dispose()};if($newHandle){$newHandle.Dispose()}}
