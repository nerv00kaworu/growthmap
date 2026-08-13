import asyncio,base64,hashlib,json,os,threading,time
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from licensing.authority_api import PeerDescriptor,ServiceAuthRequest,ServiceIdentity
import licensing.authority_composition as composition
from licensing.authority_composition import (AuthenticatedEdgeAdapter,Ed25519ServiceIdentityVerifier,
 SQLiteRequestJournal,StrictASGIGuard,validate_composition_descriptor,run)


def replay_files(tmp_path):
 root=tmp_path/'replay';root.mkdir(0o700);root.chmod(0o700)
 db=root/'request-journal.sqlite3';db.touch(0o600);db.chmod(0o600)
 lock=root/'.request-journal.lock';lock.touch(0o600);lock.chmod(0o600)
 return db

def request(nonce='abcdefghijklmnop',body='1'*64,source='trusted-edge',timestamp='2026-08-08T12:00:00Z',path='/v1/service/entitlements'):
 return ServiceAuthRequest('POST',path,body,timestamp,nonce,
  'growthmap-authority','authority-test',b'',PeerDescriptor('payments-edge',source))

def journal(path):return SQLiteRequestJournal(path,os.getuid(),max_entries=100,retention_seconds=3600,lease_seconds=1)

@pytest.mark.parametrize('provider',[
 'AuthenticatedEdgeAdapter','Ed25519ServiceIdentityVerifier','SQLiteRequestJournal',
 'StrictASGIGuard','create_authority_app','build_production_authority'])
@pytest.mark.parametrize('replacement_kind',['missing','object','noncallable','subclass','wrong','fixture','process_local','duck'])
def test_exact_provider_gate_has_zero_pre_argv_side_effects(monkeypatch,tmp_path,provider,replacement_kind):
 original=getattr(composition,provider)
 class Wrong:
  production_safe=True;fixture=False;process_local=False
  def __call__(self,*a,**k):pass
 class Sub(original if isinstance(original,type) else Wrong):pass
 replacements={'missing':None,'object':object(),'noncallable':Wrong,
  'subclass':Sub,'wrong':Wrong,'fixture':Wrong(),'process_local':Wrong(),'duck':Wrong()}
 replacement=replacements[replacement_kind]
 if replacement_kind=='noncallable':replacement=type('NonCallable',(),{'production_safe':True,'fixture':False,'process_local':False})()
 if replacement_kind=='fixture':replacement.fixture=True
 if replacement_kind=='process_local':replacement.process_local=True
 monkeypatch.setattr(composition,provider,replacement)
 events=[]
 monkeypatch.setattr(composition.argparse,'ArgumentParser',lambda *a,**k:events.append('argparse'))
 monkeypatch.setattr(composition,'load_composition_config',lambda *a:events.append('config'))
 monkeypatch.setattr(composition.sqlite3,'connect',lambda *a,**k:events.append('sqlite'))
 monkeypatch.setattr(composition,'_read_fixed',lambda *a,**k:events.append('key'))
 monkeypatch.setattr(composition,'_load_edge_provider',lambda *a:events.append('edge'))
 monkeypatch.setattr(composition,'compose',lambda *a:events.append('compose'))
 with pytest.raises(RuntimeError,match='providers_not_configured'):composition.run(['--fixed-config',str(tmp_path/'artifact')])
 assert events==[] and not list(tmp_path.iterdir())


def test_cli_main_and_run_use_exact_gate_before_argv(monkeypatch):
 monkeypatch.setattr(composition,'SQLiteRequestJournal',object())
 with pytest.raises(RuntimeError,match='providers_not_configured'):composition.cli_main()
 with pytest.raises(RuntimeError,match='providers_not_configured'):composition.run([])

def test_descriptor_unknown_alias_types_and_bindings_rejected():
 cfg={'schema_version':1,'expected_uid':123,'deployment_config_sha256':'2'*64,
  'authority_config_path':'/etc/growthmap-authority/authority-production.json',
  'edge':{'provider':'ed25519-fixed-v1','identity':'payments-edge','source':'trusted-edge','subject':'payments','audience':'growthmap-authority','public_key_path':'/etc/growthmap-authority/edge-public.pem','public_key_sha256':'3'*64},
  'replay':{'provider':'sqlite-journal-v1','path':'/var/lib/growthmap-authority/request-journal.sqlite3','expected_uid':123,'max_entries':100,'retention_seconds':3600,'lease_seconds':2},
  'listen':{'host':'127.0.0.1','port':8443}}
 assert validate_composition_descriptor(cfg)==cfg
 for mutate in (lambda c:c.update(extra=1),lambda c:c['listen'].update(host='0.0.0.0'),lambda c:c['replay'].update(path='/var/lib/growthmap-authority/../growthmap-authority/request-journal.sqlite3'),lambda c:c['edge'].update(identity='bad\nidentity')):
  bad=json.loads(json.dumps(cfg));mutate(bad)
  with pytest.raises(RuntimeError):validate_composition_descriptor(bad)

def test_authenticated_edge_signature_binds_all_provenance_and_forged_headers_irrelevant():
 key=Ed25519PrivateKey.generate();verifier=Ed25519ServiceIdentityVerifier(key.public_key(),identity='payments-edge',source='trusted-edge',subject='payments',audience='growthmap-authority')
 original=request();sig=key.sign(verifier.signed_bytes(original));signed=ServiceAuthRequest(*original.__dict__.values())
 signed=ServiceAuthRequest(signed.method,signed.path,signed.body_sha256,signed.timestamp,signed.nonce,signed.audience,signed.authority_id,base64.b64encode(sig),signed.peer)
 assert verifier.verify(signed)==ServiceIdentity('payments','growthmap-authority','authority-test')
 mutations=[{'method':'PUT'},{'path':'/v1/service/revocations'},{'body_sha256':'2'*64},{'timestamp':'2026-08-08T12:00:01Z'},{'nonce':'qrstuvwxyzABCDEF'},{'authority_id':'other-authority'},{'peer':PeerDescriptor('payments-edge','forged')}]
 for change in mutations:
  values=signed.__dict__|change
  assert verifier.verify(ServiceAuthRequest(**values)) is None
 class Request: scope={'client':('127.0.0.1',1),'headers':[(b'x-peer-identity',b'forged')]}
 assert AuthenticatedEdgeAdapter('payments-edge','trusted-edge').resolve(Request())==PeerDescriptor('payments-edge','trusted-edge')

@pytest.mark.parametrize('service_path',[
 '/v1/service/entitlements','/v1/service/entitlements/read',
 '/v1/service/revocations','/v1/service/revocations/read'])
def test_every_exposed_service_route_journal_restart_response_loss_readback_and_conflict(tmp_path,service_path):
 path=replay_files(tmp_path);identity=ServiceIdentity('payments','growthmap-authority','authority-test');calls=[]
 req=request(path=service_path)
 first=journal(path);assert first.execute(req,identity,lambda:calls.append(1) or {'path':service_path,'ok':1})=={'path':service_path,'ok':1};first.close()
 second=journal(path);assert second.execute(req,identity,lambda:calls.append(2) or {'ok':2})=={'path':service_path,'ok':1}
 with pytest.raises(RuntimeError,match='binding_conflict'):second.execute(request(body='2'*64,path=service_path),identity,lambda:{'bad':1})
 assert calls==[1];second.close()

def test_journal_pending_recovery_after_response_loss_and_concurrency(tmp_path):
 path=replay_files(tmp_path);identity=ServiceIdentity('payments','growthmap-authority','authority-test');j=journal(path);calls=[]
 # Inject a recoverable PENDING row as if Authority committed and journal response commit was lost.
 req=request();binding=j.binding(req,identity.subject);key=hashlib.sha256((identity.subject+'\0'+req.nonce).encode()).hexdigest();db=j._connect();db.execute("insert into request_journal values(?,?,'PENDING',0,NULL,?,NULL)",(key,binding,int(time.time())-2));db.close()
 result=j.execute(req,identity,lambda:calls.append(1) or {'readback':'deterministic'})
 assert result=={'readback':'deterministic'} and calls==[1]
 outputs=[]
 def worker():outputs.append(j.execute(request(nonce='qrstuvwxyzABCDEF'),identity,lambda:(time.sleep(.05),{'ok':2})[1]))
 threads=[threading.Thread(target=worker) for _ in range(2)]
 for t in threads:t.start()
 for t in threads:t.join()
 assert outputs==[{'ok':2},{'ok':2}];j.close()

def test_journal_identity_replacement_and_corruption_fail_closed(tmp_path):
 path=replay_files(tmp_path);j=journal(path);replacement=path.parent/'replacement';replacement.touch(0o600);replacement.chmod(0o600);os.replace(replacement,path)
 with pytest.raises(RuntimeError,match='identity_changed'):j.execute(request(),ServiceIdentity('payments','growthmap-authority','authority-test'),lambda:{})
 j.close()

def guarded_call(headers,frames):
 async def inner(scope,receive,send):
  while True:
   msg=await receive()
   if not msg.get('more_body'):break
  await send({'type':'http.response.start','status':200,'headers':[]});await send({'type':'http.response.body','body':b'ok'})
 app=StrictASGIGuard(inner);messages=[]
 async def receive():return frames.pop(0) if frames else {'type':'http.disconnect'}
 async def send(msg):messages.append(msg)
 scope={'type':'http','headers':headers,'client':('127.0.0.1',1)}
 asyncio.run(app(scope,receive,send));return next(m['status'] for m in messages if m['type']=='http.response.start')

@pytest.mark.parametrize('headers,frames,status',[
 ([(b'content-length',b'2'),(b'content-length',b'2')],[{'type':'http.request','body':b'{}','more_body':False}],400),
 ([(b'content-length',b'2'),(b'transfer-encoding',b'chunked')],[{'type':'http.request','body':b'{}','more_body':False}],400),
 ([(b'content-length',b'2')],[{'type':'http.request','body':b'{','more_body':False}],400),
 ([(b'content-length',b'2')],[{'type':'http.request','body':b'{','more_body':True},{'type':'http.disconnect'}],400),
 ([(b'content-length',b'2')],[{'type':'http.request','body':b'{}','more_body':False}],200),
])
def test_asgi_guard_adversarial_framing(headers,frames,status):assert guarded_call(headers,frames)==status

def _edge_cfg(tmp_path, raw):
 p=tmp_path/'edge-public.pem'
 if p.exists(): p.chmod(0o600)
 p.write_bytes(raw);p.chmod(0o400)
 return {'expected_uid':os.getuid(),'edge':{'identity':'payments-edge','source':'trusted-edge','subject':'payments','audience':'growthmap-authority','public_key_path':str(p),'public_key_sha256':hashlib.sha256(raw).hexdigest()}}

def test_ed25519_backend_concrete_class_is_accepted_without_exact_type(tmp_path):
 from cryptography.hazmat.primitives import serialization
 key=Ed25519PrivateKey.generate().public_key()
 raw=key.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
 assert type(key) is not composition.Ed25519PublicKey
 verifier,_=composition._load_edge_provider(_edge_cfg(tmp_path,raw))
 assert isinstance(verifier.key,composition.Ed25519PublicKey)

def test_ed25519_loader_is_import_sealed_and_non_ed25519_substitutes_rejected(monkeypatch,tmp_path):
 from cryptography.hazmat.primitives import serialization
 from cryptography.hazmat.primitives.asymmetric import rsa,ec,x25519
 good=Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
 monkeypatch.setattr(composition.serialization,'load_pem_public_key',lambda raw:Ed25519PrivateKey.generate().public_key())
 # Public Python serialization registry is deliberately outside the native construction path.
 verifier,_=composition._load_edge_provider(_edge_cfg(tmp_path,good));assert type(verifier.key) is composition._NATIVE_ED25519_TYPE
 monkeypatch.undo()
 for key in (rsa.generate_private_key(public_exponent=65537,key_size=2048).public_key(),ec.generate_private_key(ec.SECP256R1()).public_key(),x25519.X25519PrivateKey.generate().public_key()):
  raw=key.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
  with pytest.raises(RuntimeError,match='invalid'):composition._load_edge_provider(_edge_cfg(tmp_path,raw))

@pytest.mark.parametrize('suffix',[b'\n',b'garbage',b'-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n'])
def test_ed25519_rejects_noncanonical_trailing_or_multiple_material(tmp_path,suffix):
 from cryptography.hazmat.primitives import serialization
 key=Ed25519PrivateKey.generate().public_key();raw=key.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)+suffix
 with pytest.raises(RuntimeError,match='invalid'):composition._load_edge_provider(_edge_cfg(tmp_path,raw))

def test_uid_contract_rejects_omitted_alias_mismatch_before_compose_effect(monkeypatch):
 events=[];monkeypatch.setattr(composition,'compose',lambda *a,**k:events.append((a,k)))
 invalid=([],['--fixed-config','/etc/growthmap-authority/production-composition.json'],
  ['--fixed-config=/etc/growthmap-authority/production-composition.json','--expected-service-uid','123'],
  ['--fix','/etc/growthmap-authority/production-composition.json','--expected-service-uid','123'],
  ['--expected-service-uid','123','--fixed-config','/etc/growthmap-authority/production-composition.json'])
 for argv in invalid:
  with pytest.raises(RuntimeError,match='argv_invalid'):composition.run(argv)
 assert events==[]

def test_fresh_process_preimport_public_registry_substitution_fails_closed(tmp_path):
 import subprocess,sys,textwrap
 script=textwrap.dedent('''
 from cryptography.hazmat.primitives import serialization
 from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
 class Evil(Ed25519PublicKey):
  def verify(self,*a):pass
  def public_bytes(self,encoding,format):
   if encoding is serialization.Encoding.Raw:return b"x"*32
   if encoding is serialization.Encoding.DER:return b"evil"
   return PAYLOAD
 PAYLOAD=b"-----BEGIN PUBLIC KEY-----\\nZXZpbA==\\n-----END PUBLIC KEY-----\\n"
 serialization.load_pem_public_key=lambda raw:Evil()
 import licensing.authority_composition as c
 assert c._NATIVE_ED25519_FROM_BYTES is not serialization.load_pem_public_key
 print("registry-substitution-closed")
 ''')
 result=subprocess.run([sys.executable,'-c',script],env=os.environ|{'PYTHONPATH':str(Path(__file__).parents[1])},capture_output=True,text=True)
 assert result.returncode==0,result.stderr
 assert result.stdout.strip()=='registry-substitution-closed'

def test_fake_sys_modules_serialization_base_and_complete_subclass_cannot_substitute_native(monkeypatch,tmp_path):
 import sys,types
 from cryptography.hazmat.primitives import serialization
 from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
 good=Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
 class Evil(Ed25519PublicKey):
  def verify(self,*a):return None
  def public_bytes(self,*a,**k):return good
  def public_bytes_raw(self):return b'0'*32
  def __copy__(self):return self
  def __deepcopy__(self,memo):return self
  def __eq__(self,o):return True
 fake=types.ModuleType('cryptography.hazmat.primitives.serialization.base');fake.__spec__=types.SimpleNamespace(origin=getattr(composition,'_CRYPTOGRAPHY_EXTENSION'));fake.load_pem_public_key=lambda raw:Evil()
 monkeypatch.setitem(sys.modules,'cryptography.hazmat.primitives.serialization.base',fake);monkeypatch.setattr(serialization,'load_pem_public_key',fake.load_pem_public_key)
 verifier,_=composition._load_edge_provider(_edge_cfg(tmp_path,good));assert type(verifier.key) is composition._NATIVE_ED25519_TYPE and not isinstance(verifier.key,Evil)

def test_native_constructor_substitution_rejected_before_provider_construction(tmp_path):
 from cryptography.hazmat.primitives import serialization
 good=Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
 with pytest.raises(RuntimeError,match='edge_public_key_invalid'):
  composition._load_edge_provider(_edge_cfg(tmp_path,good),native=lambda raw:object())
