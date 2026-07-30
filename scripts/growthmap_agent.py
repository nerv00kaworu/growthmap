#!/usr/bin/env python3
"""Thin JSON CLI for GrowthMap Agent Port v1. Local HTTP only; redirects forbidden."""
import argparse,json,os,stat,sys,urllib.error,urllib.parse,urllib.request
COMMANDS={"capabilities":("GET","/capabilities"),"project":("GET","/project"),"graph":("GET","/graph"),"context":("GET","/context/{target}"),"propose":("POST","/proposals"),"apply-batch":("POST","/batch"),"report-event":("POST","/events"),"submit-readback":("POST","/readbacks")}
MAX_TOKEN=4096
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):return None
def base_url(raw):
 u=urllib.parse.urlsplit(raw)
 if u.scheme!="http" or u.username or u.password or u.query or u.fragment or not u.hostname or u.hostname.lower() not in {"localhost","127.0.0.1","::1"}:
  raise ValueError("base URL must be plain HTTP on exact loopback/localhost without userinfo, query, or fragment")
 try:
  if u.port is None:raise ValueError("base URL requires an explicit port")
 except ValueError:raise ValueError("invalid base URL port")
 return raw.rstrip("/")
def token(args):
 sources=sum(bool(x) for x in (os.getenv("GROWTHMAP_AGENT_TOKEN"),args.token_file,args.token_stdin))
 if sources!=1:raise ValueError("set exactly one token source: env, --token-file, or --token-stdin")
 if args.token_file:
  st=os.lstat(args.token_file)
  if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):raise ValueError("token file must be a regular non-symlink")
  if os.name=="posix" and stat.S_IMODE(st.st_mode)&0o077:raise ValueError("token file permissions must be owner-only")
  if st.st_size>MAX_TOKEN:raise ValueError("token file is too large")
  with open(args.token_file,encoding="utf8") as f:value=f.read(MAX_TOKEN+1).strip()
 elif args.token_stdin:value=sys.stdin.readline(MAX_TOKEN+1).strip()
 else:value=os.environ["GROWTHMAP_AGENT_TOKEN"]
 if not value or len(value)>MAX_TOKEN:raise ValueError("invalid token length")
 return value
def main():
 p=argparse.ArgumentParser(prog="growthmap-agent");p.add_argument("command",choices=COMMANDS);p.add_argument("--base-url",default=os.getenv("GROWTHMAP_AGENT_BASE_URL","http://127.0.0.1:8100/agent/v1"));p.add_argument("--token-file");p.add_argument("--token-stdin",action="store_true");p.add_argument("--target");p.add_argument("--objective",default="");p.add_argument("--input",default="-");a=p.parse_args()
 base=base_url(a.base_url);secret=token(a);method,path=COMMANDS[a.command];body=None
 if "{target}" in path:
  if not a.target:raise ValueError("--target required")
  if len(a.objective)>2000:raise ValueError("--objective exceeds 2000 characters")
  path=path.replace("{target}",urllib.parse.quote(a.target,safe=""))+"?"+urllib.parse.urlencode({"objective":a.objective})
 if method=="POST":body=(sys.stdin.read() if a.input=="-" else open(a.input,encoding="utf8").read()).encode()
 req=urllib.request.Request(base+path,data=body,method=method,headers={"Authorization":"Bearer "+secret,"Content-Type":"application/json"})
 try:
  with urllib.request.build_opener(NoRedirect).open(req,timeout=30) as r:print(r.read().decode());return 0
 except urllib.error.HTTPError as e:
  data=e.read(262144).decode(errors="replace");sys.stderr.write(data+"\n");return 10 if e.code==409 else 4 if e.code in (401,403) else 3
 except Exception as e:sys.stderr.write(json.dumps({"error":type(e).__name__})+"\n");return 2
if __name__=="__main__":
 try:raise SystemExit(main())
 except (ValueError,OSError) as e:sys.stderr.write(json.dumps({"error":str(e)})+"\n");raise SystemExit(2)
