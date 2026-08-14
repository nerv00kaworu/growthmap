"""Windows Credential Manager seam for GrowthMap Agent Port (stdlib ctypes only)."""
import ctypes,json,sys
from ctypes import wintypes
TYPE_GENERIC=1;PERSIST_SESSION=1;PERSIST_LOCAL_MACHINE=2;MAX_BLOB=4096
class CREDENTIALW(ctypes.Structure):
 _fields_=[("Flags",wintypes.DWORD),("Type",wintypes.DWORD),("TargetName",wintypes.LPWSTR),("Comment",wintypes.LPWSTR),("LastWritten",wintypes.FILETIME),("CredentialBlobSize",wintypes.DWORD),("CredentialBlob",ctypes.POINTER(ctypes.c_ubyte)),("Persist",wintypes.DWORD),("AttributeCount",wintypes.DWORD),("Attributes",ctypes.c_void_p),("TargetAlias",wintypes.LPWSTR),("UserName",wintypes.LPWSTR)]
def target(major,installation):
 value=f"GrowthMap/AgentPort/v1/product-{int(major)}/installation-{installation}"
 if len(value)>512 or "\0" in value:return (_ for _ in ()).throw(ValueError("invalid credential target"))
 return value
def _api():
 if sys.platform!="win32":raise OSError("packaged Agent Access requires Windows")
 a=ctypes.WinDLL("Advapi32",use_last_error=True)
 a.CredWriteW.argtypes=[ctypes.POINTER(CREDENTIALW),wintypes.DWORD];a.CredWriteW.restype=wintypes.BOOL
 a.CredReadW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(ctypes.POINTER(CREDENTIALW))];a.CredReadW.restype=wintypes.BOOL
 a.CredDeleteW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD];a.CredDeleteW.restype=wintypes.BOOL
 a.CredFree.argtypes=[ctypes.c_void_p];a.CredFree.restype=None
 return a
def encode(value):
 if set(value)!={"schema","endpoint","token","instance_nonce","product_major"} or value["schema"]!="growthmap.agent-credential.v1" or not str(value["token"]).startswith("gm1."):raise ValueError("invalid credential payload")
 raw=json.dumps(value,separators=(",",":"),ensure_ascii=False).encode("utf-8")
 if len(raw)>MAX_BLOB:raise ValueError("credential payload too large")
 return raw
def write(name,value,persist):
 a=_api();raw=encode(value);buf=(ctypes.c_ubyte*len(raw)).from_buffer_copy(raw);c=CREDENTIALW(Type=TYPE_GENERIC,TargetName=name,CredentialBlobSize=len(raw),CredentialBlob=buf,Persist=PERSIST_LOCAL_MACHINE if persist=="unlimited" else PERSIST_SESSION,UserName="GrowthMap")
 try:
  if not a.CredWriteW(ctypes.byref(c),0):raise ctypes.WinError(ctypes.get_last_error())
 finally:ctypes.memset(ctypes.addressof(buf),0,len(raw))
def read(name):
 a=_api();p=ctypes.POINTER(CREDENTIALW)()
 if not a.CredReadW(name,TYPE_GENERIC,0,ctypes.byref(p)):raise ctypes.WinError(ctypes.get_last_error())
 try:
  c=p.contents
  if c.CredentialBlobSize>MAX_BLOB:raise ValueError("credential payload too large")
  value=json.loads(ctypes.string_at(c.CredentialBlob,c.CredentialBlobSize).decode("utf-8"));encode(value);return value
 finally:a.CredFree(p)
def delete(name):
 a=_api()
 if not a.CredDeleteW(name,TYPE_GENERIC,0):
  error=ctypes.get_last_error()
  if error!=1168:raise ctypes.WinError(error)
