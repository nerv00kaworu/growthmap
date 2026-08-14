import ctypes,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent));import growthmap_credential as c

def test_payload_bounds_and_target():
 assert c.target(1,"abc")=="GrowthMap/AgentPort/v1/product-1/installation-abc"
 try:c.target(1,"x\0y");assert False
 except ValueError:pass
 raw=c.encode({"schema":"growthmap.agent-credential.v1","endpoint":"http://127.0.0.1:1/agent/v1","token":"gm1.a.secret","instance_nonce":"n","product_major":1});assert b"gm1" in raw

def test_write_zeroes_owned_credential_buffer(monkeypatch):
 class Api:
  def CredWriteW(self,credential,flags):
   assert flags==0
   return True
 monkeypatch.setattr(c,"_api",lambda:Api())
 seen={}
 real_memset=ctypes.memset
 def wipe(address,value,size):
  seen.update(address=address,value=value,size=size)
  return real_memset(address,value,size)
 monkeypatch.setattr(ctypes,"memset",wipe)
 payload={"schema":"growthmap.agent-credential.v1","endpoint":"http://127.0.0.1:1/agent/v1","token":"gm1.a.secret","instance_nonce":"n","product_major":1}
 expected=len(c.encode(payload));c.write("target",payload,"session")
 assert seen["address"]>0 and seen["value"]==0 and seen["size"]==expected
