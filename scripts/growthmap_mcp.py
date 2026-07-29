#!/usr/bin/env python3
"""Minimal MCP stdio adapter; every tool call is forwarded to Agent Port REST."""
import json,os,sys,urllib.request,urllib.error
TOOLS={"capabilities":("GET","/capabilities"),"read_project":("GET","/project"),"read_graph":("GET","/graph"),"get_context":("GET","/context/{target_id}"),"propose":("POST","/proposals"),"apply_batch":("POST","/batch"),"report_event":("POST","/events"),"submit_readback":("POST","/readbacks")}
def send(obj): sys.stdout.write(json.dumps(obj,separators=(",",":"))+"\n");sys.stdout.flush()
def call(name,args):
    method,path=TOOLS[name]
    if "{target_id}" in path:path=path.replace("{target_id}",str(args.pop("target_id")))
    data=json.dumps(args).encode() if method=="POST" else None
    req=urllib.request.Request(os.getenv("GROWTHMAP_AGENT_BASE_URL","http://127.0.0.1:8100/agent/v1").rstrip("/")+path,data=data,method=method,headers={"Authorization":"Bearer "+os.environ["GROWTHMAP_AGENT_TOKEN"],"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read())
for line in sys.stdin:
 try:
  q=json.loads(line);mid=q.get("id");method=q.get("method")
  if method=="initialize": result={"protocolVersion":"2025-03-26","capabilities":{"tools":{}},"serverInfo":{"name":"growthmap-agent-port","version":"1.0"}}
  elif method=="notifications/initialized":continue
  elif method=="tools/list":result={"tools":[{"name":n,"description":"GrowthMap Agent Port REST: "+n,"inputSchema":{"type":"object","additionalProperties":True}} for n in TOOLS]}
  elif method=="tools/call":
   p=q["params"];result={"content":[{"type":"text","text":json.dumps(call(p["name"],dict(p.get("arguments",{}))),ensure_ascii=False)}]}
  else:raise ValueError("method not found")
  send({"jsonrpc":"2.0","id":mid,"result":result})
 except Exception as e:send({"jsonrpc":"2.0","id":q.get("id") if isinstance(q,dict) else None,"error":{"code":-32000,"message":str(e)}})
