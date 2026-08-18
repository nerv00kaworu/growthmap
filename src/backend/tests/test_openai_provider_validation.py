import asyncio, json, pytest, httpx
from ai.providers.openai_compatible import OpenAICompatibleProvider
from ai.diagnostics import LLMInvalidResponse
class Response:
 def __init__(self,value): self.value=value; self.status_code=200
 def raise_for_status(self): pass
 def json(self):
  if isinstance(self.value,Exception): raise self.value
  return self.value
class Client:
 value=None
 async def __aenter__(self): return self
 async def __aexit__(self,*a): pass
 async def post(self,*a,**k): return Response(self.value)
@pytest.mark.parametrize('value',[ValueError('bad'),[],1,{}, {'choices':[]},{'choices':[{}]},{'choices':[{'message':{}}]},{'choices':[{'message':{'content':7}}]},{'content':''}])
def test_invalid_shapes_are_dedicated(monkeypatch,value):
 Client.value=value; monkeypatch.setattr(httpx,'AsyncClient',lambda **k:Client())
 with pytest.raises(LLMInvalidResponse): asyncio.run(OpenAICompatibleProvider(api_key='x').complete('s','u'))
def test_valid_shape(monkeypatch):
 Client.value={'choices':[{'message':{'content':'ok'}}]};monkeypatch.setattr(httpx,'AsyncClient',lambda **k:Client())
 assert asyncio.run(OpenAICompatibleProvider(api_key='x').complete('s','u'))=='ok'
