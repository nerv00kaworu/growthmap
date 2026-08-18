"""Windows owner/DACL/reparse and native file-identity helpers.

The PowerShell program is fixed production code.  Paths and operations are passed
only as structured JSON on stdin; no caller data is interpolated into commands.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess

_TRUSTED = ("S-1-5-18", "S-1-5-32-544")

_PS_POLICY = r"""
$ErrorActionPreference='Stop'
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices; using Microsoft.Win32.SafeHandles;
public static class GMIdentity {
 [StructLayout(LayoutKind.Sequential)] public struct Info { public uint attr; public System.Runtime.InteropServices.ComTypes.FILETIME c,a,w; public uint volume,sizeHigh,sizeLow,links,indexHigh,indexLow; }
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern SafeFileHandle CreateFile(string n,uint access,uint share,IntPtr sec,uint creation,uint flags,IntPtr template);
 [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandle(SafeFileHandle h,out Info i);
 public static string Get(string p) { using(var h=CreateFile(p,0,3,IntPtr.Zero,3,0x02200000,IntPtr.Zero)) { if(h.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); Info i; if(!GetFileInformationByHandle(h,out i)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); if((i.attr&0x400)!=0 || i.volume==0 || (i.indexHigh==0 && i.indexLow==0)) throw new InvalidOperationException("identity"); return i.volume.ToString("X8")+":"+i.indexHigh.ToString("X8")+i.indexLow.ToString("X8"); } }
}
'@
$q=[Console]::In.ReadToEnd()|ConvertFrom-Json
$me=[Security.Principal.WindowsIdentity]::GetCurrent().User
$trusted=@($me.Value,'S-1-5-18','S-1-5-32-544')
if($q.action -eq 'private') {
 $i=Get-Item -LiteralPath $q.path -Force
 if(($i.Attributes -band [IO.FileAttributes]::ReparsePoint)-ne 0){throw 'reparse'}
 $a=if($i.PSIsContainer){New-Object Security.AccessControl.DirectorySecurity}else{New-Object Security.AccessControl.FileSecurity}
 $inherit=if($i.PSIsContainer){[Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'}else{[Security.AccessControl.InheritanceFlags]::None}
 $a.SetAccessRuleProtection($true,$false);$a.SetOwner($me)
 foreach($sid in @($me,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'),[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))){$a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,[Security.AccessControl.FileSystemRights]::FullControl,$inherit,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow))}
 Set-Acl -LiteralPath $q.path -AclObject $a
 @{ok=$true}|ConvertTo-Json -Compress;exit
}
if($q.action -ne 'verify'){throw 'action'}
$danger=[Int64]([Security.AccessControl.FileSystemRights]::WriteData -bor [Security.AccessControl.FileSystemRights]::CreateFiles -bor [Security.AccessControl.FileSystemRights]::CreateDirectories -bor [Security.AccessControl.FileSystemRights]::AppendData -bor [Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Modify -bor [Security.AccessControl.FileSystemRights]::FullControl -bor [Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership)
$genericWrite=[Int64]0x40000000;$genericAll=[Int64]0x10000000;$out=@()
foreach($e in $q.entries){
 $p=[string]$e.path;$i=Get-Item -LiteralPath $p -Force
 if(($i.Attributes -band [IO.FileAttributes]::ReparsePoint)-ne 0){throw 'reparse'}
 if(($e.kind -eq 'dir' -and !$i.PSIsContainer) -or ($e.kind -eq 'file' -and $i.PSIsContainer)){throw 'kind'}
 $a=Get-Acl -LiteralPath $p
 try{$ownerSid=([Security.Principal.NTAccount]$a.Owner).Translate([Security.Principal.SecurityIdentifier]).Value}catch{try{$ownerSid=([Security.Principal.SecurityIdentifier]$a.Owner).Value}catch{throw 'owner-translation'}}
 if(($e.container -and $ownerSid -notin $trusted) -or (!$e.container -and $ownerSid -ne $me.Value)){throw 'owner'}
 foreach($r in $a.Access){
  try{$sid=$r.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value}catch{throw 'ace-translation'}
  $rights=[Int64]$r.FileSystemRights;$bad=(($rights-band $danger)-ne 0)-or(($rights-band $genericWrite)-ne 0)-or(($rights-band $genericAll)-ne 0)
  if($sid -notin $trusted -and $r.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and $bad){throw 'dacl'}
 }
 $out+=@{path=$p;identity=[GMIdentity]::Get($p)}
}
@{entries=$out}|ConvertTo-Json -Compress -Depth 4
"""
_ENCODED = __import__("base64").b64encode(_PS_POLICY.encode("utf-16le")).decode("ascii")


def _run(payload: dict) -> dict:
    if os.name != "nt":
        raise RuntimeError("Windows native file policy called off Windows")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-EncodedCommand", _ENCODED],
            input=json.dumps(payload), text=True, capture_output=True,
            timeout=20, check=False, creationflags=0x08000000,
        )
        if result.returncode:
            raise RuntimeError("unsafe Windows provider-lock path")
        value = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RuntimeError("Windows provider-lock policy unavailable") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Windows provider-lock policy unavailable")
    return value


def apply_private(path: Path) -> None:
    if _run({"action": "private", "path": str(path)}).get("ok") is not True:
        raise RuntimeError("Windows private ACL initialization failed")


def verify(path: Path, *, kind: str, container: bool = False) -> tuple[int, int]:
    value = _run({"action": "verify", "entries": [{"path": str(path), "kind": kind, "container": container}]})
    rows = value.get("entries")
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("path") != str(path):
        raise RuntimeError("Windows provider-lock identity unavailable")
    text = rows[0].get("identity")
    if not isinstance(text, str) or len(text) != 25 or text[8] != ":":
        raise RuntimeError("Windows provider-lock identity unavailable")
    try:
        return int(text[:8], 16), int(text[9:], 16)
    except ValueError as exc:
        raise RuntimeError("Windows provider-lock identity unavailable") from exc


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("creation_low", wintypes.DWORD),
                ("creation_high", wintypes.DWORD), ("access_low", wintypes.DWORD),
                ("access_high", wintypes.DWORD), ("write_low", wintypes.DWORD),
                ("write_high", wintypes.DWORD), ("volume", wintypes.DWORD),
                ("size_high", wintypes.DWORD), ("size_low", wintypes.DWORD),
                ("links", wintypes.DWORD), ("index_high", wintypes.DWORD),
                ("index_low", wintypes.DWORD)]


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


_kernel = None


def _kernel32():
    """Return kernel32 with every ABI used by this module declared exactly once."""
    global _kernel
    if _kernel is None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE,
                                                       ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION)]
        kernel.GetFileInformationByHandle.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.DWORD, wintypes.DWORD,
                                      ctypes.POINTER(_OVERLAPPED)]
        kernel.LockFileEx.restype = wintypes.BOOL
        kernel.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                        wintypes.DWORD, ctypes.POINTER(_OVERLAPPED)]
        kernel.UnlockFileEx.restype = wintypes.BOOL
        _kernel = kernel
    return _kernel


def _fd_handle(fd: int) -> wintypes.HANDLE:
    import msvcrt
    value = msvcrt.get_osfhandle(fd)
    if value == -1:
        raise OSError("invalid Windows file descriptor")
    return wintypes.HANDLE(value)


def handle_identity(fd: int) -> tuple[int, int, int]:
    info = _BY_HANDLE_FILE_INFORMATION()
    if not _kernel32().GetFileInformationByHandle(_fd_handle(fd), ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    identity = (int(info.volume), (int(info.index_high) << 32) | int(info.index_low))
    if not identity[0] or not identity[1] or info.attributes & 0x400:
        raise RuntimeError("unsafe Windows provider-lock handle")
    return identity[0], identity[1], int(info.links)


_last_lock_error = 0  # native diagnostic evidence; never used for classification


def lock_byte_zero(fd: int) -> bool:
    """Exclusively lock exactly byte 0; False means only ERROR_LOCK_VIOLATION."""
    global _last_lock_error
    overlap = _OVERLAPPED()  # explicit offset 0
    if _kernel32().LockFileEx(_fd_handle(fd), 0x00000003, 0, 1, 0, ctypes.byref(overlap)):
        _last_lock_error = 0
        return True
    error = ctypes.get_last_error()
    _last_lock_error = error
    if error == 33:  # ERROR_LOCK_VIOLATION
        return False
    raise ctypes.WinError(error)


def unlock_byte_zero(fd: int) -> None:
    overlap = _OVERLAPPED()  # explicit offset 0, exactly one byte
    if not _kernel32().UnlockFileEx(_fd_handle(fd), 0, 1, 0, ctypes.byref(overlap)):
        raise ctypes.WinError(ctypes.get_last_error())


def open_leaf(path: Path) -> tuple[int, bool]:
    """Open without following reparses and deny delete-sharing while fd is alive."""
    import msvcrt
    kernel = _kernel32()
    args = (str(path), 0xC0000000, 0x00000003, None, 1, 0x00200000, None)  # CREATE_NEW
    handle = kernel.CreateFileW(*args)
    invalid = wintypes.HANDLE(-1).value
    created = handle != invalid
    if not created:
        error = ctypes.get_last_error()
        if error not in (80, 183):
            raise ctypes.WinError(error)
        args = (str(path), 0xC0000000, 0x00000003, None, 3, 0x00200000, None)  # OPEN_EXISTING
        handle = kernel.CreateFileW(*args)
        if handle == invalid:
            raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDWR | getattr(os, "O_BINARY", 0))
    except BaseException:
        if not kernel.CloseHandle(wintypes.HANDLE(handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        raise
    return fd, created
