import json,os,subprocess,sys,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
ROOT=Path(__file__).parents[3]
class H(BaseHTTPRequestHandler):
 seen=[]
 def do_GET(self):self.seen.append(("GET",self.path,self.headers.get("Authorization")));self.send_response(200);self.end_headers();self.wfile.write(b'{"protocol":"growthmap-agent-port"}')
 def do_POST(self):body=self.rfile.read(int(self.headers.get("content-length",0)));self.seen.append(("POST",self.path,self.headers.get("Authorization"),body));self.send_response(200);self.end_headers();self.wfile.write(b'{"ok":true}')
 def log_message(self,*a):pass
class Clients(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.s=HTTPServer(("127.0.0.1",0),H);threading.Thread(target=cls.s.serve_forever,daemon=True).start();cls.env={**os.environ,"GROWTHMAP_AGENT_BASE_URL":f"http://127.0.0.1:{cls.s.server_port}","GROWTHMAP_AGENT_TOKEN":"secret"}
 @classmethod
 def tearDownClass(cls):cls.s.shutdown()
 def test_cli_and_mcp_are_rest_thin_clients(self):
  cli=subprocess.run([sys.executable,str(ROOT/"scripts/growthmap_agent.py"),"capabilities"],env=self.env,text=True,capture_output=True);self.assertEqual(cli.returncode,0,cli.stderr);self.assertEqual(H.seen[-1][:2],("GET","/capabilities"))
  requests='\n'.join(json.dumps(x) for x in [{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}},{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"read_project","arguments":{}}}])+"\n";mcp=subprocess.run([sys.executable,str(ROOT/"scripts/growthmap_mcp.py")],env=self.env,input=requests,text=True,capture_output=True);self.assertEqual(mcp.returncode,0,mcp.stderr);self.assertEqual(H.seen[-1][:2],("GET","/project"));self.assertNotIn("secret",mcp.stdout)
