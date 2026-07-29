"""Official MCP SDK conformance plus raw malformed-frame recovery."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

ROOT = Path(__file__).parents[3]
BACKEND = ROOT / "src/backend"
ADAPTER = ROOT / "scripts/growthmap_mcp.py"
TOKEN = "mcp-human-control-test"

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]

def request(url, method="GET", body=None, token=None):
    headers={"Content-Type":"application/json"}
    if token: headers["Authorization"]="Bearer "+token
    req=urllib.request.Request(url,data=json.dumps(body).encode() if body is not None else None,method=method,headers=headers)
    with urllib.request.urlopen(req,timeout=5) as r:return json.load(r)

@pytest.mark.anyio
async def test_official_client_session_live_uvicorn():
    port=free_port()
    with tempfile.TemporaryDirectory(prefix="gm-mcp-") as td:
        env={**os.environ,"PYTHONPATH":str(BACKEND),"DATABASE_URL":f"sqlite+aiosqlite:///{td}/db.sqlite","APP_ENV":"test","GROWTHMAP_HUMAN_CONTROL_TOKEN":TOKEN}
        server=subprocess.Popen([sys.executable,"-m","uvicorn","main:app","--host","127.0.0.1","--port",str(port)],cwd=BACKEND,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        base=f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                try: request(base+"/api");break
                except Exception: await asyncio.sleep(.05)
            else: pytest.fail("uvicorn did not become ready")
            project=request(base+"/api/projects","POST",{"name":"MCP official"})
            from datetime import datetime,timedelta,timezone
            grant=request(base+"/api/agent-port/grants","POST",{"project_id":project["id"],"permission":"write","expires_at":(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),"label":"mcp","agent_identity":"official-sdk"},TOKEN)
            agent_token=grant["token"]
            client_env={**env,"GROWTHMAP_AGENT_TOKEN":agent_token,"GROWTHMAP_AGENT_BASE_URL":base+"/agent/v1"}
            with tempfile.TemporaryFile(mode="w+") as errlog:
                params=StdioServerParameters(command=sys.executable,args=[str(ADAPTER)],env=client_env)
                async with stdio_client(params,errlog=errlog) as (read_stream,write_stream):
                    async with ClientSession(read_stream,write_stream) as session:
                        initialized=await session.initialize()
                        assert initialized.protocolVersion == "2025-11-25"
                        listed=await session.list_tools()
                        assert [t.name for t in listed.tools] == ["capabilities","read_project","read_graph","get_context","propose","apply_batch","report_event","submit_readback"]
                        from agent_port.schemas import Batch,ProposalIn,EventIn,ReadbackIn
                        strict={"propose":ProposalIn,"apply_batch":Batch,"report_event":EventIn,"submit_readback":ReadbackIn}
                        for tool in listed.tools:
                            if tool.name in strict: assert tool.inputSchema == strict[tool.name].model_json_schema()
                            assert tool.inputSchema.get("additionalProperties") is False
                        ok=await session.call_tool("read_project",{})
                        assert not ok.isError and project["id"] in ok.content[0].text
                        rest_error=await session.call_tool("apply_batch",{})
                        assert rest_error.isError and "detail" in rest_error.content[0].text
                        unknown=await session.call_tool("does_not_exist",{})
                        assert unknown.isError and unknown.content[0].text == "Unknown tool"
                        with pytest.raises(McpError): await session.list_prompts()
                errlog.seek(0); stderr=errlog.read()
                assert agent_token not in stderr
            assert server.poll() is None
        finally:
            server.terminate()
            try: server.wait(timeout=5)
            except subprocess.TimeoutExpired: server.kill();server.wait(timeout=5)
            out,err=server.communicate()
            assert agent_token not in out+err

@pytest.mark.parametrize("frame,code",[(b"{broken}\n",-32700),(b"x"*1_048_577+b"\n",-32602),(json.dumps({"jsonrpc":"2.0","id":8,"method":"tools/list","params":[]}).encode()+b"\n",-32602)])
def test_low_level_malformed_oversize_and_invalid_params_recover(frame,code):
    valid=json.dumps({"jsonrpc":"2.0","id":9,"method":"tools/list","params":{}}).encode()+b"\n"
    env={k:v for k,v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    p=subprocess.run([sys.executable,str(ADAPTER)],input=frame+valid,capture_output=True,timeout=10,env=env)
    assert p.returncode == 0 and p.stderr == b""
    lines=p.stdout.splitlines(); assert len(lines)==2
    assert json.loads(lines[0])["error"]["code"]==code
    assert json.loads(lines[1])["id"]==9 and "result" in json.loads(lines[1])
