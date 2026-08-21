$ErrorActionPreference='Stop';Set-StrictMode -Version 3;[Console]::InputEncoding=[Text.UTF8Encoding]::new($false);[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -TypeDefinition @'
using System;using System.IO;using System.Text;using System.Runtime.InteropServices;using Microsoft.Win32.SafeHandles;
public static class GMRenamePoc {
 [StructLayout(LayoutKind.Sequential)] public struct FT {public uint lo,hi;}
 [StructLayout(LayoutKind.Sequential)] public struct Info {public uint attr;public FT c,a,w;public uint volume,sizeHi,sizeLo,links,indexHi,indexLo;}
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] public static extern SafeFileHandle CreateFileW(string p,uint access,uint share,IntPtr sa,uint disposition,uint flags,IntPtr template);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetFileInformationByHandle(SafeFileHandle h,int cls,IntPtr info,uint size);
 [DllImport("kernel32.dll",SetLastError=true)] public static extern bool GetFileInformationByHandle(SafeFileHandle h,out Info info);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern uint GetFinalPathNameByHandleW(SafeFileHandle h,StringBuilder b,uint n,uint flags);
 public static SafeFileHandle Open(string p){var h=CreateFileW(p,0x80010000,1,IntPtr.Zero,3,0x00200000,IntPtr.Zero);if(h.IsInvalid)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());return h;}
 public static void Rename(SafeFileHandle h,string target){byte[] n=Encoding.Unicode.GetBytes(target);int head=20;IntPtr p=Marshal.AllocHGlobal(head+n.Length+2);try{for(int i=0;i<head+n.Length+2;i++)Marshal.WriteByte(p,i,0);Marshal.WriteByte(p,0,0);Marshal.WriteIntPtr(p,8,IntPtr.Zero);Marshal.WriteInt32(p,16,n.Length);Marshal.Copy(n,0,IntPtr.Add(p,head),n.Length);if(!SetFileInformationByHandle(h,3,p,(uint)(head+n.Length+2)))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());}finally{Marshal.FreeHGlobal(p);}}
 public static string Final(SafeFileHandle h){var b=new StringBuilder(32768);uint n=GetFinalPathNameByHandleW(h,b,(uint)b.Capacity,0);if(n==0||n>=b.Capacity)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());return b.ToString();}
 public static string Id(SafeFileHandle h){Info i;if(!GetFileInformationByHandle(h,out i))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());return i.volume.ToString("X8")+":"+i.indexHi.ToString("X8")+i.indexLo.ToString("X8")+":"+i.links;}
}
'@
$script:streams=@()
function Ev($h){$s=[IO.FileStream]::new($h,[IO.FileAccess]::Read,4096,$false);$script:streams+=,$s;$sha=[Security.Cryptography.SHA256]::Create();try{$s.Position=0;$x=$sha.ComputeHash($s);$s.Position=0;@{sha=([BitConverter]::ToString($x).Replace('-','').ToLower());size=$s.Length}}finally{$sha.Dispose()}}
$q=[Console]::In.ReadLine()|ConvertFrom-Json
$live=[GMRenamePoc]::Open([string]$q.live);$staging=if($q.staging){[GMRenamePoc]::Open([string]$q.staging)}else{$null}
try{$before=@{id=[GMRenamePoc]::Id($live);final=[GMRenamePoc]::Final($live);evidence=(Ev $live)};$stagingBefore=if($staging){@{id=[GMRenamePoc]::Id($staging);final=[GMRenamePoc]::Final($staging);evidence=(Ev $staging)}}else{$null};@{ready=$true;before=$before;staging=$stagingBefore}|ConvertTo-Json -Compress -Depth 5;[Console]::Out.Flush();if([Console]::In.ReadLine()-ne 'go'){throw 'command'};[GMRenamePoc]::Rename($live,[string]$q.old);$after=@{id=[GMRenamePoc]::Id($live);final=[GMRenamePoc]::Final($live);evidence=(Ev $live)};if($staging){[GMRenamePoc]::Rename($staging,[string]$q.live);$installed=@{id=[GMRenamePoc]::Id($staging);final=[GMRenamePoc]::Final($staging);evidence=(Ev $staging)}}else{$installed=$null};@{renamed=$true;after=$after;installed=$installed}|ConvertTo-Json -Compress -Depth 5;[Console]::Out.Flush()}finally{if($staging){$staging.Dispose()};$live.Dispose()}
