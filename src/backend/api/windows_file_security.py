"""Windows owner/DACL/reparse and native file-identity helpers.

The PowerShell program is fixed production code.  Paths and operations are passed
only as structured JSON on stdin; no caller data is interpolated into commands.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import ntpath
import os
from pathlib import Path, PureWindowsPath
import re
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
 $stage='item'
 try{
  $i=Get-Item -LiteralPath $q.path -Force
  if(($i.Attributes -band [IO.FileAttributes]::ReparsePoint)-ne 0){throw 'reparse'}
  $stage='acl';$a=$i.GetAccessControl([Security.AccessControl.AccessControlSections]::Access -bor [Security.AccessControl.AccessControlSections]::Owner)
  $stage='owner';try{$ownerSid=([Security.Principal.NTAccount]$a.Owner).Translate([Security.Principal.SecurityIdentifier]).Value}catch{try{$ownerSid=([Security.Principal.SecurityIdentifier]$a.Owner).Value}catch{throw 'owner-translation'}}
  if($ownerSid -notin $trusted){throw 'owner'}
  $inherit=if($i.PSIsContainer){[Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'}else{[Security.AccessControl.InheritanceFlags]::None}
  $stage='protect';$a.SetAccessRuleProtection($true,$false)
  $stage='purge';$seen=@{}
  foreach($r in @($a.Access)){
   try{$sid=$r.IdentityReference.Translate([Security.Principal.SecurityIdentifier])}catch{throw 'ace-translation'}
   if(!$seen.ContainsKey($sid.Value)){$a.PurgeAccessRules($sid);$seen[$sid.Value]=$true}
  }
  $stage='add';foreach($sid in @($me,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'),[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))){$a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,[Security.AccessControl.FileSystemRights]::FullControl,$inherit,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow))}
  $stage='set-dacl';$i.SetAccessControl($a)
 }catch{
  $x=$_.Exception;$code=0
  while($x){if($x -is [System.ComponentModel.Win32Exception]){$code=[int]$x.NativeErrorCode;break};$x=$x.InnerException}
  @{ok=$false;stage=$stage;code=$code}|ConvertTo-Json -Compress;exit
 }
 @{ok=$true}|ConvertTo-Json -Compress;exit
}
if($q.action -ne 'verify'){throw 'action'}
$danger=[Int64]([Security.AccessControl.FileSystemRights]::WriteData -bor [Security.AccessControl.FileSystemRights]::CreateFiles -bor [Security.AccessControl.FileSystemRights]::CreateDirectories -bor [Security.AccessControl.FileSystemRights]::AppendData -bor [Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Modify -bor [Security.AccessControl.FileSystemRights]::FullControl -bor [Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership)
$genericWrite=[Int64]0x40000000;$genericAll=[Int64]0x10000000;$out=@()
foreach($e in $q.entries){
 $p=[string]$e.path;$i=Get-Item -LiteralPath $p -Force
 if(($i.Attributes -band [IO.FileAttributes]::ReparsePoint)-ne 0){throw 'reparse'}
 if(($e.kind -eq 'dir' -and !$i.PSIsContainer) -or ($e.kind -eq 'file' -and $i.PSIsContainer)){throw 'kind'}
 $a=$i.GetAccessControl([Security.AccessControl.AccessControlSections]::Access -bor [Security.AccessControl.AccessControlSections]::Owner)
 try{$ownerSid=([Security.Principal.NTAccount]$a.Owner).Translate([Security.Principal.SecurityIdentifier]).Value}catch{try{$ownerSid=([Security.Principal.SecurityIdentifier]$a.Owner).Value}catch{throw 'owner-translation'}}
 if($ownerSid -notin $trusted){throw 'owner'}
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


def _native_windows_directory() -> str:
    if os.name != "nt":
        raise RuntimeError("Windows provider-lock policy unavailable")
    kernel = _kernel32()
    buffer = ctypes.create_unicode_buffer(32768)
    size = kernel.GetWindowsDirectoryW(buffer, len(buffer))
    if not size or size >= len(buffer):
        raise RuntimeError("Windows provider-lock policy unavailable")
    return buffer.value


def _canonical_local_path(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.rstrip(" .") or not ntpath.isabs(value):
        raise RuntimeError("Windows provider-lock policy unavailable")
    if value.startswith(("\\\\", "\\\\?\\", "\\??\\")) or re.search(r'[<>"|?*\x00-\x1f]', value) or ":" in value[2:]:
        raise RuntimeError("Windows provider-lock policy unavailable")
    parsed = PureWindowsPath(value)
    if not re.fullmatch(r"[A-Za-z]:", parsed.drive) or parsed.root != "\\" or any(part in {".", ".."} or part != part.rstrip(" .") for part in parsed.parts[1:]):
        raise RuntimeError("Windows provider-lock policy unavailable")
    return str(parsed)


def _verified_existing_component(path: str, directory: bool) -> tuple[int, int]:
    kernel = _kernel32(); flags = 0x00200000 | (0x02000000 if directory else 0)
    handle = kernel.CreateFileW(path, 0x00020000 | 0x80, 0x00000001 | 0x00000002, None, 3, flags, None)
    invalid = wintypes.HANDLE(-1).value
    if handle == invalid:
        raise RuntimeError("Windows provider-lock policy unavailable")
    try:
        info = _BY_HANDLE_FILE_INFORMATION()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)) or info.attributes & 0x400 or bool(info.attributes & 0x10) != directory:
            raise RuntimeError("Windows provider-lock policy unavailable")
        final = ctypes.create_unicode_buffer(32768)
        size = kernel.GetFinalPathNameByHandleW(handle, final, len(final), 0)
        observed = final.value[4:] if final.value.startswith("\\\\?\\") else final.value
        if not size or size >= len(final) or ntpath.normcase(observed) != ntpath.normcase(path):
            raise RuntimeError("Windows provider-lock policy unavailable")
        _validate_native_acl(handle)
        return int(info.volume), (int(info.index_high) << 32) | int(info.index_low)
    finally:
        kernel.CloseHandle(handle)


def _powershell_path() -> str:
    """Resolve and no-follow verify inbox Windows PowerShell without PATH/env trust."""
    root = _canonical_local_path(_native_windows_directory())
    parts = [root, ntpath.join(root,"System32"), ntpath.join(root,"System32","WindowsPowerShell"), ntpath.join(root,"System32","WindowsPowerShell","v1.0")]
    for component in parts: _verified_existing_component(component, True)
    candidate = ntpath.join(parts[-1], "powershell.exe")
    identity = _verified_existing_component(candidate, False)
    # subprocess cannot be created from an already-open executable handle. Keep
    # the no-follow canonical check adjacent to launch and require stable file ID.
    if _verified_existing_component(candidate, False) != identity:
        raise RuntimeError("Windows provider-lock policy unavailable")
    return candidate


def _run(payload: dict) -> dict:
    if os.name != "nt":
        raise RuntimeError("Windows native file policy called off Windows")
    executable = _powershell_path()
    try:
        result = subprocess.run(
            [executable, "-NoLogo", "-NoProfile", "-NonInteractive",
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
    value = _run({"action": "private", "path": str(path)})
    if value.get("ok") is not True:
        stage = value.get("stage")
        code = value.get("code")
        allowed_stages = {"item", "acl", "owner", "protect", "purge", "add", "set-dacl"}
        if stage in allowed_stages and isinstance(code, int):
            raise RuntimeError(f"Windows private ACL initialization failed ({stage}:{code})")
        raise RuntimeError("Windows private ACL initialization failed")


def verify_many(entries: list[tuple[Path, str, bool]]) -> list[tuple[int, int]]:
    """Verify an ordered set in one native policy process.

    Repeated entries are intentional TOCTOU sentinels. Batching avoids multiple
    PowerShell startups without weakening any owner/DACL/identity check.
    """
    request = [{"path": str(path), "kind": kind, "container": container}
               for path, kind, container in entries]
    rows = _run({"action": "verify", "entries": request}).get("entries")
    if not isinstance(rows, list) or len(rows) != len(request):
        raise RuntimeError("Windows provider-lock identity unavailable")
    identities = []
    for expected, row in zip(request, rows):
        if not isinstance(row, dict) or row.get("path") != expected["path"]:
            raise RuntimeError("Windows provider-lock identity unavailable")
        text = row.get("identity")
        if not isinstance(text, str) or len(text) != 25 or text[8] != ":":
            raise RuntimeError("Windows provider-lock identity unavailable")
        try:
            identities.append((int(text[:8], 16), int(text[9:], 16)))
        except ValueError as exc:
            raise RuntimeError("Windows provider-lock identity unavailable") from exc
    return identities


def verify(path: Path, *, kind: str, container: bool = False) -> tuple[int, int]:
    return verify_many([(path, kind, container)])[0]


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("creation_low", wintypes.DWORD),
                ("creation_high", wintypes.DWORD), ("access_low", wintypes.DWORD),
                ("access_high", wintypes.DWORD), ("write_low", wintypes.DWORD),
                ("write_high", wintypes.DWORD), ("volume", wintypes.DWORD),
                ("size_high", wintypes.DWORD), ("size_low", wintypes.DWORD),
                ("links", wintypes.DWORD), ("index_high", wintypes.DWORD),
                ("index_low", wintypes.DWORD)]


class _ACE_HEADER(ctypes.Structure):
    _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte), ("AceSize", wintypes.WORD)]


class _ACL_SIZE_INFORMATION(ctypes.Structure):
    _fields_ = [("AceCount", wintypes.DWORD), ("AclBytesInUse", wintypes.DWORD), ("AclBytesFree", wintypes.DWORD)]


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


_kernel = None
_advapi = None
SE_FILE_OBJECT = 1
OWNER_SECURITY_INFORMATION = 0x1
DACL_SECURITY_INFORMATION = 0x4
ACCESS_ALLOWED_ACE_TYPE = 0
ACCESS_ALLOWED_OBJECT_ACE_TYPE = 5
ACCESS_ALLOWED_CALLBACK_ACE_TYPE = 9
ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE = 11
_OBJECT_ACE_TYPES = frozenset((ACCESS_ALLOWED_OBJECT_ACE_TYPE, ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE))
_SUPPORTED_ALLOW_ACE_TYPES = frozenset((ACCESS_ALLOWED_ACE_TYPE, ACCESS_ALLOWED_CALLBACK_ACE_TYPE, *_OBJECT_ACE_TYPES))


def _sid_text(sid) -> str:
    string = wintypes.LPWSTR()
    if not _advapi32().ConvertSidToStringSidW(sid, ctypes.byref(string)):
        raise RuntimeError("Windows provider-lock policy unavailable")
    try: return string.value
    finally: _kernel32().LocalFree(ctypes.cast(string, wintypes.LPVOID))


def _acl_policy(owner: str, allow_entries: list[tuple[str, int]]) -> None:
    trusted={"S-1-5-18","S-1-5-32-544","S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"}
    write_mask=0x10000000|0x40000000|0x00010000|0x00040000|0x00080000|0x00000156
    if owner not in trusted or any(mask & write_mask and sid not in trusted for sid,mask in allow_entries):
        raise RuntimeError("Windows provider-lock policy unavailable")


def _allow_ace_fields(ace: int, ace_type: int, ace_size: int) -> tuple[int, wintypes.LPVOID]:
    """Return a bounded mask/SID view for supported allow ACE layouts."""
    if ace_type not in _SUPPORTED_ALLOW_ACE_TYPES or ace_size < 16:
        raise RuntimeError("Windows provider-lock policy unavailable")
    mask=ctypes.cast(ace+4,ctypes.POINTER(ctypes.c_uint32)).contents.value
    sid_offset=8
    if ace_type in _OBJECT_ACE_TYPES:
        if ace_size < 20: raise RuntimeError("Windows provider-lock policy unavailable")
        flags=ctypes.cast(ace+8,ctypes.POINTER(ctypes.c_uint32)).contents.value
        if flags & ~0x3: raise RuntimeError("Windows provider-lock policy unavailable")
        sid_offset=12 + (16 if flags & 0x1 else 0) + (16 if flags & 0x2 else 0)
    if sid_offset + 8 > ace_size: raise RuntimeError("Windows provider-lock policy unavailable")
    sid=wintypes.LPVOID(ace+sid_offset); advapi=_advapi32()
    if not advapi.IsValidSid(sid): raise RuntimeError("Windows provider-lock policy unavailable")
    sid_length=advapi.GetLengthSid(sid)
    if sid_length < 8 or sid_offset + sid_length > ace_size: raise RuntimeError("Windows provider-lock policy unavailable")
    return mask,sid


def _validate_native_acl(handle) -> None:
    """Validate owner and reject write-capable allow ACEs for untrusted SIDs."""
    advapi=_advapi32(); owner=wintypes.LPVOID(); dacl=wintypes.LPVOID(); descriptor=wintypes.LPVOID()
    if advapi.GetSecurityInfo(handle,SE_FILE_OBJECT,OWNER_SECURITY_INFORMATION|DACL_SECURITY_INFORMATION,ctypes.byref(owner),None,ctypes.byref(dacl),None,ctypes.byref(descriptor)):
        raise RuntimeError("Windows provider-lock policy unavailable")
    try:
        if not dacl: raise RuntimeError("Windows provider-lock policy unavailable")
        info=_ACL_SIZE_INFORMATION()
        if not advapi.GetAclInformation(dacl,ctypes.byref(info),ctypes.sizeof(info),2): raise RuntimeError("Windows provider-lock policy unavailable")
        entries=[]; consumed=ctypes.sizeof(wintypes.DWORD)*2
        for index in range(info.AceCount):
            ace=wintypes.LPVOID()
            if not advapi.GetAce(dacl,index,ctypes.byref(ace)): raise RuntimeError("Windows provider-lock policy unavailable")
            header=ctypes.cast(ace,ctypes.POINTER(_ACE_HEADER)).contents
            if header.AceSize < 8 or consumed + header.AceSize > info.AclBytesInUse: raise RuntimeError("Windows provider-lock policy unavailable")
            consumed += header.AceSize
            if header.AceType in _SUPPORTED_ALLOW_ACE_TYPES:
                mask,sid=_allow_ace_fields(ace.value,header.AceType,header.AceSize)
                entries.append((_sid_text(sid),mask))
            elif header.AceType == 4:  # obsolete compound allow layout: fail closed
                raise RuntimeError("Windows provider-lock policy unavailable")
        _acl_policy(_sid_text(owner),entries)
    finally: _kernel32().LocalFree(descriptor)


def _advapi32():
    global _advapi
    if _advapi is None:
        api=ctypes.WinDLL("advapi32",use_last_error=True)
        api.GetSecurityInfo.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(wintypes.LPVOID),ctypes.POINTER(wintypes.LPVOID),ctypes.POINTER(wintypes.LPVOID),ctypes.POINTER(wintypes.LPVOID),ctypes.POINTER(wintypes.LPVOID)];api.GetSecurityInfo.restype=wintypes.DWORD
        api.GetAclInformation.argtypes=[wintypes.LPVOID,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD];api.GetAclInformation.restype=wintypes.BOOL
        api.GetAce.argtypes=[wintypes.LPVOID,wintypes.DWORD,ctypes.POINTER(wintypes.LPVOID)];api.GetAce.restype=wintypes.BOOL
        api.ConvertSidToStringSidW.argtypes=[wintypes.LPVOID,ctypes.POINTER(wintypes.LPWSTR)];api.ConvertSidToStringSidW.restype=wintypes.BOOL
        api.IsValidSid.argtypes=[wintypes.LPVOID];api.IsValidSid.restype=wintypes.BOOL
        api.GetLengthSid.argtypes=[wintypes.LPVOID];api.GetLengthSid.restype=wintypes.DWORD
        _advapi=api
    return _advapi


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
        kernel.GetWindowsDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        kernel.GetWindowsDirectoryW.restype = wintypes.UINT
        kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [wintypes.LPVOID]
        kernel.LocalFree.restype = wintypes.LPVOID
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
