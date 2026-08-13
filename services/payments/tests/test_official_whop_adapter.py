import json,sys
import pytest
from growthmap_payments.whop import OfficialWhopVerifier,WhopIngressError,parse_verified_event

HEADERS={"webhook-id":"msg_1","webhook-timestamp":"1720000000","webhook-signature":"v1,signed"}
def envelope(**data_changes):
 data={"id":"pay_1","status":"succeeded","currency":"usd","total":49,"metadata":{"order_id":"order_1"},"product":{"id":"prod_growthmap","title":"GrowthMap"},"plan":{"id":"plan_lifetime"},"checkout_configuration_id":"ch_growthmap"}
 data.update(data_changes)
 return json.dumps({"id":"msg_1","api_version":"v1","type":"payment.succeeded","timestamp":"2026-08-12T08:00:00.000Z","company_id":"biz_growthmap","data":data},separators=(",",":"))

class Hooks:
 def __init__(self,owner):self.owner=owner
 def unwrap(self,body,headers):
  self.owner.calls.append((body,headers))
  if self.owner.fail:raise RuntimeError("signature details must not escape")
  return object()
class SDK:
 def __init__(self,**kwargs):self.kwargs=kwargs;self.calls=[];self.fail=False;self.webhooks=Hooks(self)

def verifier(sdk=None,**changes):
 sdk=sdk or SDK()
 config={"api_key":"server-api-key","webhook_secret":"server-webhook-secret","company_id":"biz_growthmap","expected_currency":"usd","expected_total":"49.00","product_id":"prod_growthmap","plan_id":"plan_lifetime","checkout_configuration_id":"ch_growthmap","sdk_factory":lambda **kwargs:(setattr(sdk,"kwargs",kwargs) or sdk)}
 config.update(changes);return OfficialWhopVerifier(**config),sdk

def test_verifies_unchanged_raw_body_then_normalizes_exact_official_envelope():
 adapter,sdk=verifier();raw=(envelope()+"\n").encode()
 result=parse_verified_event(adapter.verify(raw,HEADERS))
 assert sdk.calls==[(raw.decode(),HEADERS)]
 assert sdk.kwargs["api_key"]=="server-api-key" and sdk.kwargs["webhook_key"]=="c2VydmVyLXdlYmhvb2stc2VjcmV0"
 assert result.event_id=="msg_1" and result.kind=="paid" and result.order_id=="order_1"
 assert result.provider_order_ref=="ch_growthmap" and result.provider_payment_ref=="pay_1"
 assert result.occurred_at=="2026-08-12T08:00:00+00:00"

@pytest.mark.parametrize(("change","value"),[
 ("status","paid"),("status","failed"),("currency","eur"),("total",48),("metadata",{"order_id":"wrong order"}),
 ("product",{"id":"prod_wrong"}),("plan",{"id":"plan_wrong"}),("checkout_configuration_id","ch_wrong")])
def test_rejects_bad_semantic_bindings_after_sdk_verification(change,value):
 adapter,sdk=verifier()
 with pytest.raises(WhopIngressError):adapter.verify(envelope(**{change:value}).encode(),HEADERS)
 assert len(sdk.calls)==1

def test_rejects_company_event_type_duplicate_case_and_header_issues():
 adapter,_=verifier()
 bad_company=envelope().replace('"biz_growthmap"','"biz_other"')
 duplicate=envelope().replace('"company_id":"biz_growthmap"','"company_id":"biz_growthmap","COMPANY_ID":"biz_growthmap"')
 reversal=envelope().replace('"payment.succeeded"','"refund.created"')
 for raw in (bad_company,duplicate,reversal):
  with pytest.raises(WhopIngressError):adapter.verify(raw.encode(),HEADERS)
 with pytest.raises(WhopIngressError):adapter.verify(envelope().encode(),{**HEADERS,"whop-extra":"x"})
 with pytest.raises(WhopIngressError):adapter.verify(envelope().encode(),{"webhook-signature":"x"})

def test_sdk_exception_is_generic_and_fails_before_normalization():
 adapter,sdk=verifier();sdk.fail=True
 with pytest.raises(WhopIngressError,match="invalid webhook") as caught:adapter.verify(b"not json",HEADERS)
 assert caught.value.__cause__ is None and len(sdk.calls)==1

def test_missing_dependency_and_configuration_fail_closed(monkeypatch):
 with pytest.raises(WhopIngressError,match="configuration unavailable"):verifier(product_id=None,plan_id=None,checkout_configuration_id=None)
 adapter,_=verifier();adapter._sdk_factory=None
 monkeypatch.setattr("growthmap_payments.whop.importlib.import_module",lambda name:(_ for _ in ()).throw(ImportError()))
 with pytest.raises(WhopIngressError,match="verifier unavailable"):adapter.verify(envelope().encode(),HEADERS)

def test_duplicate_nested_metadata_case_rejected():
 adapter,_=verifier();raw=envelope().replace('"order_id":"order_1"','"order_id":"order_1","ORDER_ID":"order_1"')
 with pytest.raises(WhopIngressError):adapter.verify(raw.encode(),HEADERS)
