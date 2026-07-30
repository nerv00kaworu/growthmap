import json,os,subprocess,sys,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
from urllib.parse import parse_qs,urlsplit
from pathlib import Path
ROOT=Path(__file__).parents[3]
class H(BaseHTTPRequestHandler):
 seen=[]
 def do_GET(self):
  self.seen.append(("GET",self.path,self.headers.get("Authorization")));self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.end_headers()
  parsed=urlsplit(self.path);objective=parse_qs(parsed.query,keep_blank_values=True).get("objective",[""])[0]
  payload={"objective":objective} if "/context/" in parsed.path else {"protocol":"growthmap-agent-port"}
  self.wfile.write(json.dumps(payload,ensure_ascii=False).encode("utf-8"))
 def do_POST(self):body=self.rfile.read(int(self.headers.get("content-length",0)));self.seen.append(("POST",self.path,self.headers.get("Authorization"),body));self.send_response(200);self.end_headers();self.wfile.write(b'{"ok":true}')
 def log_message(self,*a):pass
class Clients(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.s=HTTPServer(("127.0.0.1",0),H);threading.Thread(target=cls.s.serve_forever,daemon=True).start();cls.env={**os.environ,"GROWTHMAP_AGENT_BASE_URL":f"http://127.0.0.1:{cls.s.server_port}","GROWTHMAP_AGENT_TOKEN":"secret","PYTHONIOENCODING":"cp1252"}
 @classmethod
 def tearDownClass(cls):cls.s.shutdown()
 def test_cli_and_mcp_are_rest_thin_clients(self):
  cli=subprocess.run([sys.executable,str(ROOT/"scripts/growthmap_agent.py"),"capabilities"],env=self.env,text=True,capture_output=True);self.assertEqual(cli.returncode,0,cli.stderr);self.assertEqual(H.seen[-1][:2],("GET","/capabilities"))
  objective="發布 空格 & 驗證";cli=subprocess.run([sys.executable,str(ROOT/"scripts/growthmap_agent.py"),"context","--target","11111111-1111-4111-8111-111111111111","--objective",objective],env=self.env,capture_output=True);self.assertEqual(cli.returncode,0,cli.stderr.decode("utf-8","replace"));self.assertEqual(parse_qs(urlsplit(H.seen[-1][1]).query)["objective"],[objective]);self.assertEqual(json.loads(cli.stdout.decode("utf-8"))["objective"],objective);too_long=subprocess.run([sys.executable,str(ROOT/"scripts/growthmap_agent.py"),"context","--target","11111111-1111-4111-8111-111111111111","--objective","x"*2001],env=self.env,capture_output=True);self.assertEqual(too_long.returncode,2)
  requests='\n'.join(json.dumps(x,ensure_ascii=False) for x in [{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}},{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"read_project","arguments":{}}},{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_context","arguments":{"target_id":"11111111-1111-4111-8111-111111111111","objective":objective}}}])+"\n";mcp=subprocess.run([sys.executable,str(ROOT/"scripts/growthmap_mcp.py")],env=self.env,input=requests.encode("utf-8"),capture_output=True);self.assertEqual(mcp.returncode,0,mcp.stderr.decode("utf-8","replace"));self.assertEqual(parse_qs(urlsplit(H.seen[-1][1]).query)["objective"],[objective]);decoded=mcp.stdout.decode("utf-8");self.assertIn("發布",decoded);self.assertNotIn("secret",decoded)
