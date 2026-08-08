import base64,json,sqlite3
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from licensing.authority import LicenseAuthority,activation_challenge,device_identifier
from licensing.gift_service import GiftLicenseService,parse_activation_capability

def authority(tmp_path):
 key=Ed25519PrivateKey.generate();path=tmp_path/'key.pem';path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));return LicenseAuthority(tmp_path/'gift.db',path)
def device():
 key=Ed25519PrivateKey.generate();public=base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode();return key,public
def complete(service,claim,dev):
 challenge=service.challenge(claim,dev[1]);proof=base64.b64encode(dev[0].sign(activation_challenge(challenge['license_id'],dev[1],challenge['nonce']))).decode();return challenge,service.complete(challenge['challenge_id'],proof)
def test_strict_parser_and_secret_never_persists(tmp_path):
 a=authority(tmp_path);s=GiftLicenseService(a);created=s.create();claim=created.pop('claim_key');cap=parse_activation_capability(claim);assert cap.kind=='gift'
 for bad in ['',claim.lower(),claim+'x',' '+claim,'x'*129,None]:
  with pytest.raises(ValueError):parse_activation_capability(bad)
 raw=(tmp_path/'gift.db').read_bytes();assert cap.secret.encode() not in raw;assert cap.secret not in str(s.list())+str(s.get(cap.identity))
 _,cert=complete(s,claim,device());assert cap.secret not in str(cert);assert cap.secret.encode() not in (tmp_path/'gift.db').read_bytes()
def test_rotation_revoke_seats_deactivate_and_reopen(tmp_path):
 a=authority(tmp_path);s=GiftLicenseService(a);created=s.create();old=created['claim_key'];gift=created['gift_id'];d1,d2,d3=device(),device(),device();pending=s.challenge(old,d1[1]);rotated=s.rotate(gift);new=rotated['claim_key']
 for claim in (old,'GMG1.'+gift+'.'+'Z'*32):
  with pytest.raises(ValueError,match='gift_unavailable'):s.challenge(claim,d1[1])
 proof=base64.b64encode(d1[0].sign(activation_challenge(pending['license_id'],d1[1],pending['nonce']))).decode()
 with pytest.raises(ValueError):s.complete(pending['challenge_id'],proof)
 _,c1=complete(s,new,d1);complete(s,new,d2)
 with pytest.raises(ValueError,match='seat_limit'):complete(s,new,d3)
 assert s.deactivate(gift,device_identifier(d1[1]));_,c3=complete(s,new,d3);assert c3['activation_id']!=c1['activation_id']
 s.revoke(gift)
 with pytest.raises(ValueError,match='gift_unavailable'):s.challenge(new,d1[1])
 reopened=LicenseAuthority(tmp_path/'gift.db',tmp_path/'key.pem');assert reopened.get_gift(gift)['status']=='revoked'

def proof_for(challenge,dev):
 return base64.b64encode(dev[0].sign(activation_challenge(challenge['license_id'],dev[1],challenge['nonce']))).decode()

def test_complete_idempotency_stops_after_deactivation_and_flow_is_exact(tmp_path):
 a=authority(tmp_path);s=GiftLicenseService(a);created=s.create();dev=device();challenge=s.challenge(created['claim_key'],dev[1]);proof=proof_for(challenge,dev)
 first=s.complete(challenge['challenge_id'],proof);assert s.complete(challenge['challenge_id'],proof)==first
 assert s.deactivate(created['gift_id'],device_identifier(dev[1]))
 with pytest.raises(ValueError,match='challenge_consumed'):s.complete(challenge['challenge_id'],proof)
 payment=a.create_license();paydev=device();pay=a.issue_activation_challenge(license_id=payment['license_id'],device_public_key=paydev[1]);payproof=proof_for(pay,paydev)
 with pytest.raises(ValueError,match='challenge_unavailable'):a.activate_challenge(challenge_id=pay['challenge_id'],proof=payproof,expected_flow_kind='gift')
 with pytest.raises(ValueError,match='challenge_unavailable'):a.activate_challenge(challenge_id=challenge['challenge_id'],proof=proof,expected_flow_kind='payment')
 assert a.activate_challenge(challenge_id=pay['challenge_id'],proof=payproof,expected_flow_kind='payment')['license_id']==payment['license_id']

def test_consumed_gift_retry_rejects_cross_activation_certificate_tamper(tmp_path):
 a=authority(tmp_path);s=GiftLicenseService(a);created=s.create();first_dev,second_dev=device(),device()
 first_challenge,first_cert=complete(s,created['claim_key'],first_dev)
 _,second_cert=complete(s,created['claim_key'],second_dev)
 assert first_cert['activation_id']!=second_cert['activation_id']
 tampered=dict(first_cert);tampered['activation_id']=second_cert['activation_id']
 with sqlite3.connect(tmp_path/'gift.db') as db:
  db.execute('UPDATE activation_challenges SET certificate_json=? WHERE challenge_id=?',(json.dumps(tampered,separators=(',',':')),first_challenge['challenge_id']))
 with pytest.raises(ValueError,match='^challenge_consumed$'):
  s.complete(first_challenge['challenge_id'],proof_for(first_challenge,first_dev))

def test_consumed_gift_retry_rejects_activation_public_key_tamper(tmp_path):
 a=authority(tmp_path);s=GiftLicenseService(a);created=s.create();first_dev,second_dev=device(),device()
 first_challenge,first_cert=complete(s,created['claim_key'],first_dev)
 _,second_cert=complete(s,created['claim_key'],second_dev)
 assert first_cert['device_public_key']!=second_cert['device_public_key']
 with sqlite3.connect(tmp_path/'gift.db') as db:
  db.execute('UPDATE activations SET device_public_key=? WHERE activation_id=?',(second_cert['device_public_key'],first_cert['activation_id']))
 with pytest.raises(ValueError,match='^challenge_consumed$'):
  s.complete(first_challenge['challenge_id'],proof_for(first_challenge,first_dev))


def test_completed_gift_retry_never_requires_sqlite_json_functions(tmp_path, monkeypatch):
 a=authority(tmp_path);s=GiftLicenseService(a);created=s.create();dev=device();challenge,first=complete(s,created['claim_key'],dev);proof=proof_for(challenge,dev)
 original_connect=a._connect
 def no_json_connect():
  db=original_connect()
  db.create_function('json_extract',-1,lambda *_:(_ for _ in ()).throw(sqlite3.OperationalError('json unavailable')))
  return db
 monkeypatch.setattr(a,'_connect',no_json_connect)
 assert s.complete(challenge['challenge_id'],proof)==first
 assert s.deactivate(created['gift_id'],device_identifier(dev[1]))
 with pytest.raises(ValueError,match='challenge_consumed'):s.complete(challenge['challenge_id'],proof)

def test_major_policy_exact_and_legacy_challenge_fails_closed(tmp_path):
 a=authority(tmp_path)
 for value in (0,2,True,'1'):
  with pytest.raises(ValueError,match='invalid_gift_policy'):a.create_gift(major_version=value)
 created=a.create_gift();dev=device();challenge=a.issue_gift_claim_challenge(gift_id=created['gift_id'],secret=created['claim_key'].rsplit('.',1)[1],device_public_key=dev[1]);proof=proof_for(challenge,dev)
 with sqlite3.connect(tmp_path/'gift.db') as db:db.execute('UPDATE activation_challenges SET flow_kind=NULL WHERE challenge_id=?',(challenge['challenge_id'],))
 with pytest.raises(ValueError,match='challenge_unavailable'):a.activate_challenge(challenge_id=challenge['challenge_id'],proof=proof,expected_flow_kind='gift')
