import pytest
from fastapi.testclient import TestClient
from .test_gift_license_service import authority,device
from licensing.gift_api import create_candidate_app
class Verifier:
 def __init__(self,explode=False):self.explode=explode
 def verify(self,token):
  if self.explode:raise RuntimeError('secret detail')
  return token=='ok'
def headers():return {'Authorization':'Bearer ok','Origin':'https://admin.test','X-CSRF-Token':'csrf'}
def test_admin_boundary_public_generic_and_headers(tmp_path):
 a=authority(tmp_path);client=TestClient(create_candidate_app(authority=a,session_verifier=Verifier(),allowed_admin_origin='https://admin.test',csrf_secret='csrf',rate_limit=10));d=device()
 for h in ({},{'Authorization':'Bearer wrong','Origin':'https://admin.test','X-CSRF-Token':'csrf'},{'Authorization':'Bearer ok','Origin':'https://evil.test','X-CSRF-Token':'csrf'}):assert client.get('/v1/admin/gifts',headers=h).status_code==403
 create=client.post('/v1/admin/gifts',headers=headers(),json={});assert create.status_code==201;claim=create.json()['claim_key'];gift=create.json()['gift_id']
 listed=client.get('/v1/admin/gifts',headers=headers());assert 'claim_key' not in listed.text and claim not in listed.text
 for key in ('GMG1.'+gift+'.'+'X'*32,claim+'x'):
  result=client.post('/v1/gifts/claim/challenge',json={'claim_key':key,'device_public_key':d[1]});assert result.status_code==404 and result.json()=={'detail':'gift unavailable'}
 assert create.headers['cache-control']=='no-store' and create.headers['pragma']=='no-cache' and create.headers['referrer-policy']=='no-referrer'
 assert client.post('/v1/admin/gifts',headers=headers(),content=b'x'*8193).status_code==400
def test_verifier_exception_oversized_bearer_and_rate_limit(tmp_path):
 a=authority(tmp_path);bad=TestClient(create_candidate_app(authority=a,session_verifier=Verifier(True),allowed_admin_origin='https://admin.test',csrf_secret='csrf'));assert bad.get('/v1/admin/gifts',headers=headers()).status_code==403
 c=TestClient(create_candidate_app(authority=a,session_verifier=Verifier(),allowed_admin_origin='https://admin.test',csrf_secret='csrf',rate_limit=1));assert c.get('/v1/admin/gifts',headers={'Authorization':'Bearer '+'x'*5000,'Origin':'https://admin.test','X-CSRF-Token':'csrf'}).status_code==403;assert c.get('/v1/admin/gifts',headers=headers()).status_code==200;assert c.get('/v1/admin/gifts',headers=headers()).status_code==429

import base64,sqlite3
from licensing.authority import activation_challenge
from starlette.datastructures import Headers

def raw_admin(client,headers_list,path='/v1/admin/gifts'):
 return client.get(path,headers=Headers(raw=[(k.encode(),v.encode()) for k,v in headers_list]))

def test_raw_duplicate_security_headers_and_canonical_authorization(tmp_path):
 a=authority(tmp_path);client=TestClient(create_candidate_app(authority=a,session_verifier=Verifier(),allowed_admin_origin='https://admin.test',csrf_secret='csrf',rate_limit=50))
 base=[('authorization','Bearer ok'),('origin','https://admin.test'),('x-csrf-token','csrf')]
 assert raw_admin(client,base).status_code==200
 for name,value in [('authorization','Bearer wrong'),('origin','https://evil.test'),('x-csrf-token','wrong')]:
  for duplicate in (base+[(name,value)],[(name,value)]+base):assert raw_admin(client,duplicate).status_code==403
 for auth in ['Bearer  ok','bearer ok','Bearer ok,wrong',' Bearer ok','Bearer ok ','Basic ok','Bearer ok\r\nx: y']:
  assert raw_admin(client,[('authorization',auth),*base[1:]]).status_code==403

def test_origin_policy_header_bounds_limiter_capacity_and_injected_peer(tmp_path):
 a=authority(tmp_path)
 for origin in ['http://admin.test','https://','https://user@admin.test','https://admin.test/','https://admin.test/path','https://admin.test?q=1','https://admin.test#x','https://127.0.0.1','https://ADMIN.test','https://admin.test:443','https://admin.test.']:
  with pytest.raises(RuntimeError):create_candidate_app(authority=a,session_verifier=Verifier(),allowed_admin_origin=origin,csrf_secret='csrf')
 app=create_candidate_app(authority=a,session_verifier=Verifier(),allowed_admin_origin='https://admin.test',csrf_secret='csrf',rate_limit=5,limiter_capacity=2,client_identity_resolver=lambda request:request.scope.get('peer','fixed'))
 client=TestClient(app);assert client.get('/v1/admin/gifts',headers=headers()).status_code==200
 for key in ('a','b','c'):app.state.gift_limiter.check('probe',key)
 assert len(app.state.gift_limiter.rows)<=2
 too_many=[('x-'+str(i),'v') for i in range(65)];assert raw_admin(client,too_many).status_code==400
 assert raw_admin(client,[('authorization','Bearer '+'x'*4097),*[(k.lower(),v) for k,v in list(headers().items())[1:]]]).status_code==403

def test_api_major_types_and_cross_protocol_complete(tmp_path):
 a=authority(tmp_path);client=TestClient(create_candidate_app(authority=a,session_verifier=Verifier(),allowed_admin_origin='https://admin.test',csrf_secret='csrf',rate_limit=50));dev=device()
 for value in (0,2,True,'1'):assert client.post('/v1/admin/gifts',headers=headers(),json={'major_version':value}).status_code in (400,422)
 gift=client.post('/v1/admin/gifts',headers=headers(),json={}).json();gc=client.post('/v1/gifts/claim/challenge',json={'claim_key':gift['claim_key'],'device_public_key':dev[1]}).json()['challenge'];gp=base64.b64encode(dev[0].sign(activation_challenge(gc['license_id'],dev[1],gc['nonce']))).decode()
 payment=a.create_license();pd=device();pc=a.issue_activation_challenge(license_id=payment['license_id'],device_public_key=pd[1]);pp=base64.b64encode(pd[0].sign(activation_challenge(pc['license_id'],pd[1],pc['nonce']))).decode()
 assert client.post('/v1/gifts/claim/complete',json={'challenge_id':pc['challenge_id'],'proof':pp}).status_code==404
 with pytest.raises(ValueError,match='challenge_unavailable'):a.activate_challenge(challenge_id=gc['challenge_id'],proof=gp,expected_flow_kind='payment')

def test_gift_complete_signer_failure_is_generic_and_rolls_back(tmp_path):
 a=authority(tmp_path);created=a.create_gift();dev=device();client=TestClient(create_candidate_app(authority=a,session_verifier=Verifier(),allowed_admin_origin='https://admin.test',csrf_secret='csrf',rate_limit=50));challenge=client.post('/v1/gifts/claim/challenge',json={'claim_key':created['claim_key'],'device_public_key':dev[1]}).json()['challenge'];proof=base64.b64encode(dev[0].sign(activation_challenge(challenge['license_id'],dev[1],challenge['nonce']))).decode()
 class FailingSigner:
  def sign(self,_):raise RuntimeError('SECRET_SIGNER_DETAIL')
 a.signer=FailingSigner();result=client.post('/v1/gifts/claim/complete',json={'challenge_id':challenge['challenge_id'],'proof':proof});assert result.status_code==404 and result.json()=={'detail':'gift unavailable'} and 'SECRET' not in result.text
 with sqlite3.connect(tmp_path/'gift.db') as db:
  assert db.execute('select count(*) from activations').fetchone()[0]==0
  assert db.execute('select count(*) from activation_requests').fetchone()[0]==0
  row=db.execute('select consumed_at,certificate_json from activation_challenges where challenge_id=?',(challenge['challenge_id'],)).fetchone();assert row==(None,None)
