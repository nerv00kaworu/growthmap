#!/usr/bin/env python3
"""MCP stdio thin adapter for localhost Agent Port REST (protocol 2025-11-25)."""
import json,os,sys,urllib.error,urllib.parse,urllib.request
from pathlib import Path
MAX_LINE=1_048_576;PROTOCOL="2025-11-25"
def canonical_schemas():
 backend=Path(__file__).resolve().parents[1]/"src"/"backend"
 sys.path.insert(0,str(backend))
 from agent_port.schemas import Batch,ProposalIn,EventIn,ReadbackIn
 return {"propose":ProposalIn.model_json_schema(),"apply_batch":Batch.model_json_schema(),
         "report_event":EventIn.model_json_schema(),"submit_readback":ReadbackIn.model_json_schema()}
_STRICT=canonical_schemas()
TOOLS={
 "capabilities":("GET","/capabilities",{"type":"object","additionalProperties":False}),
 "read_project":("GET","/project",{"type":"object","additionalProperties":False}),
 "read_graph":("GET","/graph",{"type":"object","additionalProperties":False}),
 "get_context":("GET","/context/{target_id}",{"type":"object","properties":{"target_id":{"type":"string","format":"uuid"},"objective":{"type":"string","maxLength":2000}},"required":["target_id"],"additionalProperties":False}),
 "propose":("POST","/proposals",_STRICT["propose"]),
 "apply_batch":("POST","/batch",_STRICT["apply_batch"]),
 "report_event":("POST","/events",_STRICT["report_event"]),
 "submit_readback":("POST","/readbacks",_STRICT["submit_readback"])}
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):return None
def send(o):
 # JSON-RPC over stdio is UTF-8 regardless of the host console code page.
 # Write protocol bytes directly so Windows cp1252/charmap cannot corrupt or
 # reject Unicode objectives, tool results, or error messages.
 sys.stdout.buffer.write(json.dumps(o,separators=(",",":"),ensure_ascii=False).encode("utf-8")+b"\n");sys.stdout.buffer.flush()
def err(mid,code,message):send({"jsonrpc":"2.0","id":mid,"error":{"code":code,"message":message}})
def base_url():
 raw=os.getenv("GROWTHMAP_AGENT_BASE_URL","http://127.0.0.1:8100/agent/v1");u=urllib.parse.urlsplit(raw)
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
  objective=args.pop("objective","")
  if not isinstance(objective,str) or len(objective)>2000:raise ValueError("objective must be a string of at most 2000 characters")
  path+="?"+urllib.parse.urlencode({"objective":objective})
 if method=="GET" and args:raise ValueError("unknown GET arguments")
 data=json.dumps(args,separators=(",",":")).encode() if method=="POST" else None
 secret=os.environ.get("GROWTHMAP_AGENT_TOKEN","")
 if not secret:raise ValueError("agent token required")
 req=urllib.request.Request(base_url()+path,data=data,method=method,headers={"Authorization":"Bearer "+secret,"Content-Type":"application/json"})
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
