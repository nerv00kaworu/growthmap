$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Text;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class GrowthMapNativeEvidence {
  [StructLayout(LayoutKind.Sequential)] public struct FILETIME { public uint Low; public uint High; }
  [StructLayout(LayoutKind.Sequential)] public struct Info { public uint Attributes; public FILETIME Creation, Access, Write; public uint VolumeSerial, SizeHigh, SizeLow, NumberOfLinks, FileIndexHigh, FileIndexLow; }
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool GetFileInformationByHandle(SafeFileHandle handle, out Info info);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern uint GetFinalPathNameByHandleW(SafeFileHandle handle, StringBuilder path, uint length, uint flags);
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
function Identity($info,[string]$p) { @{platform='win32';path=$p;volumeSerial=('{0:X8}' -f $info.VolumeSerial);fileIndex=('{0:X8}{1:X8}' -f $info.FileIndexHigh,$info.FileIndexLow)} }
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
$stream=$null
try {
  $line=[Console]::In.ReadLine(); if($null -eq $line -or $line.Length -gt 65536){Fail 'request'}
  try{$q=$line|ConvertFrom-Json}catch{Fail 'request'}
  if($null -eq $q -or $q.protocolVersion -ne $Protocol -or @($q.PSObject.Properties.Name).Count -ne 2 -or -not ($q.PSObject.Properties.Name -contains 'path')){Fail 'request'}
  try{$path=Canon ([string]$q.path)}catch{Fail 'path'}
  try{$stream=[IO.FileStream]::new($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)}catch{Fail 'open'}
  try{$held=[GrowthMapNativeEvidence]::GetInfo($stream.SafeFileHandle);Validate-Info $held;if((Final-Canon $stream.SafeFileHandle) -ine $path){throw 'final'};Validate-Acl $path;$ev=Evidence $stream}catch{Fail 'validate'}
  Send-Value @{protocolVersion=$Protocol;identity=(Identity $held $path);evidence=$ev;ready=$true}
  while($true){
    $line=[Console]::In.ReadLine();if($null -eq $line){break};if($line.Length -gt 4096){Fail 'command'}
    try{$cmd=$line|ConvertFrom-Json}catch{Fail 'command'}
    if($null -eq $cmd -or $cmd.protocolVersion -ne $Protocol -or @($cmd.PSObject.Properties.Name).Count -ne 2){Fail 'command'}
    if($cmd.command -eq 'close'){$stream.Dispose();$stream=$null;Send-Value @{protocolVersion=$Protocol;closed=$true};exit 0}
    if($cmd.command -ne 'assert'){Fail 'command'}
    try{
      $now=[GrowthMapNativeEvidence]::GetInfo($stream.SafeFileHandle);Validate-Info $now;if(-not (Same-Identity $held $now)){throw 'held'};if((Final-Canon $stream.SafeFileHandle) -ine $path){throw 'final'}
      $fresh=[IO.FileStream]::new($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
      try{$named=[GrowthMapNativeEvidence]::GetInfo($fresh.SafeFileHandle);Validate-Info $named;if(-not (Same-Identity $held $named)){throw 'named'};if((Final-Canon $fresh.SafeFileHandle) -ine $path){throw 'named-final'}}finally{$fresh.Dispose()}
      Validate-Acl $path;$ev=Evidence $stream
    }catch{Fail 'assert'}
    Send-Value @{protocolVersion=$Protocol;ok=$true;identity=(Identity $now $path);evidence=$ev}
  }
} catch { Fail 'internal' } finally { if($null -ne $stream){$stream.Dispose()} }
exit 0
