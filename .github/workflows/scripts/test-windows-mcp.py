#!/usr/bin/env python3
"""Genuine-Windows integration harness for the frozen MCP executable.

Uses only stdlib plus the already-built growthmap-mcp.exe. Secrets are supplied to
Credential Manager on stdin and to the fake sidecar through a private control file;
they never enter child argv, child env, generic config, descriptor, or captured logs.
"""
import argparse, datetime, http.server, json, os, pathlib, secrets, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
MAX_OUTPUT=262_144
INVOCATIONS=[]

def control_read(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))

class Sidecar(http.server.BaseHTTPRequestHandler):
    server_version="LocalFixture/1"
    def log_message(self, *_): pass
    def body(self, status, value):
        raw=json.dumps(value,separators=(",",":")).encode();self.send_response(status);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        state=control_read(self.server.control)
        if self.path=="/agent/v1/capabilities":return self.body(200,{"instance_nonce":state["nonce"],"product_major":1,"version":"1.0"})
        if self.path=="/agent/v1/project":
            supplied=self.headers.get("Authorization","")
            if state["revoked"] or supplied!="Bearer "+state["token"]:return self.body(401,{"code":"GRANT_INACTIVE"})
            return self.body(200,{"id":"fixture","name":"Fixture"})
        self.body(404,{"code":"NOT_FOUND"})

def server_mode(control, ready):
    server=http.server.ThreadingHTTPServer(("127.0.0.1",0),Sidecar);server.control=control
    pathlib.Path(ready).write_text(json.dumps({"port":server.server_address[1],"pid":os.getpid()}),encoding="utf-8")
    server.serve_forever()

def bounded_run(exe,args,stdin,env,expect=0,timeout=12):
    INVOCATIONS.append([str(exe),*args])
    p=subprocess.Popen([str(exe),*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,text=False,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    try: out,err=p.communicate(stdin.encode(),timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill();out,err=p.communicate();raise AssertionError("MCP child timed out")
    if len(out)+len(err)>MAX_OUTPUT:raise AssertionError("MCP child output exceeded bound")
    if (p.returncode==expect) is False:raise AssertionError(f"MCP child status {p.returncode}, expected {expect}")
    return out,err

def mcp_exchange(exe,env,include_call=True,expect_call_error=False):
    frames=[{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"windows-fixture","version":"1"}}},{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}]
    if include_call:frames.append({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"read_project","arguments":{}}})
    out,err=bounded_run(exe,[],"".join(json.dumps(x,separators=(",",":"))+"\n" for x in frames),env)
    rows=[json.loads(x) for x in out.decode("utf-8").splitlines() if x]
    by={x.get("id"):x for x in rows}
    assert by[1]["result"]["protocolVersion"]=="2025-11-25"
    assert len(by[2]["result"]["tools"])>=2
    if include_call:assert by[3]["result"]["isError"] is expect_call_error
    return out,err,by

def write_control(path,token,nonce,revoked=False):
    pathlib.Path(path).write_text(json.dumps({"token":token,"nonce":nonce,"revoked":revoked},separators=(",",":")),encoding="utf-8")

def start_sidecar(script,control,ready,base_env):
    pathlib.Path(ready).unlink(missing_ok=True)
    command=[sys.executable,str(script),"--server",str(control),str(ready)];INVOCATIONS.append(command)
    p=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=base_env,text=False,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    deadline=time.time()+10
    while time.time()<deadline and not pathlib.Path(ready).exists():
        if p.poll() is not None:raise AssertionError("fake sidecar exited before ready")
        time.sleep(.05)
    if not pathlib.Path(ready).exists():p.kill();raise AssertionError("fake sidecar readiness timed out")
    state=json.loads(pathlib.Path(ready).read_text(encoding="utf-8"));return p,state["port"],state["pid"]

def stop_sidecar(p):
    p.terminate()
    try:p.wait(5)
    except subprocess.TimeoutExpired:p.kill();p.wait(5)
    out,err=p.communicate()
    if out or err:raise AssertionError("fake sidecar emitted unexpected log output")

def descriptor(exe,target,endpoint,nonce,sidecar_pid):
    return {"schema":"growthmap.agent-discovery.v1","protocol":"1.0","endpoint":endpoint,"sidecar_pid":sidecar_pid,"desktop_pid":os.getpid(),"instance_nonce":nonce,"product_major":1,"created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"credential_target":target,"mcp_executable":str(exe)}

def direct_project(endpoint,token,expected):
    req=urllib.request.Request(endpoint+"/project",headers={"Authorization":"Bearer "+token})
    try:
        with urllib.request.urlopen(req,timeout=3) as r:status=r.status
    except urllib.error.HTTPError as e:status=e.code
    assert status==expected,(status,expected)

def assert_no_leak(blobs,secret,port_strings,temp_root):
    forbidden=[secret,"session_token","license","device_id","DATABASE_URL",str(temp_root/"growthmap.db")]
    for name,value in blobs.items():
        text=value.decode("utf-8","replace") if isinstance(value,bytes) else json.dumps(value,separators=(",",":")) if not isinstance(value,str) else value
        for needle in forbidden:
            if needle and needle in text:raise AssertionError(f"prohibited value leaked in {name}")
        if name in {"argv","env","generic","stdout","stderr"}:
            for port in port_strings:
                if port in text:raise AssertionError(f"endpoint port leaked in {name}")

def integration(exe):
    reached=set();script=pathlib.Path(__file__).resolve()
    with tempfile.TemporaryDirectory(prefix="growthmap-mcp-win-") as raw:
        root=pathlib.Path(raw);local=root/"local";discovery=local/"GrowthMap"/"agent-access.json";discovery.parent.mkdir(parents=True)
        control=root/"sidecar-control.json";ready=root/"sidecar-ready.json"
        token="gm1."+secrets.token_hex(6)+"."+secrets.token_urlsafe(32);target=f"GrowthMap/AgentPort/v1/product-1/installation-{secrets.token_hex(16)}/primary"
        env={k:v for k,v in os.environ.items() if k in {"SystemRoot","WINDIR","PATH","PATHEXT","TEMP","TMP"}};env["LOCALAPPDATA"]=str(local)
        generic={"mcpServers":{"growthmap":{"command":str(exe)}}};logs=[];ports=[];sidecar=None
        try:
            nonce=secrets.token_hex(24);write_control(control,token,nonce);sidecar,port,pid=start_sidecar(script,control,ready,env);ports.append(str(port));endpoint=f"http://127.0.0.1:{port}/agent/v1"
            provision=json.dumps({"target":target,"persist":"session","credential":{"schema":"growthmap.agent-credential.v1","endpoint":endpoint,"token":token,"instance_nonce":nonce,"product_major":1}},separators=(",",":"))
            out,err=bounded_run(exe,["provision"],provision,env);logs += [("stdout",out),("stderr",err)];reached.add("credential_roundtrip")
            out,err=bounded_run(exe,["read"],json.dumps({"target":target}),env);logs += [("stdout",out),("stderr",err)]
            discovery.write_text(json.dumps(descriptor(exe,target,endpoint,nonce,pid),separators=(",",":")),encoding="utf-8")
            out,err,_=mcp_exchange(exe,env);logs += [("stdout",out),("stderr",err)];reached.add("ordinary_discovery_and_mcp")
            # The actual frozen executable must traverse the fixed LOCALAPPDATA descriptor symlink and fail closed.
            ordinary=root/"ordinary-descriptor.json";discovery.replace(ordinary)
            try:
                os.symlink(ordinary,discovery)
            except OSError as e:
                if getattr(e,"winerror",None)==1314:reached.add("reparse_creation_skipped_privilege")
                else:raise
            else:
                _,_,rows=mcp_exchange(exe,env,expect_call_error=True)
                reached.add("reparse_rejected_by_executable")
                discovery.unlink()
            if not discovery.exists():ordinary.replace(discovery)
            stop_sidecar(sidecar);sidecar=None
            nonce2=secrets.token_hex(24);write_control(control,token,nonce2);sidecar,port2,pid2=start_sidecar(script,control,ready,env);ports.append(str(port2));assert port2!=port
            endpoint2=f"http://127.0.0.1:{port2}/agent/v1"
            rebind=json.dumps({"target":target,"endpoint":endpoint2,"instance_nonce":nonce2,"product_major":1,"persist":"session"},separators=(",",":"))
            out,err=bounded_run(exe,["rebind"],rebind,env);logs += [("stdout",out),("stderr",err)]
            discovery.write_text(json.dumps(descriptor(exe,target,endpoint2,nonce2,pid2),separators=(",",":")),encoding="utf-8")
            out,err,_=mcp_exchange(exe,env);logs += [("stdout",out),("stderr",err)];reached.add("restart_rebind_persistence")
            direct_project(endpoint2,token,200);write_control(control,token,nonce2,True);direct_project(endpoint2,token,401)
            out,err,rows=mcp_exchange(exe,env,expect_call_error=True);logs += [("stdout",out),("stderr",err)];reached.add("revoke_blocks_bearer_and_mcp")
            out,err=bounded_run(exe,["delete"],json.dumps({"target":target}),env);logs += [("stdout",out),("stderr",err)]
            out,err=bounded_run(exe,["read"],json.dumps({"target":target}),env,expect=1);logs += [("stdout",out),("stderr",err)];reached.add("credential_deleted")
            desc=json.loads(discovery.read_text(encoding="utf-8"));assert token not in json.dumps(desc)
            evidence={"argv":INVOCATIONS,"env":env,"generic":generic,"descriptor":desc}
            for kind,value in logs:evidence[kind]=evidence.get(kind,b"")+value
            assert_no_leak(evidence,token,ports,root);reached.add("secret_evidence_checked")
        finally:
            if sidecar is not None:stop_sidecar(sidecar)
            try:bounded_run(exe,["delete"],json.dumps({"target":target}),env)
            except Exception:pass
        required={"credential_roundtrip","ordinary_discovery_and_mcp","restart_rebind_persistence","revoke_blocks_bearer_and_mcp","credential_deleted","secret_evidence_checked"}
        assert required<=reached,reached
        assert "reparse_rejected_by_executable" in reached or "reparse_creation_skipped_privilege" in reached

if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--server",nargs=2,metavar=("CONTROL","READY"));ap.add_argument("--exe")
    a=ap.parse_args()
    if a.server:server_mode(*a.server)
    else:
        if os.name!="nt":raise SystemExit("genuine Windows required")
        integration(pathlib.Path(a.exe).resolve())
