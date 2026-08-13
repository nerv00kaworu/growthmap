import hashlib,importlib.util,json,os,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).parents[2]; R13=ROOT.parents[0]/'reports/phase2-authority-production-readiness-20260808/vps-staging-r13'
def module(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def test_deterministic_explicit_manifest_double_build(tmp_path):
 b=module(R13/'deploy/build_bundle.py','r13bundle');one=tmp_path/'a.tar';two=tmp_path/'b.tar'
 assert b.build(one)==b.build(two)==hashlib.sha256(one.read_bytes()).hexdigest();assert one.read_bytes()==two.read_bytes()
 assert tarfile.open(one).getnames()==(R13/'deploy/source-manifest.txt').read_text().splitlines()

def test_unit_exact_tokens_custody_and_sandbox():
 text=(R13/'deploy/growthmap-authority-staging-r13.service.template').read_text()
 assert 'User=growthmap-auth-stg' in text and 'Group=growthmap-auth-stg' in text
 assert ' --fixed-config /etc/growthmap-authority-staging-r13/production-composition.json --expected-service-uid @SERVICE_UID@' in text
 assert '127.0.0.1' not in text and 'ReadWritePaths=/var/lib/growthmap-authority-staging-r13' in text
 for directive in ('NoNewPrivileges=yes','ProtectSystem=strict','PrivateDevices=yes','IPAddressDeny=any'):assert directive in text

def test_provision_anchor_shared_claim_idempotent_and_preserves_retained_r11(tmp_path,monkeypatch):
 p=module(R13/'provision_staging.py','r13provision');monkeypatch.setattr(p.os,'chown',lambda *a:None);monkeypatch.setattr(p.os,'fchown',lambda *a:None);state=tmp_path/'r13';config=tmp_path/'etc-r13';r11=tmp_path/'retained-r11';r11.mkdir();sentinel=r11/'authority-synthetic.pem';sentinel.write_text('preserve')
 result=p.provision(state=state,config=config,release='a'*64,uid=os.getuid(),gid=os.getgid(),now='2026-08-09T00:00:00Z')
 again=p.provision(state=state,config=config,release='a'*64,uid=os.getuid(),gid=os.getgid(),now='different')
 assert again['adopted'] and result['deployment_config_sha256']==again['deployment_config_sha256'] and sentinel.read_text()=='preserve'
 descriptor=json.loads((state/'keys/descriptor.json').read_text());anchor=json.loads((state/'keys/anchor.json').read_text())
 ceremony={'schema_version':1,'purpose':'growthmap-license-authority-signing','domain':'growthmap-activation-certificate-v2','algorithm':'Ed25519','authority_id':p.AUTH,'key_id':descriptor['key_id'],'generation':1,'activated_at':descriptor['activated_at'],'predecessor_generation':None,'public_key_sha256':descriptor['public_pem_sha256'],'provider_attestation_id':'pem-witness:'+descriptor['ceremony_record_sha256']}
 from licensing.authority import canonical_ceremony_claim
 assert anchor==canonical_ceremony_claim(ceremony)

def test_deploy_contract_has_no_ambient_digest_or_production_paths():
 text=(R13/'deploy/deploy.sh').read_text()+(R13/'deploy/rollback.sh').read_text()
 assert "RELEASE_DIGEST=$(cat \"$TMP/digest\")" in text and 'RELEASE_DIGEST=${' not in text
 assert '--require-hashes --no-index --only-binary=:all:' in text and 'getent passwd' in text
 assert '/opt/growthmap-production' not in text and '/var/lib/growthmap-production' not in text and '8310' not in text

def test_provisioned_artifacts_real_compose_restart(tmp_path,monkeypatch):
 p=module(R13/'provision_staging.py','r13provision_compose');monkeypatch.setattr(p.os,'chown',lambda *a:None);monkeypatch.setattr(p.os,'fchown',lambda *a:None)
 state=tmp_path/'r13';config=tmp_path/'etc-r13';p.provision(state=state,config=config,release='b'*64,uid=os.getuid(),gid=os.getgid(),now='2020-08-09T00:00:00Z')
 # Current composition deliberately separates deployment release identity from stable security config.
 comp_path=config/'production-composition.json';comp=json.loads(comp_path.read_text());comp.pop('release_sha256');comp_path.chmod(0o600);comp_path.write_text(json.dumps(comp));comp_path.chmod(0o400)
 import licensing.authority_composition as c
 monkeypatch.setattr(c,'FIXED_CONFIG_PATH',config/'production-composition.json')
 for _ in range(2):
  app,cfg,life=c.compose(c.FIXED_CONFIG_PATH,expected_uid=os.getuid(),release_digest="b"*64)
  assert cfg['listen']=={'host':'127.0.0.1','port':8320}
  assert life[0].anchor.read()['generation']==1
  for item in life:item.close()
 import sqlite3
 db=sqlite3.connect(state/'authority/authority.sqlite3')
 assert db.execute('select generation from signer_ceremonies').fetchall()==[(1,)]
 db.close()

def test_r14_manifest_import_closure_and_exact_bundle(tmp_path):
 r14=ROOT.parents[0]/'reports/phase2-authority-production-readiness-20260808/vps-staging-r14';v=module(r14/'deploy/verify_bundle.py','r14verify');files=v.files();v.import_closure(files);assert 'src/backend/licensing/gift_service.py' in files
 b=module(r14/'deploy/build_bundle.py','r14bundle');tar=tmp_path/'runtime.tar';digest=b.build(tar);v.verify_tar(tar,files);assert len(digest)==64

def test_r14_adversarial_transaction_and_rollback_contracts():
 r14=ROOT.parents[0]/'reports/phase2-authority-production-readiness-20260808/vps-staging-r14';deploy=(r14/'deploy/deploy.sh').read_text();rollback=(r14/'deploy/rollback.sh').read_text();restore=(r14/'deploy/transaction_restore.sh').read_text()
 assert 'REVIEWED-BUNDLE.sha256' in deploy and 'reviewed-bundle-mismatch' in deploy
 assert '.incoming-$EXPECTED_BUNDLE_SHA256-$$' in deploy and 'verify_bundle.py" --release' in deploy
 assert 'env -i' in deploy and ' -I -B -c' in deploy and 'PYTHONPATH=' not in deploy
 assert 'systemd-analyze verify "$TMP/$UNIT"' in deploy and 'acceptance.py' in deploy
 assert 'accepted-releases.json' in deploy and 'accepted-releases.json' in rollback
 assert "*[!0-9a-f]*|'')" in rollback and 'transaction_restore.sh' in rollback and 'acceptance.py' in rollback
 assert 'systemctl is-active --quiet' in restore

def test_r14_atomic_relocation_keeps_exact_unit_import_and_existing_verify(tmp_path):
 import shutil
 r14=ROOT.parents[0]/'reports/phase2-authority-production-readiness-20260808/vps-staging-r14';b=module(r14/'deploy/build_bundle.py','r14relocate_bundle');v=module(r14/'deploy/verify_bundle.py','r14relocate_verify')
 base=tmp_path/'opt/growthmap-authority-staging-r14';digest=b.build(tmp_path/'built.tar');incoming=base/f'.incoming-{digest}-random';release=base/'releases'/digest;incoming.mkdir(parents=True);shutil.copy2(tmp_path/'built.tar',incoming/'runtime.tar')
 with tarfile.open(incoming/'runtime.tar') as tar:tar.extractall(incoming,filter='data')
 manifest={x:hashlib.sha256((incoming/x).read_bytes()).hexdigest() for x in v.files()};(incoming/'source-files.sha256').write_text(json.dumps(manifest,sort_keys=True,separators=(',',':')))
 subprocess.run([sys.executable,'-m','venv',str(incoming/'venv')],check=True)
 site=incoming/'venv/lib/python3.12/site-packages';site.mkdir(parents=True,exist_ok=True)
 dependency_site=next(Path(x) for x in sys.path if x.endswith('site-packages') and (Path(x)/'fastapi').exists())
 shutil.copytree(dependency_site,site,dirs_exist_ok=True)
 pth=site/'growthmap-r14.pth';pth.write_text(f'{release}/src/backend\n{release}/services/payments\n')
 (incoming/'venv-provenance.json').write_text(json.dumps({'release_sha256':digest,'python':str(release/'venv/bin/python')},sort_keys=True))
 release.parent.mkdir(parents=True);incoming.rename(release);assert not incoming.exists()
 result=subprocess.run(['env','-i','PATH=/usr/bin:/bin','PYTHONDONTWRITEBYTECODE=1',str(release/'venv/bin/python'),'-I','-B','-c','import licensing.authority_composition as c;c._providers_available();print(c.__file__)'],cwd=release,capture_output=True,text=True)
 assert result.returncode==0,result.stderr;assert str(release/'src/backend/licensing/authority_composition.py') in result.stdout
 v.verify_release(release,digest)
 relocated_pth=release/'venv/lib/python3.12/site-packages/growthmap-r14.pth'
 relocated_pth.write_text(f'{incoming}/src/backend\n{incoming}/services/payments\n')
 try:v.verify_release(release,digest)
 except RuntimeError as exc:assert str(exc)=='venv_first_party_path_invalid'
 else:raise AssertionError('stale incoming path accepted')
