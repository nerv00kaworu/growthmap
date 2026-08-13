"""Gift claim capability parsing and Authority orchestration; no HTTP or secret persistence."""
from __future__ import annotations
import re
from dataclasses import dataclass

_GIFT=re.compile(r"GMG1\.([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.([A-Za-z0-9_-]{32})")
_PAYMENT=re.compile(r"GM1\.([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.([A-Za-z0-9_-]{32})")
@dataclass(frozen=True)
class ActivationCapability:
 kind:str
 identity:str
 secret:str

def parse_activation_capability(value:str)->ActivationCapability:
 if type(value) is not str or len(value)>128 or value!=value.strip():raise ValueError("activation_key_invalid")
 match=_PAYMENT.fullmatch(value)
 if match:return ActivationCapability("payment",match[1],match[2])
 match=_GIFT.fullmatch(value)
 if match:return ActivationCapability("gift",match[1],match[2])
 raise ValueError("activation_key_invalid")

class GiftLicenseService:
 def __init__(self,authority):self.authority=authority
 def create(self,**policy):return self.authority.create_gift(**policy)
 def list(self):return self.authority.list_gifts()
 def get(self,gift_id):return self.authority.get_gift(gift_id)
 def rotate(self,gift_id):return self.authority.recover_gift(gift_id)
 def revoke(self,gift_id):return self.authority.revoke_gift(gift_id)
 def devices(self,gift_id):return self.authority.list_gift_devices(gift_id)
 def deactivate(self,gift_id,device_id):return self.authority.deactivate_gift_device(gift_id,device_id)
 def challenge(self,claim_key,device_public_key):
  cap=parse_activation_capability(claim_key)
  if cap.kind!="gift":raise ValueError("gift_unavailable")
  return self.authority.issue_gift_claim_challenge(gift_id=cap.identity,secret=cap.secret,device_public_key=device_public_key)
 def complete(self,challenge_id,proof):return self.authority.activate_challenge(challenge_id=challenge_id,proof=proof,expected_flow_kind="gift")
 def refresh_challenge(self,activation_id,license_id,device_public_key):
  return self.authority.issue_gift_refresh_challenge(activation_id=activation_id,license_id=license_id,device_public_key=device_public_key)
 def refresh_complete(self,challenge_id,proof):return self.authority.complete_activation_refresh(challenge_id=challenge_id,proof=proof,expected_flow_kind="gift")
