$ErrorActionPreference='Stop';Add-Type -TypeDefinition @'
using System;using System.Runtime.InteropServices;using Microsoft.Win32.SafeHandles;
public static class GMDirFlush {
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern SafeFileHandle CreateFileW(string p,uint a,uint s,IntPtr x,uint d,uint f,IntPtr t);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool FlushFileBuffers(SafeFileHandle h);
 public static void Run(string p){using(var h=CreateFileW(p,0x80000000,7,IntPtr.Zero,3,0x02000000|0x20000000,IntPtr.Zero)){if(h.IsInvalid)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());if(!FlushFileBuffers(h))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());}}
}
'@;try{[GMDirFlush]::Run($args[0]);'{"ok":true}'}catch{'{"ok":false,"hresult":'+$_.Exception.InnerException.NativeErrorCode+'}';exit 1}
