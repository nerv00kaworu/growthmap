#!/usr/bin/env python3
"""MCP stdio thin adapter for localhost Agent Port REST (protocol 2025-11-25)."""
import json,os,sys,urllib.error,urllib.parse,urllib.request
from pathlib import Path
MAX_LINE=1_048_576;PROTOCOL="2025-11-25"
def configure_stdio_utf8():
 # Windows inherits the console code page (for example zh-TW CP950), while MCP
 # stdio is a bounded UTF-8 JSON-lines protocol.  Reconfigure text wrappers;
 # credential commands intentionally keep using the same binary stdin.
 for stream in (sys.stdin,sys.stdout,sys.stderr):
  reconfigure=getattr(stream,"reconfigure",None)
  if reconfigure:reconfigure(encoding="utf-8",errors="strict")
configure_stdio_utf8()
def resource(name):return Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))/name
_STRICT=json.loads(resource("growthmap_mcp_schemas.json").read_text(encoding="utf-8"))
_CREDENTIAL=None
def descriptor_path():
 if sys.platform!="win32":raise ValueError("packaged Agent Access requires Windows")
 root=os.getenv("LOCALAPPDATA","")
 if not root or not Path(root).is_absolute():raise ValueError("LOCALAPPDATA unavailable")
 import stat
 base=Path(root);parent=base/"GrowthMap"
 for component in (base,parent):
  info=component.lstat()
  if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or getattr(info,"st_file_attributes",0)&0x400:raise ValueError("unsafe discovery descriptor")
 return parent/"agent-access.json"
def _pid_live(pid):
 if sys.platform!="win32":
  try:os.kill(pid,0);return True
  except OSError:return False
 import ctypes
 from ctypes import wintypes
 k=ctypes.WinDLL("Kernel32",use_last_error=True);k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE;k.CloseHandle.argtypes=[wintypes.HANDLE];k.CloseHandle.restype=wintypes.BOOL
 h=k.OpenProcess(0x1000,False,pid)
 if not h:return False
 k.CloseHandle(h);return True
def _bounded_descriptor(f):
 import stat
 before=f.lstat()
 attrs=getattr(before,"st_file_attributes",0)
 if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or attrs&0x400 or before.st_size>16384:raise ValueError("unsafe discovery descriptor")
 flags=os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0)
 fd=os.open(f,flags)
 try:
  opened=os.fstat(fd)
  if not stat.S_ISREG(opened.st_mode) or opened.st_size>16384 or (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino):raise ValueError("unsafe discovery descriptor")
  raw=os.read(fd,16385)
  if len(raw)>16384 or os.read(fd,1):raise ValueError("oversize discovery descriptor")
  after=os.fstat(fd)
 finally:os.close(fd)
 final=f.lstat()
 identity=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns)
 if identity(opened)!=identity(after) or identity(before)!=identity(final):raise ValueError("discovery descriptor changed while reading")
 try:return json.loads(raw.decode("utf-8","strict"))
 except (UnicodeError,json.JSONDecodeError):raise ValueError("invalid discovery descriptor")
def discovered():
 global _CREDENTIAL
 if _CREDENTIAL:return _CREDENTIAL
 d=_bounded_descriptor(descriptor_path());keys={"schema","protocol","endpoint","sidecar_pid","desktop_pid","instance_nonce","product_major","created_at","credential_target","mcp_executable"}
 if set(d)!=keys or d["schema"]!="growthmap.agent-discovery.v1" or d["protocol"]!="1.0":raise ValueError("invalid discovery descriptor")
 if not isinstance(d["product_major"],int) or d["product_major"]<1 or not isinstance(d["instance_nonce"],str) or not 24<=len(d["instance_nonce"])<=128:raise ValueError("invalid discovery identity")
 import datetime
 try:created=datetime.datetime.fromisoformat(d["created_at"].replace("Z","+00:00"))
 except Exception:raise ValueError("invalid discovery timestamp")
 if created.tzinfo is None or abs((datetime.datetime.now(datetime.timezone.utc)-created).total_seconds())>366*86400:raise ValueError("invalid discovery timestamp")
 for pid in (d["sidecar_pid"],d["desktop_pid"]):
  if not isinstance(pid,int) or pid<=0 or not _pid_live(pid):raise ValueError("stale discovery descriptor")
 expected=str(Path(sys.executable).resolve())
 if getattr(sys,"frozen",False) and str(Path(d["mcp_executable"]).resolve()).casefold()!=expected.casefold():raise ValueError("discovery executable mismatch")
 if not isinstance(d["credential_target"],str) or not d["credential_target"].startswith(f"GrowthMap/AgentPort/v1/product-{d['product_major']}/installation-"):raise ValueError("invalid credential target")
 from growthmap_credential import read
 c=read(d["credential_target"])
 if c["endpoint"]!=d["endpoint"] or c["instance_nonce"]!=d["instance_nonce"] or c["product_major"]!=d["product_major"]:raise ValueError("credential identity mismatch")
 u=urllib.parse.urlsplit(d["endpoint"])
 if u.scheme!="http" or u.hostname!="127.0.0.1" or u.port is None or u.path!="/agent/v1" or u.query or u.fragment or u.username or u.password:raise ValueError("invalid discovery endpoint")
 cap=d["endpoint"]+"/capabilities"
 with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(cap),timeout=3) as r:identity=json.load(r)
 if set(identity)<{"instance_nonce","product_major","version"} or identity["instance_nonce"]!=d["instance_nonce"] or identity["product_major"]!=d["product_major"] or identity["version"]!=d["protocol"]:raise ValueError("sidecar identity mismatch")
 _CREDENTIAL=(d["endpoint"],c["token"]);return _CREDENTIAL
def credential_command(command):
 if sys.platform!="win32":raise SystemExit("packaged Agent Access requires Windows")
 if command=="provision":
  raw=sys.stdin.buffer.read(8193)
  if len(raw)>8192:raise SystemExit("provision input too large")
  q=json.loads(raw);expected={"target","persist","credential"}
  if set(q)!=expected or q["persist"] not in {"session","finite","unlimited"}:raise SystemExit("invalid provision request")
  from growthmap_credential import write;write(q["target"],q["credential"],q["persist"]);return {"status":"provisioned"}
 if command=="read":
  raw=sys.stdin.buffer.read(2049)
  if len(raw)>2048:raise SystemExit("read input too large")
  q=json.loads(raw)
  if set(q)!={"target"}:raise SystemExit("invalid read request")
  from growthmap_credential import read
  read(q["target"]);return {"status":"available"}
 if command=="delete":
  raw=sys.stdin.buffer.read(2049)
  if len(raw)>2048:raise SystemExit("delete input too large")
  q=json.loads(raw)
  if set(q)!={"target"}:raise SystemExit("invalid delete request")
  from growthmap_credential import delete;delete(q["target"]);return {"status":"deleted"}
 if command=="rebind":
  raw=sys.stdin.buffer.read(4097)
  if len(raw)>4096:raise SystemExit("rebind input too large")
  q=json.loads(raw)
  if set(q)!={"target","endpoint","instance_nonce","product_major","persist"}:raise SystemExit("invalid rebind request")
  from growthmap_credential import read,write
  c=read(q["target"]);c.update(endpoint=q["endpoint"],instance_nonce=q["instance_nonce"],product_major=q["product_major"]);write(q["target"],c,q["persist"]);return {"status":"rebound"}
 raise SystemExit("unknown command")

def dispatch_credential_argv():
 if len(sys.argv)==1:return False
 if len(sys.argv)!=2 or sys.argv[1] not in {"provision","read","delete","rebind"}:raise SystemExit("usage: growthmap-mcp [provision|read|delete|rebind]")
 result=credential_command(sys.argv[1])
 sys.stdout.write(json.dumps(result,separators=(",",":"))+"\n");sys.stdout.flush()
 return True

if dispatch_credential_argv():raise SystemExit(0)

TOOLS={
 "capabilities":("GET","/capabilities",{"type":"object","additionalProperties":False}),
 "list_projects":("GET","/projects",{"type":"object","additionalProperties":False}),
 "read_project":("GET","/project",{"type":"object","properties":{"project_id":{"type":"string","format":"uuid"}},"required":["project_id"],"additionalProperties":False}),
 "read_graph":("GET","/graph",{"type":"object","properties":{"project_id":{"type":"string","format":"uuid"}},"required":["project_id"],"additionalProperties":False}),
 "get_context":("GET","/context/{target_id}",{"type":"object","properties":{"project_id":{"type":"string","format":"uuid"},"target_id":{"type":"string","format":"uuid"}},"required":["project_id","target_id"],"additionalProperties":False}),
 "propose":("POST","/proposals",_STRICT["propose"]),
 "apply_batch":("POST","/batch",_STRICT["apply_batch"]),
 "report_event":("POST","/events",_STRICT["report_event"]),
 "submit_readback":("POST","/readbacks",_STRICT["submit_readback"])}
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):return None
def send(o):sys.stdout.write(json.dumps(o,separators=(",",":"),ensure_ascii=False)+"\n");sys.stdout.flush()
def err(mid,code,message):send({"jsonrpc":"2.0","id":mid,"error":{"code":code,"message":message}})
def base_url():
 raw=os.getenv("GROWTHMAP_AGENT_BASE_URL")
 if not raw:raw=discovered()[0]
 u=urllib.parse.urlsplit(raw)
 if u.scheme!="http" or u.username or u.password or u.query or u.fragment or u.hostname not in {"localhost","127.0.0.1","::1"}:raise ValueError("Agent Port base URL must be exact local plain HTTP")
 if u.port is None:raise ValueError("Agent Port base URL requires port")
 return raw.rstrip("/")
def depth(v,n=0):
 if n>12:raise ValueError("arguments exceed nesting limit")
 if isinstance(v,dict):
  if len(v)>1000:raise ValueError("too many fields")
  for x in v.values():depth(x,n+1)
 elif isinstance(v,list):
  if len(v)>1000:raise ValueError("too many items")
  for x in v:depth(x,n+1)
def call(name,args):
 if name not in TOOLS:raise KeyError("unknown tool")
 method,path,_=TOOLS[name];args=dict(args);depth(args)
 if "{target_id}" in path:
  if "target_id" not in args:raise ValueError("target_id required")
  path=path.replace("{target_id}",urllib.parse.quote(str(args.pop("target_id")),safe=""))
 query=""
 if method=="GET" and args: query="?"+urllib.parse.urlencode(args)
 data=json.dumps(args,separators=(",",":")).encode() if method=="POST" else None
 secret=os.environ.get("GROWTHMAP_AGENT_TOKEN","")
 if not secret:secret=discovered()[1]
 req=urllib.request.Request(base_url()+path+query,data=data,method=method,headers={"Authorization":"Bearer "+secret,"Content-Type":"application/json"})
 try:
  with urllib.request.build_opener(NoRedirect).open(req,timeout=30) as r:return json.loads(r.read(1_048_577))
 except urllib.error.HTTPError as e:
  try:detail=json.loads(e.read(262144))
  except Exception:detail={"status":e.code}
  raise RuntimeError(json.dumps(detail,separators=(",",":")))
def handle(q):
 if not isinstance(q,dict) or q.get("jsonrpc")!="2.0" or not isinstance(q.get("method"),str):raise TypeError("Invalid Request")
 mid=q.get("id");method=q["method"];params=q.get("params",{})
 if not isinstance(params,dict):raise ValueError("params must be object")
 if method=="initialize":
  requested=params.get("protocolVersion")
  if requested and requested!=PROTOCOL:raise ValueError("unsupported protocol version")
  return {"protocolVersion":PROTOCOL,"capabilities":{"tools":{"listChanged":False}},"serverInfo":{"name":"growthmap-agent-port","version":"1.0"}}
 if method=="notifications/initialized":return None
 if method=="tools/list":return {"tools":[{"name":n,"description":"GrowthMap Agent Port REST tool: "+n,"inputSchema":v[2]} for n,v in TOOLS.items()]}
 if method=="tools/call":
  name=params.get("name");args=params.get("arguments",{})
  if name not in TOOLS:return {"content":[{"type":"text","text":"Unknown tool"}],"isError":True}
  try:value=call(name,args)
  except Exception as e:return {"content":[{"type":"text","text":str(e)}],"isError":True}
  return {"content":[{"type":"text","text":json.dumps(value,ensure_ascii=False)}],"isError":False}
 raise KeyError("Method not found")
for raw in sys.stdin.buffer:
 mid=None
 try:
  if len(raw)>MAX_LINE:raise OverflowError("frame too large")
  q=json.loads(raw);mid=q.get("id") if isinstance(q,dict) else None;result=handle(q)
  if result is not None and "id" in q:send({"jsonrpc":"2.0","id":mid,"result":result})
 except json.JSONDecodeError:err(None,-32700,"Parse error")
 except TypeError:err(mid,-32600,"Invalid Request")
 except KeyError:err(mid,-32601,"Method not found")
 except (ValueError,OverflowError) as e:err(mid,-32602,str(e))
 except Exception:err(mid,-32603,"Internal error")
