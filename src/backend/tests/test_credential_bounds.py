from desktop.routes import SecretIn, HydrateSecretIn
from models.schemas import ProviderSecretRecovery
from pydantic import ValidationError
from fastapi.exceptions import RequestValidationError
from main import credential_request_validation
from starlette.requests import Request
import json
import pytest

MODELS=(SecretIn,HydrateSecretIn)
# Exact UTF-8 byte edges while remaining below the independent 16,384-char cap.
UTF8={
 32767: "密"*10922+"a",
 32768: "密"*10922+"ab",
 32769: "密"*10923,
}
ASCII={32767:"a"*32767,32768:"a"*32768,32769:"a"*32769}
VALID=["a"*16383,"a"*16384,UTF8[32767],UTF8[32768]]
INVALID=["","x\0y","x"*16385,UTF8[32769],*ASCII.values()]

def assert_redacted(caught,value):
 text=str(caught.value)
 assert "INVALID_PROVIDER_CREDENTIAL" in text
 assert value[:12] not in text if len(value)>=12 else True

@pytest.mark.parametrize("model",MODELS)
@pytest.mark.parametrize("value",VALID)
def test_set_and_hydrate_accept_boundaries(model,value): model(api_key=value)
@pytest.mark.parametrize("model",MODELS)
@pytest.mark.parametrize("value",INVALID)
def test_set_and_hydrate_reject_redacted(model,value):
 with pytest.raises(ValidationError) as caught:model(api_key=value)
 assert_redacted(caught,value)
@pytest.mark.parametrize("value",VALID)
def test_recovery_accepts_boundaries(value):ProviderSecretRecovery(revision=1,operation="set",api_key=value)
@pytest.mark.parametrize("value",INVALID)
def test_recovery_rejects_redacted(value):
 with pytest.raises(ValidationError) as caught:ProviderSecretRecovery(revision=1,operation="set",api_key=value)
 assert_redacted(caught,value)
def test_recovery_delete_forbids_secret():
 with pytest.raises(ValidationError):ProviderSecretRecovery(revision=1,operation="delete",api_key="unique-secret")

@pytest.mark.asyncio
async def test_credential_route_422_is_stable_typed_and_non_echoing():
 secret="route-secret-prefix-unique"
 request=Request({"type":"http","method":"PUT","path":"/api/desktop/secrets/p","query_string":b"","headers":[]})
 error=RequestValidationError([{"type":"value_error","loc":("body","api_key"),"msg":"invalid","input":secret,"ctx":{"error":ValueError("invalid")}}])
 response=await credential_request_validation(request,error)
 assert response.status_code==422
 assert json.loads(response.body)=={"detail":{"code":"INVALID_PROVIDER_CREDENTIAL","message":"Provider credential is invalid"}}
 assert secret.encode() not in response.body

@pytest.mark.asyncio
async def test_non_secret_route_retains_fastapi_validation_detail_contract():
 request=Request({"type":"http","method":"POST","path":"/api/projects","query_string":b"","headers":[]})
 error=RequestValidationError([{"type":"missing","loc":("body","name"),"msg":"Field required","input":{}}])
 response=await credential_request_validation(request,error)
 body=json.loads(response.body)
 assert response.status_code==422
 assert isinstance(body["detail"],list)
 assert body["detail"][0]["loc"]==["body","name"]
