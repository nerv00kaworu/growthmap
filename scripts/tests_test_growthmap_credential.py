import ctypes,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent));import growthmap_credential as c

def test_payload_bounds_and_target():
 assert c.target(1,"abc")=="GrowthMap/AgentPort/v1/product-1/installation-abc"
 try:c.target(1,"x\0y");assert False
 except ValueError:pass
 raw=c.encode({"schema":"growthmap.agent-credential.v1","endpoint":"http://127.0.0.1:1/agent/v1","token":"gm1.a.secret","instance_nonce":"n","product_major":1});assert b"gm1" in raw
