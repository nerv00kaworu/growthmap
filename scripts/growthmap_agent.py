#!/usr/bin/env python3
"""Thin JSON CLI for GrowthMap Agent Port v1. Tokens are accepted only via env/file/stdin."""
import argparse,json,os,sys,urllib.error,urllib.parse,urllib.request
COMMANDS={"capabilities":("GET","/capabilities"),"project":("GET","/project"),"graph":("GET","/graph"),"context":("GET","/context/{target}"),"propose":("POST","/proposals"),"apply-batch":("POST","/batch"),"report-event":("POST","/events"),"submit-readback":("POST","/readbacks")}
def token(args):
    sources=sum(bool(x) for x in (os.getenv("GROWTHMAP_AGENT_TOKEN"),args.token_file,args.token_stdin))
    if sources!=1: raise ValueError("set exactly one token source: env, --token-file, or --token-stdin")
    if args.token_file:return open(args.token_file,encoding="utf8").read().strip()
    if args.token_stdin:return sys.stdin.readline().strip()
    return os.environ["GROWTHMAP_AGENT_TOKEN"]
def main():
    p=argparse.ArgumentParser(prog="growthmap-agent");p.add_argument("command",choices=COMMANDS);p.add_argument("--base-url",default=os.getenv("GROWTHMAP_AGENT_BASE_URL","http://127.0.0.1:8100/agent/v1"));p.add_argument("--token-file");p.add_argument("--token-stdin",action="store_true");p.add_argument("--target");p.add_argument("--input",default="-");a=p.parse_args()
    method,path=COMMANDS[a.command];body=None
    if "{target}" in path:
        if not a.target: raise ValueError("--target required")
        path=path.replace("{target}",urllib.parse.quote(a.target,safe=""))
    if method=="POST": body=(sys.stdin.read() if a.input=="-" else open(a.input,encoding="utf8").read()).encode()
    req=urllib.request.Request(a.base_url.rstrip("/")+path,data=body,method=method,headers={"Authorization":"Bearer "+token(a),"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=30) as r: print(r.read().decode());return 0
    except urllib.error.HTTPError as e:
        sys.stderr.write(e.read().decode()+"\n");return 10 if e.code==409 else 4 if e.code in (401,403) else 3
    except Exception as e: sys.stderr.write(json.dumps({"error":str(e)})+"\n");return 2
if __name__=="__main__":
    try: raise SystemExit(main())
    except ValueError as e: sys.stderr.write(json.dumps({"error":str(e)})+"\n");raise SystemExit(2)
