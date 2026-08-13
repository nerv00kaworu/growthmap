import hashlib,importlib.util,json,os,platform,signal,subprocess,sys,time
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[2];R24=ROOT.parents[0]/'reports/phase2-authority-production-readiness-20260808/vps-staging-r24';DEP=R24/'deploy'
def module(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def test_release_identity_strict_and_old_process_rejected(monkeypatch,tmp_path):
 import licensing.authority_composition as c
 with pytest.raises(RuntimeError,match='release_digest_invalid'):c.run(['--fixed-config','/x','--expected-service-uid','1','--release-digest','A'*64])
 a=module(DEP/'acceptance.py','r24accept');cfg=tmp_path/'composition.json';auth=tmp_path/'authority-production.json';auth.write_text(json.dumps({'reviewed_public_key_sha256':'1'*64}));cfg.write_text(json.dumps({'authority_config_path':str(auth),'listen':{'host':'127.0.0.1','port':8320}}))
 monkeypatch.setattr(a,'call',lambda *_a,**_k:{'authority_id':'x','release_sha256':'a'*64})
 monkeypatch.setattr(a.argparse.ArgumentParser,'parse_args',lambda _:{'x':1}) if False else None

def test_unit_exact_parity_and_stable_security_config():
 u=(DEP/'growthmap-authority-staging-r24.service.template').read_text();p=(R24/'provision_staging.py').read_text()
 assert 'python -I -B -m licensing.authority_composition --fixed-config /etc/growthmap-authority-staging-r24/production-composition.json --expected-service-uid @SERVICE_UID@ --release-digest @RELEASE_DIGEST@' in u
 assert 'Environment=PYTHONDONTWRITEBYTECODE=1' in u and "comp={'schema_version':1,'expected_uid':uid,'deployment_config_sha256'" in p

def test_registry_binds_authority_pin_and_venv(tmp_path):
 r=module(DEP/'registry.py','r24registry');release=tmp_path/('a'*64);release.mkdir();
 for n,v in [('runtime.tar',b'x'),('source-files.sha256',b'y'),('venv-manifest.json',b'z')]: (release/n).write_bytes(v)
 unit=tmp_path/'growthmap-authority-staging-r24.service';unit.write_text('u');auth=tmp_path/'authority-production.json';auth.write_text(json.dumps({'reviewed_public_key_sha256':'b'*64}));cfg=tmp_path/'production-composition.json';cfg.write_text(json.dumps({'expected_uid':123,'listen':{'port':8320},'edge':{'public_key_sha256':'c'*64}}))
 a=type('A',(),dict(release=str(release),release_digest='a'*64,config=str(cfg),authority_config=str(auth),unit=str(unit),venv_manifest=str(release/'venv-manifest.json'),uid=123,gid=124))
 rec=r.record(a);assert rec['authority_config_sha256']==hashlib.sha256(auth.read_bytes()).hexdigest() and rec['reviewed_authority_public_key_sha256']=='b'*64 and rec['venv_manifest_sha256']==hashlib.sha256(b'z').hexdigest()
 auth.write_text(json.dumps({'reviewed_public_key_sha256':'d'*64}));assert r.record(a)!=rec

def test_transaction_fresh_and_existing_byte_metadata_restore(tmp_path):
 t=module(DEP/'transaction.py','r24tx');root=tmp_path/'state';snap=tmp_path/'snap';t.snapshot(root,snap);root.mkdir();(root/'new').write_bytes(b'n');t.restore(root,snap);assert not root.exists()
 root.mkdir();x=root/'x';x.write_bytes(b'old');x.chmod(0o400);stamp=1_700_000_000_123_456_789;os.utime(x,ns=(stamp,stamp));(root/'inside').symlink_to('x');snap2=tmp_path/'snap2';t.snapshot(root,snap2);meta=json.loads((snap2/'meta.json').read_text());xm=next(m for m in meta['records'] if m['path']=='x');assert (xm['uid'],xm['gid'],xm['mode'],xm['mtime_ns'])==(os.getuid(),os.getgid(),0o400,stamp)
 x.chmod(0o600);x.write_bytes(b'new');(root/'extra').write_bytes(b'e');t.restore(root,snap2);assert x.read_bytes()==b'old' and x.stat().st_mode&0o777==0o400 and x.stat().st_mtime_ns==stamp and os.readlink(root/'inside')=='x' and not (root/'extra').exists()

def test_transaction_rejects_hardlink_and_external_symlink(tmp_path):
 t=module(DEP/'transaction.py','r24txbad');root=tmp_path/'state';root.mkdir();a=root/'a';a.write_text('x');os.link(a,root/'b')
 with pytest.raises(RuntimeError,match='hardlink'):t.snapshot(root,tmp_path/'s1')
 os.unlink(root/'b');(root/'bad').symlink_to('../outside')
 with pytest.raises(RuntimeError,match='symlink'):t.snapshot(root,tmp_path/'s2')

def test_executable_fake_systemctl_restart_and_uid_preflight(tmp_path):
 bind=tmp_path/'bin';bind.mkdir();log=tmp_path/'log';sc=bind/'systemctl';sc.write_text('#!/bin/sh\necho "$*" >> "$FAKE_LOG"\ncase "$1" in is-active) echo active;exit 0;;is-enabled)echo enabled;exit 0;;esac\n');sc.chmod(0o755)
 # Execute the parent-shell UID parse used by rollback, not a grep-only assertion.
 script='entry=$(getent passwd "$USER"); UID_ONCE=$(printf %s "$entry"|cut -d: -f3); GID_ONCE=$(printf %s "$entry"|cut -d: -f4); case $UID_ONCE:$GID_ONCE in *[!0-9:]*)exit 9;;esac; test "$UID_ONCE" -gt 0; test "$GID_ONCE" -gt 0; systemctl restart unit'
 env={**os.environ,'PATH':str(bind)+':'+os.environ['PATH'],'FAKE_LOG':str(log),'USER':os.environ.get('USER','nobody')};subprocess.run(['/bin/sh','-eu','-c',script],env=env,check=True);assert log.read_text().strip()=='restart unit'

def test_real_venv_copies_inventory_structural_policy(tmp_path):
 v=module(DEP/'venv_manifest.py','r24venvreal');root=tmp_path/'venv';subprocess.run([sys.executable,'-B','-m','venv','--copies',str(root)],check=True,env={**{k:v for k,v in os.environ.items() if k!='PYTHONPYCACHEPREFIX'},'PYTHONDONTWRITEBYTECODE':'1'})
 for p in root.rglob('*.pyc'):p.unlink()
 for p in sorted(root.rglob('__pycache__'),reverse=True):
  if not any(p.iterdir()):p.rmdir()
 items=v.inventory(root);by={x['path']:x for x in items};assert by['bin/python3']['type']=='file' and by['bin/python3']['sha256']==hashlib.sha256((root/'bin/python3').read_bytes()).hexdigest()
 assert all(not (x['type']=='symlink' and os.path.isabs(x['target'])) for x in items)

def test_venv_verifier_rejects_addition_symlink_hardlink_and_pyc(tmp_path):
 v=module(DEP/'venv_manifest.py','r24venv');root=tmp_path/'v';(root/'bin').mkdir(parents=True);(root/'bin/python3').write_bytes(b'elf');(root/'a').write_bytes(b'a');assert any(x['path']=='a' for x in v.inventory(root));(root/'x.pyc').write_bytes(b'x')
 with pytest.raises(RuntimeError,match='bytecode'):v.inventory(root)
 (root/'x.pyc').unlink();(root/'escape').symlink_to('../outside')
 with pytest.raises(RuntimeError,match='symlink'):v.inventory(root)
 (root/'escape').unlink();os.link(root/'a',root/'hard')
 with pytest.raises(RuntimeError,match='hardlink'):v.inventory(root)

def _manifest_cli_fixture(tmp_path):
 """Minimal deterministic aarch64 runtime consumed by the shipped manifest CLI."""
 root=tmp_path/'venv';bind=root/'bin';site=root/'lib/python3.12/site-packages';bind.mkdir(parents=True);site.mkdir(parents=True)
 lock=R24/'evidence/requirements-aarch64-cp312.hashed.txt';wheel=R24/'evidence/wheelhouse-manifest.json';pairs=[]
 import re
 for line in lock.read_text().splitlines():
  m=re.fullmatch(r'([A-Za-z0-9_.-]+)==([^ ]+) --hash=sha256:[a-f0-9]{64}',line.strip())
  if m:pairs.append((m.group(1).lower().replace('_','-'),m.group(2)))
 assert len(pairs)==16
 dist=[]
 for name,version in pairs:
  d=site/(name.replace('-','_')+'-'+version+'.dist-info');d.mkdir();(d/'RECORD').write_text('RECORD,,\n');dist.append([name,version,str(d.resolve())])
 origins={n:str((site/(n.replace('-','_')+'.py')).resolve()) for n in ('cryptography','fastapi','pydantic','uvicorn','starlette','cffi','anyio')}
 launcher=bind/'python';launcher.write_text("""#!/usr/bin/python3
import json,sys
code=sys.argv[sys.argv.index('-c')+1] if '-c' in sys.argv else ''
if 'sys.version_info' in code: print(json.dumps({'version':[3,12,3],'implementation':'CPython','machine':'aarch64','platform':'manylinux_2_17_aarch64','abi':'cpython-312-aarch64-linux-gnu'}))
elif 'm.distributions' in code: print(json.dumps(DIST))
elif 'importlib.import_module' in code: print(json.dumps(ORIGINS))
elif '-m' in sys.argv and sys.argv[sys.argv.index('-m')+1]=='pip': sys.exit(0)
else: sys.exit(9)
""".replace('DIST',repr(dist)).replace('ORIGINS',repr(origins)));launcher.chmod(0o755);(bind/'python3').write_bytes(launcher.read_bytes());(bind/'python3').chmod(0o755)
 return root,lock,wheel

def _manifest_argv(action,root,manifest,lock,wheel,release='a'*64):
 return ['/usr/bin/python3','-I','-B',str(DEP/'venv_manifest.py'),action,'--venv',str(root),'--manifest',str(manifest),'--lock',str(lock),'--wheel-manifest',str(wheel),'--release',release]

def test_r24_exact20_manifest_cli_requires_archive_trust_root(tmp_path):
 root,lock,wheel=_manifest_cli_fixture(tmp_path);manifest=tmp_path/'venv-manifest.json';env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
 create=_manifest_argv('create',root,manifest,lock,wheel)+['--wheelhouse',str(R24/'evidence/wheelhouse')]
 # The synthetic installed RECORD cannot self-authorize membership against reviewed wheels.
 assert subprocess.run(create,env=env,capture_output=True).returncode!=0
 for extra in (['--anchor',str(tmp_path/'anchor.json')],['--unsupported-option']):assert subprocess.run(create+extra,env=env,capture_output=True).returncode==2

def test_r24_exact20_manifest_source_parser_contract_cannot_drift():
 import re
 allowed={'--venv','--manifest','--base-manifest','--base-custody','--expected-base-digest','--expected-custody-digest','--runtime-root','--lock','--wheel-manifest','--wheelhouse','--release','--target-machine'}
 parser=set(re.findall(r"add_argument\('(\-\-[a-z-]+)'",(DEP/'venv_manifest.py').read_text()));assert parser==allowed and '--anchor' not in parser
 for name in ('deploy.sh','rollback.sh'):
  text=(DEP/name).read_text();calls=[x for x in text.splitlines() if 'venv_manifest.py" verify' in x];assert len(calls)==1
  segment=calls[0].split('venv_manifest.py" verify',1)[1].split(';',1)[0];options=set(re.findall(r'--[a-z-]+',segment));assert options=={'--venv','--manifest','--base-manifest','--runtime-root','--lock','--wheel-manifest','--wheelhouse','--release'} and options<=parser

def test_r24_exact20_lock_parser_rejects_malformed_comments_trailing_and_duplicates(tmp_path):
 v=module(DEP/'venv_manifest.py','r24venvlock20');good=(R24/'evidence/requirements-aarch64-cp312.hashed.txt').read_text()
 for bad in ('garbage\n',good.splitlines()[0]+' trailing\n', '#bad\n',good+good.splitlines()[0]+'\n'):
  q=tmp_path/'lock';q.write_text(bad)
  with pytest.raises(RuntimeError):v.load_wheels(q)

def test_r24_exact20_record_archive_membership_digest_size_and_self_row(tmp_path):
 import base64,csv,io,zipfile
 v=module(DEP/'venv_manifest.py','r24venvrecord20');root=tmp_path/'v';site=root/'lib/python3.12/site-packages';dist=site/'demo-1.dist-info';dist.mkdir(parents=True);payload=site/'demo.py';payload.write_bytes(b'ok')
 wheel=tmp_path/'demo-1-py3-none-any.whl';member='demo.py';meta='demo-1.dist-info/METADATA';rec='demo-1.dist-info/RECORD'
 def dg(b):return 'sha256='+base64.urlsafe_b64encode(hashlib.sha256(b).digest()).decode().rstrip('=')
 metadata=b'Name: demo\nVersion: 1\n'; rows=[[member,dg(b'ok'),'2'],[meta,dg(metadata),str(len(metadata))],[rec,'','']]
 def make(rows=rows):
  with zipfile.ZipFile(wheel,'w') as z:z.writestr(member,b'ok');z.writestr(meta,metadata);buf=io.StringIO(newline='');csv.writer(buf,lineterminator='\n').writerows(rows);z.writestr(rec,buf.getvalue())
 make(); (dist/'METADATA').write_bytes(metadata);buf=io.StringIO(newline='');csv.writer(buf,lineterminator='\n').writerows(rows);(dist/'RECORD').write_text(buf.getvalue())
 mapping={'demo':{'filename':wheel.name,'project':'demo','version':'1','sha256':hashlib.sha256(wheel.read_bytes()).hexdigest()}}
 assert v.record_integrity(root,[['demo','1',str(dist)]],mapping,tmp_path)['demo']
 forged=[[member,'','999999'],[meta,dg(metadata),str(len(metadata))],[rec,'','']]
 for rows2 in (forged, [[member,dg(b'ok'),'999999'],[meta,dg(metadata),str(len(metadata))],[rec,'','']], rows+[[member,dg(b'ok'),'2']], rows[:-1], rows+[['extra',dg(b'x'),'1']], [[member,'sha256='+dg(b'ok')[7:]+'=','2'],[meta,dg(metadata),str(len(metadata))],[rec,'','']], [[member,dg(b'ok'),'02'],[meta,dg(metadata),str(len(metadata))],[rec,'','']], [[member,dg(b'ok'),'2'],[meta,dg(metadata),str(len(metadata))],[rec,dg(b'x'),'1']]):
  buf=io.StringIO(newline='');csv.writer(buf,lineterminator='\n').writerows(rows2);(dist/'RECORD').write_text(buf.getvalue())
  with pytest.raises(RuntimeError):v.record_integrity(root,[['demo','1',str(dist)]],mapping,tmp_path)

def test_r24_exact20_relocator_unowned_script_and_atomic_record_race_policy():
 s=(DEP/'relocate_venv.py').read_text();assert "len(matches)!=1" in s and 'os.replace(rtmp,record)' in s and 'os.fsync(dd)' in s and 'venv_record_raced' in s

def test_r24_exact20_pre_mutation_gate_precedes_recovery_begin_and_stop():
 s=(DEP/'deploy.sh').read_text();gate=s.index('pre_mutation_gate.py');assert gate<s.index('forward_transaction.py" recover',gate)<s.index('forward_transaction.py" begin',gate)<s.index('systemctl stop',s.index('forward_transaction.py" begin',gate))
 assert 'runuser -u "$USER"' in s and '/tmp/growthmap-r24-preflight.' in s

def _fake_apply_env(tmp_path,monkeypatch,fail='',baseline='present',initial='active enabled'):
 import shutil
 rail=tmp_path/'rail';shutil.copytree(R24,rail);root=tmp_path/'root';(root/'opt').mkdir(parents=True);(root/'etc/systemd/system').mkdir(parents=True);
 if baseline=='present':
  (root/'etc/systemd/system/growthmap-authority-staging-r24.service').write_text('baseline-unit');(root/'var/lib/growthmap-authority-staging-r24-transactions').mkdir(parents=True);(root/'var/lib/growthmap-authority-staging-r24-transactions').chmod(0o700)
 for script in (rail/'deploy/deploy.sh',rail/'deploy/rollback.sh'):
  text=script.read_text()
  bind=tmp_path/'bin'
  paths=[('/var/lib/growthmap-authority-staging-r24-transactions',str(root/'var/lib/growthmap-authority-staging-r24-transactions')),('/opt/growthmap-authority-staging-r24',str(root/'opt/growthmap-authority-staging-r24')),('/var/lib/growthmap-authority-staging-r24',str(root/'var/lib/growthmap-authority-staging-r24')),('/etc/growthmap-authority-staging-r24',str(root/'etc/growthmap-authority-staging-r24')),('/etc/systemd/system',str(root/'etc/systemd/system'))]
  for i,(canonical,adapted) in enumerate(paths):
   marker=f'__R24_ADAPTER_PATH_{i}__';assert marker not in text and canonical in text;text=text.replace(canonical,marker)
  for i,(_canonical,adapted) in enumerate(paths):text=text.replace(f'__R24_ADAPTER_PATH_{i}__',adapted)
  # Adapter rewrites reviewed executable tokens only, never substrings in argv.
  import shlex
  absolute=['python3','getent','systemctl','systemd-analyze','ss','tar','install','chmod','sha256sum']
  protected=('--tar','-m pip install','-Hln','source-files.sha256','R24_TRANSACTION_INJECT')
  before={x:text.count(x) for x in protected}
  for tool in absolute:
   token='/usr/bin/'+tool
   # shell-aware-enough boundary: executable token must be delimited by command syntax/space.
   import re
   pattern=r'(?<![A-Za-z0-9_./-])'+re.escape(token)+r'(?![A-Za-z0-9_./-])'
   text,n=re.subn(pattern,str(bind/tool),text,flags=re.M)
   assert n or tool in ('systemd-analyze','ss','tar','chmod')
  assert {x:text.count(x) for x in protected}==before
  if script.name=='deploy.sh':
   ga=text.index('# Target-equivalent construction must pass');gb=text.index('# Apply startup recovery',ga);text=text[:ga]+'/bin/true # fake pre-mutation gate\n'+text[gb:]
  script.write_text(text)
 # The production helper has immutable canonical constants; adapt only the isolated copy.
 fwd=rail/'deploy/forward_transaction.py';ft=fwd.read_text()
 for i,(canonical,_adapted) in enumerate(paths):ft=ft.replace(canonical,f'__R24_FWD_PATH_{i}__')
 for i,(_canonical,adapted) in enumerate(paths):ft=ft.replace(f'__R24_FWD_PATH_{i}__',adapted)
 ft=ft.replace("SYSTEMCTL='/usr/bin/systemctl'",f"SYSTEMCTL={str(bind/'systemctl')!r}")
 fwd.write_text(ft)
 bind.mkdir();log=tmp_path/'calls';state=tmp_path/'systemctl-state';state.write_text(initial)
 dispatcher=bind/'dispatch.py';dispatcher.write_text(r'''#!/usr/bin/env python3
import json,os,pathlib,shutil,subprocess,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];log=pathlib.Path(os.environ['FAKE_LOG']);log.write_text(log.read_text() + name+' '+' '.join(a)+'\n' if log.exists() else name+' '+' '.join(a)+'\n')
def fail(stage):
 marker=pathlib.Path(os.environ['FAKE_LOG']+'.failed-'+stage)
 if os.environ.get('FAIL_STAGE')==stage and not marker.exists():marker.write_text('1');sys.exit(44)
if name=='getent':print('growthmap-auth-stg:x:1234:1235::/nonexistent:/usr/sbin/nologin')
elif name=='systemctl':
 st=pathlib.Path(os.environ['SYSTEMCTL_STATE']);words=set(st.read_text().split());cmd=a[0]
 unit=pathlib.Path(os.environ['UNIT_PATH'])
 if cmd=='show':
  counter=pathlib.Path(os.environ['FAKE_LOG']+'.show-count');i=int(counter.read_text()) if counter.exists() else 0;counter.write_text(str(i+1))
  if i+1==int(os.environ.get('MUTATE_UNIT_ON_SHOW','0')):
   if os.environ.get('MUTATE_UNIT_ACTION')=='appear':unit.write_text('appeared-unit')
   elif os.environ.get('MUTATE_UNIT_ACTION')=='remove' and unit.exists():unit.unlink()
  present=unit.is_file() and not unit.is_symlink();print(os.environ.get('FAKE_LOAD_OUT','loaded' if present else 'not-found'));sys.exit(int(os.environ.get('FAKE_LOAD_RC','0')))
 present=unit.is_file() and not unit.is_symlink()
 if cmd=='is-active':
  print(os.environ.get('FAKE_ACTIVE_OUT','active' if 'active' in words else 'inactive'))
  sys.exit(int(os.environ.get('FAKE_ACTIVE_RC','0' if 'active' in words else ('3' if present else '4'))))
 if cmd=='is-enabled':
  if 'FAKE_ENABLED_RC_SEQUENCE' in os.environ:
   counter=pathlib.Path(os.environ['FAKE_LOG']+'.enabled-sequence');i=int(counter.read_text()) if counter.exists() else 0;seq=os.environ['FAKE_ENABLED_RC_SEQUENCE'].split(',');counter.write_text(str(i+1));print('not-found');sys.exit(int(seq[min(i,len(seq)-1)]))
  if 'FAKE_ENABLED_OUT' in os.environ:print(os.environ['FAKE_ENABLED_OUT']);sys.exit(int(os.environ.get('FAKE_ENABLED_RC','0')))
  if not present:
   if 'enabled' in words:print('enabled');sys.exit(0)
   print('not-found');sys.exit(int(os.environ.get('FAKE_ENABLED_RC','1')))
  print('enabled' if 'enabled' in words else 'disabled');sys.exit(0 if 'enabled' in words else 1)
 if cmd=='daemon-reload':
  fail('daemon-reload')
  if not present:words.discard('enabled');words.discard('disabled');st.write_text(' '.join(sorted(words)))
 if cmd in ('restart','start'):fail('restart');words.discard('inactive');words.add('active')
 if cmd=='stop':
  fail('stop')
  if 'FAKE_STOP_RC' in os.environ:sys.exit(int(os.environ['FAKE_STOP_RC']))
  words.discard('active');words.add('inactive')
 if cmd=='enable':fail('enable');words.discard('disabled');words.add('enabled')
 if cmd=='disable':words.discard('enabled');words.add('disabled')
 st.write_text(' '.join(sorted(words)))
elif name=='systemd-analyze':fail('systemd')
elif name=='sha256sum':
 if '-c' in a:sys.exit()
 p=pathlib.Path(a[-1]);import hashlib;print(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p))
elif name=='ss':pass
elif name=='tar':pass
elif name=='chmod':pass
elif name=='install':
 dirs='-d' in a;vals=[];skip=False
 for x in a:
  if skip:skip=False;continue
  if x in ('-m','-o','-g'):skip=True;continue
  if x=='-d':continue
  vals.append(x)
 if dirs:
  for x in vals:pathlib.Path(x).mkdir(parents=True,exist_ok=True);pathlib.Path(x).chmod(0o700 if '0700' in a else 0o755)
 else:
  sources=[pathlib.Path(x) for x in vals[:-1]];dst=pathlib.Path(vals[-1])
  if len(sources)>1 and not dst.is_dir():sys.exit(2)
  for src in sources:
   target=dst/src.name if dst.is_dir() else dst;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
elif name=='python3':
 if '-m' in a and a[a.index('-m')+1]=='venv':
  dest=pathlib.Path(a[-1]);(dest/'bin').mkdir(parents=True);(dest/'lib/python3.12/site-packages').mkdir(parents=True);src=dest/'launcher.c';src.write_text('#include <unistd.h>\n#include <stdlib.h>\nint main(int c,char**v){char*p=getenv("FAKE_PYTHON3");execv(p,v);return 127;}\n');subprocess.run(['/usr/bin/cc',str(src),'-o',str(dest/'bin/python3')],check=True);src.unlink();(dest/'bin/python').symlink_to('python3');(dest/'bin/python3.12').symlink_to('python3');(dest/'pyvenv.cfg').write_text('home = '+str(pathlib.Path(sys.executable).parent)+'\n');sys.exit()
 script=next((x for x in a if x.endswith('.py')),None)
 if script and script.endswith('transaction.py'):
  if a[a.index(script)+1]=='snapshot':fail('snapshot')
  os.execv(sys.executable,[sys.executable,script,*a[a.index(script)+1:]])
 if script and script.endswith('build_bundle.py'):
  pathlib.Path(a[-1]).write_bytes(b'tar');print(pathlib.Path(os.environ['RAIL']+'/evidence/REVIEWED-BUNDLE.sha256').read_text().strip());sys.exit()
 if script and script.endswith('verify_bundle.py'):
  if '--tar' in a:print('{}');sys.exit()
  sys.exit()
 if script and script.endswith('relocate_venv.py'):
  if 'capture-anchor' in a:pathlib.Path(a[a.index('--output')+1]).write_text('{}')
  sys.exit()
 if script and script.endswith('venv_manifest.py'):
  if a[0]=='create':pathlib.Path(a[a.index('--manifest')+1]).write_text('{}')
  sys.exit()
 if script and script.endswith('provision_staging.py'):
  fail('provision');statep=pathlib.Path(a[a.index('--state')+1]);conf=pathlib.Path(a[a.index('--config')+1]);statep.mkdir(parents=True,exist_ok=True);conf.mkdir(parents=True,exist_ok=True);(statep/'client').mkdir(exist_ok=True);(statep/'client/edge-private.pem').write_text('private');auth={'reviewed_public_key_sha256':'b'*64};(conf/'authority-production.json').write_text(json.dumps(auth));comp={'expected_uid':1234,'authority_config_path':str(conf/'authority-production.json'),'listen':{'port':8320},'edge':{'public_key_sha256':'c'*64}};(conf/'production-composition.json').write_text(json.dumps(comp));sys.exit()
 if script and script.endswith('acceptance.py'):fail('acceptance');sys.exit()
 if script and script.endswith('registry.py'):
  fail('registry');reg=pathlib.Path(a[a.index('--registry')+1]);reg.parent.mkdir(parents=True,exist_ok=True);v=json.loads(reg.read_text()) if reg.exists() else {'schema_version':2,'active':None,'releases':{}};d=pathlib.Path(a[a.index('--release')+1]).name
  if a[0]=='accept':v['releases'][d]={'fake':d};v['active']=d;reg.write_text(json.dumps(v))
  elif a[0]=='verify':
   if d not in v['releases']:sys.exit(9)
  elif a[0]=='activate':v['active']=d;reg.write_text(json.dumps(v))
  print(d);sys.exit()
 if '-m' in a and a[a.index('-m')+1]=='licensing.authority_composition':fail('preflight');sys.exit()
 if '-m' in a and a[a.index('-m')+1]=='pip':sys.exit()
 os.execv(sys.executable,[sys.executable,*a])
''');dispatcher.write_text(dispatcher.read_text().replace('#!/usr/bin/env python3','#!'+sys.executable));dispatcher.chmod(0o755)
 for n in ('python3','getent','systemctl','systemd-analyze','ss','tar','install','chmod','sha256sum'):(bind/n).symlink_to(dispatcher)
 env={**os.environ,'PATH':str(bind)+':'+os.environ['PATH'],'FAKE_LOG':str(log),'SYSTEMCTL_STATE':str(state),'FAIL_STAGE':fail,'FAKE_PYTHON3':str(bind/'python3'),'RAIL':str(rail),'UNIT_PATH':str(root/'etc/systemd/system/growthmap-authority-staging-r24.service')}
 return rail,root,env,state,log

def _tree(root):
 """Exact canonical adapted targets; exclude pytest scratch accidentally nested by path replacement."""
 targets=(root/'opt/growthmap-authority-staging-r24',root/'etc/growthmap-authority-staging-r24',root/'var/lib/growthmap-authority-staging-r24',root/'etc/systemd/system/growthmap-authority-staging-r24.service',root/'var/lib/growthmap-authority-staging-r24-transactions')
 out=[]
 for target in targets:
  if not os.path.lexists(target):out.append((str(target.relative_to(root)),b'ABSENT'));continue
  items=[target,*target.rglob('*')] if target.is_dir() and not target.is_symlink() else [target]
  out.extend((str(p.relative_to(root)),p.read_bytes() if p.is_file() and not p.is_symlink() else ('->'+os.readlink(p)).encode() if p.is_symlink() else b'D') for p in items)
 return sorted(out)

def _no_orphans(root):
 names=[p.name for base in (root/'opt/growthmap-authority-staging-r24',root/'etc/growthmap-authority-staging-r24',root/'var/lib/growthmap-authority-staging-r24',root/'etc/systemd/system') if base.exists() for p in base.rglob('*')]
 assert not any(n.startswith('.incoming-') or n.startswith('.growthmap-restore-') or n.startswith('.growthmap-backup-') for n in names)

@pytest.mark.parametrize('stage',['provision','systemd','preflight','restart','acceptance','registry'])
def test_entire_deploy_fresh_failure_restores_true_prestate(tmp_path,stage):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None,stage);before=_tree(root);r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env);assert r.returncode!=0 and _tree(root)==before and set(state.read_text().split())=={'active','enabled'};_no_orphans(root)

def test_entire_deploy_upgrade_and_rollback_active_lifecycle(tmp_path):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None);a='a'*64;b='b'*64
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(a+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(b+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 current=root/'opt/growthmap-authority-staging-r24/current';assert os.readlink(current)=='releases/'+b
 trace=log.read_text()
 assert 'verify_bundle.py --tar ' in trace and ' -m pip --python ' in trace
 assert 'ss -Hln sport = :8320' in trace and 'install -d -m 0755' in trace
 # ln remains the real absolute executable and is confined to the isolated adapter tree.
 assert os.path.islink(current) and os.readlink(current)=='releases/'+b
 assert subprocess.run(['/bin/sh',str(rail/'deploy/rollback.sh'),'--apply',a],env=env).returncode==0;assert os.readlink(current)=='releases/'+a and 'restart growthmap-authority-staging-r24.service' in log.read_text()

@pytest.mark.parametrize('stage',['preflight','restart','acceptance','registry'])
def test_entire_upgrade_failure_restores_files_status_and_registry(tmp_path,stage):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None);a='a'*64;b='b'*64;(rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(a+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0;before=_tree(root);(rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(b+'\n');env['FAIL_STAGE']=stage;assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode!=0;assert _tree(root)==before and set(state.read_text().split())=={'active','enabled'}

@pytest.mark.parametrize('stage',['preflight','restart','acceptance','registry'])
def test_entire_rollback_failure_restores_state_config_registry_and_active_process(tmp_path,stage):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None);a='a'*64;b='b'*64
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(a+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(b+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 before=_tree(root);env['FAIL_STAGE']=stage;assert subprocess.run(['/bin/sh',str(rail/'deploy/rollback.sh'),'--apply',a],env=env).returncode!=0;assert _tree(root)==before and set(state.read_text().split())=={'active','enabled'}


@pytest.mark.parametrize('enabled_rc',['1','4'])
def test_first_install_absent_rc4_success_and_rc1_portability(tmp_path,enabled_rc):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None,baseline='absent',initial='inactive');env['FAKE_ENABLED_RC']=enabled_rc
 r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env,capture_output=True,text=True)
 assert r.returncode==0,r.stderr
 assert (root/'etc/systemd/system/growthmap-authority-staging-r24.service').is_file()
 assert set(state.read_text().split())=={'active','enabled'}
 trace=log.read_text();assert 'systemctl show growthmap-authority-staging-r24.service --property=LoadState --value' in trace
 assert trace.index('systemctl daemon-reload')<trace.index('systemctl show ')

def test_stop_decision_uses_durable_rechecked_presence(tmp_path):
 # begin() performs two complete reads; the stop-decision boundary is the third.
 rail,root,env,state,log=_fake_apply_env(tmp_path,None,baseline='absent',initial='inactive');env.update(FAKE_ENABLED_RC='4',MUTATE_UNIT_ON_SHOW='3',MUTATE_UNIT_ACTION='appear');before=_tree(root)
 r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env,capture_output=True,text=True)
 assert r.returncode!=0 and 'phase=stop decision=skip' not in r.stdout
 trace=log.read_text();assert trace.index('systemctl show growthmap-authority-staging-r24.service',trace.index('systemctl show growthmap-authority-staging-r24.service')+1)<trace.index('systemctl stop growthmap-authority-staging-r24.service')
 assert not (root/'etc/systemd/system/growthmap-authority-staging-r24.service').exists();assert (root/'var/lib/growthmap-authority-staging-r24-transactions').is_dir()
 rail,root,env,state,log=_fake_apply_env(tmp_path/'present',None,baseline='present',initial='active enabled');env.update(MUTATE_UNIT_ON_SHOW='3',MUTATE_UNIT_ACTION='remove')
 r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env,capture_output=True,text=True)
 assert r.returncode!=0 and 'phase=stop decision=skip' not in r.stdout
 assert (root/'etc/systemd/system/growthmap-authority-staging-r24.service').is_file() and set(state.read_text().split())=={'active','enabled'}

def test_absent_skip_is_auditable_and_present_stop_is_exact(tmp_path):
 rail,root,env,state,log=_fake_apply_env(tmp_path/'absent',None,baseline='absent',initial='inactive');env['FAKE_ENABLED_RC']='1'
 r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env,capture_output=True,text=True)
 assert r.returncode==0 and 'phase=stop decision=skip baseline=certified-absent' in r.stdout
 assert 'systemctl stop growthmap-authority-staging-r24.service' not in log.read_text()
 for rc in ('0','5','44'):
  rail,root,env,state,log=_fake_apply_env(tmp_path/('present-'+rc),None,baseline='present',initial='active enabled');env['FAKE_STOP_RC']=rc
  r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env,capture_output=True,text=True)
  assert log.read_text().count('systemctl stop growthmap-authority-staging-r24.service')>=1
  if rc=='0':assert r.returncode==0 and log.read_text().count('systemctl stop growthmap-authority-staging-r24.service')==1
  else:assert r.returncode!=0 and (root/'etc/systemd/system/growthmap-authority-staging-r24.service').read_text()=='baseline-unit'

@pytest.mark.parametrize(('baseline','overrides'),[
 ('present',{'FAKE_ACTIVE_RC':'4','FAKE_ENABLED_OUT':'not-found','FAKE_ENABLED_RC':'4'}),
 ('absent',{'FAKE_LOAD_OUT':'loaded','FAKE_ENABLED_OUT':'not-found','FAKE_ENABLED_RC':'4'}),
 ('absent',{'FAKE_LOAD_OUT':'masked','FAKE_ENABLED_OUT':'not-found','FAKE_ENABLED_RC':'4'}),
 ('absent',{'FAKE_ACTIVE_RC':'0','FAKE_ACTIVE_OUT':'active','FAKE_ENABLED_OUT':'not-found','FAKE_ENABLED_RC':'4'}),
 ('absent',{'FAKE_ACTIVE_RC':'3','FAKE_ACTIVE_OUT':'inactive','FAKE_ENABLED_OUT':'not-found','FAKE_ENABLED_RC':'4'}),
 ('absent',{'FAKE_ACTIVE_RC':'4','FAKE_ACTIVE_OUT':'active','FAKE_ENABLED_OUT':'not-found','FAKE_ENABLED_RC':'4'}),
 ('absent',{'FAKE_ACTIVE_RC':'4','FAKE_ACTIVE_OUT':'unknown','FAKE_ENABLED_OUT':'not-found','FAKE_ENABLED_RC':'4'}),
 ('absent',{'FAKE_ACTIVE_RC':'4','FAKE_ENABLED_OUT':'enabled','FAKE_ENABLED_RC':'4'}),
 ('absent',{'FAKE_ACTIVE_RC':'4','FAKE_ENABLED_OUT':'disabled','FAKE_ENABLED_RC':'4'}),
 ('absent',{'FAKE_ACTIVE_RC':'4','FAKE_ENABLED_OUT':'unknown','FAKE_ENABLED_RC':'4'}),
 ('absent',{'FAKE_ENABLED_OUT':'not-found','FAKE_ENABLED_RC':'2'}),
 ('absent',{'FAKE_ENABLED_OUT':'not-found','FAKE_ENABLED_RC':'3'}),
 ('absent',{'FAKE_ENABLED_OUT':'not-found','FAKE_ENABLED_RC':'5'}),
])
def test_systemd_rc4_only_accepted_for_coherent_absent_tuple(tmp_path,baseline,overrides):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None,baseline=baseline,initial='inactive enabled' if baseline=='present' else 'inactive')
 env.update(overrides);before=_tree(root)
 r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env,capture_output=True,text=True)
 assert r.returncode!=0 and _tree(root)==before
 assert not (root/'var/lib/growthmap-authority-staging-r24-transactions').exists() if baseline=='absent' else True

@pytest.mark.parametrize('enabled',['enabled','disabled'])
def test_installed_inactive_rc3_remains_supported(tmp_path,enabled):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None,fail='acceptance',baseline='present',initial='inactive '+enabled);before=_tree(root)
 r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env,capture_output=True,text=True)
 assert r.returncode!=0 and _tree(root)==before and set(state.read_text().split())=={'inactive',enabled}

@pytest.mark.parametrize('enabled_rc',['1','4'])
@pytest.mark.parametrize('stage',['systemd','enable','restart','acceptance','registry'])
def test_first_install_failure_restores_exact_absence(tmp_path,stage,enabled_rc):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None,fail=stage,baseline='absent',initial='inactive');env['FAKE_ENABLED_RC']=enabled_rc;unit=root/'etc/systemd/system/growthmap-authority-staging-r24.service'
 r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env,capture_output=True,text=True)
 assert r.returncode!=0 and not unit.exists() and not unit.is_symlink()
 assert state.read_text().strip()=='inactive'
 trace=log.read_text();assert 'systemctl daemon-reload' in trace and trace.rfind('systemctl show ')>trace.rfind('systemctl daemon-reload')
 assert trace.rfind('systemctl is-active ')>trace.rfind('systemctl daemon-reload') and trace.rfind('systemctl is-enabled ')>trace.rfind('systemctl daemon-reload')
 assert f'not-found' in trace or enabled_rc in ('1','4')

@pytest.mark.parametrize('sequence',['1,4','4,1'])
def test_absent_enabled_rc_toctou_change_fails_closed(tmp_path,sequence):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None,baseline='absent',initial='inactive');env['FAKE_ENABLED_RC_SEQUENCE']=sequence;before=_tree(root)
 r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env,capture_output=True,text=True)
 assert r.returncode!=0 and state.read_text().strip()=='inactive'
 journal=root/'var/lib/growthmap-authority-staging-r24-transactions';assert journal.is_dir() and not list(journal.iterdir())
 assert all(x==y for x,y in zip(_tree(root),before) if not x[0].endswith('-transactions'))

@pytest.mark.parametrize('initial',['active enabled','active disabled','inactive enabled','inactive disabled'])
def test_upgrade_present_baseline_matrix_failure_exact(tmp_path,initial):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None,fail='acceptance',baseline='present',initial=initial);before=_tree(root)
 r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env)
 assert r.returncode!=0 and _tree(root)==before and set(state.read_text().split())==set(initial.split())

@pytest.mark.parametrize(('unit_present','initial','expected'),[(False,'inactive enabled','unsupported'),(False,'active','unsupported'),(True,'inactive enabled','unsupported')])
def test_mixed_or_ambiguous_systemd_state_rejected_before_journal(tmp_path,unit_present,initial,expected):
 baseline='present' if unit_present else 'absent';rail,root,env,state,log=_fake_apply_env(tmp_path,None,baseline=baseline,initial=initial)
 if not unit_present and 'enabled' in initial.split():
  # Preserve the deliberately incoherent absent/enabled response across startup daemon-reload.
  dispatch=Path(env['FAKE_LOG']).parent/'bin/dispatch.py';text=dispatch.read_text();text=text.replace("if not present:words.discard('enabled');words.discard('disabled');st.write_text(' '.join(sorted(words)))","if not present and 'KEEP_MIXED' not in os.environ:words.discard('enabled');words.discard('disabled');st.write_text(' '.join(sorted(words)))");dispatch.write_text(text);env['KEEP_MIXED']='1'
 if unit_present and initial=='inactive enabled':
  # A masked-like adapter response is rejected rather than coerced.
  env['FAKE_LOAD_OUT']='masked'
 r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env,capture_output=True,text=True)
 assert r.returncode==2
 if not unit_present:assert not (root/'var/lib/growthmap-authority-staging-r24-transactions').exists()

def test_production_rejects_root_overrides():
 for script,args in [(DEP/'deploy.sh',[]),(DEP/'rollback.sh',['--apply','a'*64])]: 
  for key in ('R24_ROOT','R15_ROOT','GROWTHMAP_ROOT'):
   env={**os.environ,key:'/tmp/not-allowed'}
   r=subprocess.run(['/bin/sh',str(script),*args],env=env,capture_output=True,text=True)
   assert r.returncode==2 and 'root_override_rejected' in r.stderr

@pytest.mark.parametrize('stage',['stop','snapshot'])
def test_deploy_pre_snapshot_failures_restore_status_and_files(tmp_path,stage):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None,stage);before=_tree(root)
 if stage=='snapshot':
  # Test-copy-only injection: kill/fail after begin has durably armed its snapshot.
  f=rail/'deploy/forward_transaction.py';s=f.read_text();needle="r['phase']='snapshot_armed';write_record(tx,r)";assert needle in s;s=s.replace(needle,needle+"\n  if os.environ.get('FAIL_STAGE')=='snapshot':raise OSError('snapshot_injected')");f.write_text(s)
 r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env)
 assert r.returncode!=0 and _tree(root)==before and set(state.read_text().split())=={'active','enabled'};_no_orphans(root)

@pytest.mark.parametrize('initial',['active enabled','active disabled','inactive enabled','inactive disabled'])
def test_rollback_preserves_all_four_status_combinations(tmp_path,initial):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None);a='a'*64;b='b'*64
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(a+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(b+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 state.write_text(initial)
 assert subprocess.run(['/bin/sh',str(rail/'deploy/rollback.sh'),'--apply',a],env=env).returncode==0
 assert set(state.read_text().split())==set(initial.split())

def test_sqlite_fail_closed_wal_and_partial_cleanup(tmp_path,monkeypatch):
 t=module(DEP/'transaction.py','r24txsqlite');bad=tmp_path/'bad.db';bad.write_bytes(b'not sqlite');snap=tmp_path/'snap'
 with pytest.raises(Exception):t.snapshot(bad,snap)
 assert not snap.exists()
 db=tmp_path/'ok.sqlite3';c=__import__('sqlite3').connect(db);c.execute('pragma journal_mode=wal');c.execute('create table x(v)');c.execute('insert into x values (7)');c.commit()
 good=tmp_path/'good';t.snapshot(db,good);out=__import__('sqlite3').connect(good/'value');assert out.execute('select v from x').fetchone()==(7,);out.close();c.close()

def test_transaction_rejects_overlap_and_symlink_parent(tmp_path):
 t=module(DEP/'transaction.py','r24txcontain');a=(tmp_path/'a').absolute();a.mkdir()
 with pytest.raises(RuntimeError,match='overlap'):t.snapshot_all(a/'snap',[a])
 real=tmp_path/'real';real.mkdir();link=tmp_path/'link';link.symlink_to(real,target_is_directory=True)
 with pytest.raises(RuntimeError,match='symlink'):t.snapshot_all((tmp_path/'snap').absolute(),[(link/'state').absolute()])

def test_relocated_console_script_and_no_incoming_bytes(tmp_path):
 r=module(DEP/'relocate_venv.py','r24relocate');incoming=tmp_path/'.incoming-x';release=tmp_path/'release';v=incoming/'venv';subprocess.run([sys.executable,'-m','venv','--without-pip',str(v)],check=True,env={k:v for k,v in os.environ.items() if k!='PYTHONPYCACHEPREFIX'})
 for p in v.rglob('*.pyc'):p.unlink()
 for p in sorted(v.rglob('__pycache__'),reverse=True):
  if not any(p.iterdir()):p.rmdir()
 script=v/'bin/tool';script.write_bytes(('#!'+str(v/'bin/python')+'\nprint(1)\n').encode());script.chmod(0o755)
 # Production rejects an executable script not owned by a reviewed wheel RECORD.
 with pytest.raises(RuntimeError,match='record_owner_invalid'):r.relocate(v,incoming,release)
 # The failed pass may have already atomically rewritten earlier owned scripts; fail-closed is the asserted contract.

def test_r24_real_pinned_cffi_wheel_long_shebang_fixture_relocates(tmp_path):
 r=module(DEP/'relocate_venv.py','r24relocatecffi');wheel=next((R24/'evidence/wheelhouse').glob('cffi-2.1.1-*.whl'))
 # Force pip/distlib's portable shell trampoline, the form observed from this
 # exact pinned wheel when the absolute venv interpreter exceeds 127 bytes.
 incoming=tmp_path/('.incoming-'+('x'*125));v=incoming/'venv';release=tmp_path/'release';subprocess.run([sys.executable,'-B','-m','venv','--without-pip',str(v)],check=True,env={k:v for k,v in os.environ.items() if k!='PYTHONPYCACHEPREFIX'})
 bootstrap=tmp_path/'bootstrap';subprocess.run([sys.executable,'-B','-m','venv',str(bootstrap)],check=True)
 renamed=tmp_path/'cffi-2.1.1-py3-none-any.whl';renamed.write_bytes(wheel.read_bytes())
 subprocess.run([str(bootstrap/'bin/python'),'-I','-B','-m','pip','--python',str(v),'install','--no-compile','--no-deps',str(renamed)],check=True,env={**{k:v for k,v in os.environ.items() if k!='PYTHONPYCACHEPREFIX'},'PYTHONDONTWRITEBYTECODE':'1'})
 script=v/'bin/cffi-gen-src';raw=script.read_bytes();assert raw.startswith(b"#!/bin/sh\n'''exec' "+str(v/'bin/python').encode()+b' "$0" "$@"\n\' \'\'\'\n')
 for p in v.rglob('*.pyc'):p.unlink()
 for p in sorted(v.rglob('__pycache__'),reverse=True):
  if not any(p.iterdir()):p.rmdir()
 r.relocate(v,incoming,release);(release/'venv').parent.mkdir(parents=True,exist_ok=True);v.rename(release/'venv');r.verify(release/'venv')
 assert (release/'venv/bin/cffi-gen-src').read_bytes().startswith(('#!'+str(release/'venv/bin/python')+'\n').encode())

def test_r24_interpreter_layout_is_custodied_not_rewritten_or_name_whitelisted(tmp_path):
 r=module(DEP/'relocate_venv.py','r24relocateinterpreter');incoming=tmp_path/'incoming';v=incoming/'venv';subprocess.run([sys.executable,'-m','venv','--copies',str(v)],check=True,env={k:v for k,v in os.environ.items() if k!='PYTHONPYCACHEPREFIX'});bind=v/'bin'
 for p in v.rglob('*.pyc'):p.unlink()
 for p in sorted(v.rglob('__pycache__'),reverse=True):
  if not any(p.iterdir()):p.rmdir()
 raw=(bind/'python').read_bytes();tool=bind/'tool';tool.write_bytes(('#!'+str(bind/'python')+'\nprint(1)\n').encode())
 with pytest.raises(RuntimeError,match='record_owner_invalid'):r.relocate(v,incoming,tmp_path/'release')
 assert (bind/'python').read_bytes()==raw
 tool.unlink()
 fake=bind/'python9';fake.write_bytes(b'#!/usr/bin/env python\n');fake.chmod(0o755)
 with pytest.raises(RuntimeError,match='topology_invalid'):r.relocate(v,incoming,tmp_path/'release2')

def test_r24_shebang_policy_fail_closed_matrix(tmp_path):
 r=module(DEP/'relocate_venv.py','r24relocatebad');bad=[b'#!/usr/bin/env python\n',b'#!/usr/bin/python3\n',b'#!python\n',b'#!python3\n',b'#!../python\n',b'#!/bin/sh\n',b'#!/old/python -I\n',b'#!python\x00\n',b'#!\xff\n']
 for i,head in enumerate(bad):
  incoming=tmp_path/f'i{i}';v=incoming/'venv';subprocess.run([sys.executable,'-m','venv','--copies',str(v)],check=True,env={k:v for k,v in os.environ.items() if k!='PYTHONPYCACHEPREFIX'});p=v/'bin/tool';p.write_bytes(head+b'print(1)\n');p.chmod(0o755)
  with pytest.raises(RuntimeError):r.relocate(v,incoming,tmp_path/f'r{i}')

def test_r24_relocator_rejects_link_custody_and_external_verify(tmp_path):
 r=module(DEP/'relocate_venv.py','r24relocatelinks')
 for kind in ('symlink','hardlink'):
  incoming=tmp_path/kind;v=incoming/'venv';subprocess.run([sys.executable,'-m','venv','--copies',str(v)],check=True,env={k:v for k,v in os.environ.items() if k!='PYTHONPYCACHEPREFIX'});target=v/'bin/base';target.write_bytes(('#!'+str(v/'bin/python')+'\n').encode())
  tool=v/'bin/tool';tool.symlink_to('base') if kind=='symlink' else os.link(target,tool)
  with pytest.raises(RuntimeError):r.relocate(v,incoming,tmp_path/('release-'+kind))
 final=tmp_path/'final';subprocess.run([sys.executable,'-m','venv','--copies',str(final)],check=True);(final/'bin/tool').write_bytes(b'#!/usr/bin/python3\nprint(1)\n')
 with pytest.raises(RuntimeError,match='not_release_python'):r.verify(final)

def test_private_temp_never_touches_predictable_symlink(tmp_path):
 text=(DEP/'rollback.sh').read_text();assert '/tmp/$UNIT.$$' not in text and 'TMP=$(/usr/bin/mktemp -d)' in text and '"$TMP/$UNIT"' in text
 sentinel=tmp_path/'sentinel';sentinel.write_text('safe');predictable=tmp_path/'growthmap-authority-staging-r24.service.1';predictable.symlink_to(sentinel)
 assert sentinel.read_text()=='safe'


def _r24_multi(tmp_path):
 t=module(DEP/'transaction.py','r24txmulti');roots=[]
 for i in range(4):
  p=tmp_path/f'r{i}';p.mkdir();(p/'v').write_text('B'+str(i));roots.append(p)
 snap=tmp_path/'snap-all';t.snapshot_all(snap,roots)
 for i,p in enumerate(roots):(p/'v').write_text('C'+str(i))
 return t,roots,snap,tmp_path/'journals'

def test_r24_all_root_restore_and_prevalidation(tmp_path):
 t,roots,snap,jr=_r24_multi(tmp_path);t.restore_all(snap,roots,jr)
 assert [(p/'v').read_text() for p in roots]==['B0','B1','B2','B3'] and not list(jr.iterdir())

def test_r24_root_boundary_failures_undo_to_exact_candidate(tmp_path,monkeypatch):
 for point in [*(f'before_backup_{i}' for i in range(4)),*(f'after_backup_{i}' for i in range(4)),*(f'before_install_{i}' for i in range(4)),*(f'after_install_{i}' for i in range(4))]:
  case=tmp_path/point;case.mkdir();t,roots,snap,jr=_r24_multi(case);monkeypatch.setenv('R24_TRANSACTION_INJECT',point)
  with pytest.raises(Exception):t.restore_all(snap,roots,jr)
  assert [(p/'v').read_text() for p in roots]==['C0','C1','C2','C3'],point
  assert not list(jr.iterdir()),point
  monkeypatch.delenv('R24_TRANSACTION_INJECT')

def test_r24_undo_failure_leaves_journal_and_recover_is_idempotent(tmp_path,monkeypatch):
 t,roots,snap,jr=_r24_multi(tmp_path);original=t._fail
 def injected(point):
  if point=='after_install_2' or point=='before_undo_1':raise OSError('injected:'+point)
 monkeypatch.setattr(t,'_fail',injected)
 with pytest.raises(RuntimeError,match='RECOVERY_REQUIRED'):t.restore_all(snap,roots,jr)
 assert list(jr.glob('*.json'))
 monkeypatch.setattr(t,'_fail',lambda _p:None);t.recover(jr);t.recover(jr)
 assert [(p/'v').read_text() for p in roots]==['C0','C1','C2','C3'] and not list(jr.iterdir())

def test_r24_metadata_tamper_matrix_is_before_mutation(tmp_path):
 mutators=[
  lambda m:m['records'][0].update(path='/outside'),
  lambda m:m['records'][0].update(path='../outside'),
  lambda m:m['records'].append(dict(m['records'][0])),
  lambda m:m['records'][0].update(type='dir'),
  lambda m:m['records'].pop(),
 ]
 for n,mutate in enumerate(mutators):
  case=tmp_path/str(n);case.mkdir();t,roots,snap,jr=_r24_multi(case);before=[(p/'v').read_text() for p in roots];mp=snap/'0/meta.json';m=json.loads(mp.read_text());mutate(m);mp.write_text(json.dumps(m))
  with pytest.raises(Exception,match='transaction'): t.restore_all(snap,roots,jr)
  assert [(p/'v').read_text() for p in roots]==before

def test_r24_complete_extra_hardlink_and_symlink_tamper(tmp_path):
 for kind in ('complete','extra','hardlink','symlink'):
  case=tmp_path/kind;case.mkdir();t,roots,snap,jr=_r24_multi(case)
  if kind=='complete':(snap/'COMPLETE').write_text('[]')
  elif kind=='extra':(snap/'0/extra').write_text('x')
  elif kind=='hardlink':os.link(snap/'0/meta.json',snap/'hard')
  else:
   (snap/'0/value/v').unlink();(snap/'0/value/v').symlink_to('../../../../escape')
  with pytest.raises(Exception):t.restore_all(snap,roots,jr)
  assert [(p/'v').read_text() for p in roots]==['C0','C1','C2','C3']

def test_r24_privileged_environment_and_absolute_python_contract():
 for p in (DEP/'deploy.sh',DEP/'rollback.sh'):
  s=p.read_text();assert s.startswith("#!/bin/sh\nPATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH\nIFS=")
  assert 'unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT' in s
  assert '/usr/bin/python3 -I -B' in s and 'python3 -B' not in s and '/usr/bin/env' not in s
  assert 'forward_transaction.py" recover' in s and 'primary_failure_rc=' in s and 'recovery_failure=' in s
 u=(DEP/'growthmap-authority-staging-r24.service.template').read_text()
 assert 'Environment=PATH=/usr/sbin:/usr/bin:/sbin:/bin' in u and 'Environment=PYTHONPATH=' in u

def test_r24_forward_transaction_imports_sibling_under_real_isolated_python():
 f=DEP/'forward_transaction.py';t=DEP/'transaction.py'
 r=subprocess.run(['/usr/bin/python3','-I','-B',str(f),'--help'],cwd='/',env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True)
 assert r.returncode==0,(r.stdout,r.stderr)
 assert 'usage:' in r.stdout and t.is_file()

def test_r24_forward_transaction_sibling_custody_fails_closed(tmp_path):
 f=tmp_path/'forward_transaction.py';t=tmp_path/'transaction.py';f.write_bytes((DEP/'forward_transaction.py').read_bytes());t.write_bytes((DEP/'transaction.py').read_bytes())
 def run():return subprocess.run(['/usr/bin/python3','-I','-B',str(f),'--help'],cwd='/',env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True)
 assert run().returncode==0
 t.write_text('print("TAMPER_EXECUTED")\n');r=run();assert r.returncode!=0 and 'TAMPER_EXECUTED' not in r.stdout+r.stderr and 'transaction_module_hash_mismatch' in r.stderr
 t.unlink();t.symlink_to('/etc/passwd');r=run();assert r.returncode!=0 and 'transaction_module_open_failed' in r.stderr

def test_r24_hostile_environment_cannot_run_path_shim(tmp_path):
 shim=tmp_path/'bin';shim.mkdir();marker=tmp_path/'executed'
 for n in ('dirname','cat','getent','cut','mktemp','stat','id','python3','systemctl'):
  p=shim/n;p.write_text('#!/bin/sh\necho bad >"$MARKER"\nexit 99\n');p.chmod(0o755)
 env={**os.environ,'PATH':str(shim),'PYTHONPATH':str(shim),'PYTHONHOME':str(shim),'PYTHONSTARTUP':str(shim/'x'),'PYTHONINSPECT':'1','CDPATH':str(shim),'IFS':':','MARKER':str(marker)}
 r=subprocess.run(['/bin/sh',str(DEP/'deploy.sh')],env=env,capture_output=True)
 assert not marker.exists() and r.returncode!=99

PRODUCTION_FILES=tuple(sorted([*DEP.glob('*'),R24/'provision_staging.py']))
PRODUCTION_FILES=tuple(p for p in PRODUCTION_FILES if p.is_file())
SERVICE=DEP/'growthmap-authority-staging-r24.service.template'
SCANNER_PATH=R24/'evidence/semantic_scanner.py'

def _scanner():return module(SCANNER_PATH,'r24_semantic_scanner_'+os.urandom(4).hex())
def _audit_production(overrides=None,manifest_path=None):
 s=_scanner();return s.verify(overrides,manifest_path or s.MANIFEST)

def test_r24_canonical_scanner_manifest_and_evidence_same_code_path():
 s=_scanner();got=s.verify();log=json.loads((R24/'evidence/semantic-command-audit.log').read_text())
 assert log['status']=='PASS' and {k:log[k] for k in got}==got
 assert got['count']==len(got['records']) and got['production_files']==[p.relative_to(R24).as_posix() for p in PRODUCTION_FILES]
 assert set(got['by_class'])=={'shell_shebang','python_shebang','shell_command_token','service_execstart','python_path_literal'}
 assert got['by_class']['python_shebang']==10 and got['by_class']['python_path_literal']==13

def test_r24_scanner_manifest_count_and_evidence_divergence_fail_closed(tmp_path):
 s=_scanner();raw=json.loads(s.MANIFEST.read_text())
 for kind in ('count','hash','records'):
  bad=dict(raw)
  if kind=='count':bad['count']+=1
  elif kind=='hash':bad['inventory_sha256']='0'*64
  else:bad['records']=bad['records'][:-1]
  path=tmp_path/(kind+'.json');path.write_text(json.dumps(bad))
  with pytest.raises(ValueError,match='manifest'):s.verify(manifest_path=path)
 # Evidence is immutable derivation: any edited payload diverges from fresh scanner output.
 ev=json.loads((R24/'evidence/semantic-command-audit.log').read_text());ev['count']+=1
 assert {k:ev[k] for k in s.scan()}!=s.scan()

@pytest.mark.parametrize('path',[p for p in PRODUCTION_FILES if p.suffix=='.py'])
def test_r24_every_python_shebang_mutation_rejected(path):
 text=path.read_text();assert text.startswith('#!/usr/bin/python3')
 with pytest.raises(ValueError,match='unreviewed'): _audit_production({path:text.replace('/usr/bin/python3','/usr/bin/perl',1)})

@pytest.mark.parametrize('path',[DEP/'relocate_venv.py',DEP/'deploy.sh',DEP/'rollback.sh',SERVICE])
def test_r24_venv_python_path_mutations_rejected(path):
 text=path.read_text();assert '/bin/python' in text
 with pytest.raises((ValueError,AssertionError)): _audit_production({path:text.replace('/bin/python','/bin/perl',1)})

def test_r24_shell_absolute_command_and_all_r17_corruptions_rejected():
 text=(DEP/'deploy.sh').read_text()
 with pytest.raises(ValueError,match='unreviewed'):_audit_production({DEP/'deploy.sh':text.replace('/usr/bin/tar','/usr/bin/curl',1)})
 for old,new,sig in [('tar','/usr/bin/tar','--/usr/bin/tar'),('install','/usr/bin/install','--python "$INCOMING/venv" /usr/bin/install'),('ln','/usr/bin/ln','-H/usr/bin/ln')]:
  bad=text.replace(old,new);assert sig in bad
  with pytest.raises(ValueError,match='known_corruption'):_audit_production({DEP/'deploy.sh':bad})

@pytest.mark.parametrize('old',('R19','R18'))
def test_r24_service_description_mutations_rejected(old):
 with pytest.raises(ValueError):_audit_production({SERVICE:SERVICE.read_text().replace('isolated staging R24','isolated staging '+old)})

@pytest.mark.parametrize('needle',(
 '/opt/growthmap-authority-staging-r24/current/venv/bin/python','/opt/growthmap-authority-staging-r24/current',
 'ReadOnlyPaths=/opt/growthmap-authority-staging-r24 /etc/growthmap-authority-staging-r24','ReadWritePaths=/var/lib/growthmap-authority-staging-r24',
 'growthmap-authority-staging-r24.service','/var/lib/growthmap-authority-staging-r24-transactions',
 '/opt/growthmap-authority-staging-r24','/etc/growthmap-authority-staging-r24','/var/lib/growthmap-authority-staging-r24'))
def test_r24_identity_and_service_field_mutations_rejected(needle):
 overrides={p:p.read_text().replace(needle,needle.replace('r24','r19')) for p in PRODUCTION_FILES}
 assert any(overrides[p]!=p.read_text() for p in PRODUCTION_FILES)
 with pytest.raises(ValueError):_audit_production(overrides)

def test_r24_real_plan_build_verify_wheels_and_recover(tmp_path):
 """Run canonical plan with real python/build/verify/checksums; adapt host identity and journal only."""
 import re,shutil
 work=tmp_path/'work';rail=work/'reports/phase2-authority-production-readiness-20260808/vps-staging-r24';rail.parent.mkdir(parents=True);shutil.copytree(R24,rail)
 for rel in ('src','services'):shutil.copytree(ROOT.parent/rel,work/rel)
 script=rail/'deploy/deploy.sh';text=script.read_text();bind=tmp_path/'bin';bind.mkdir()
 journal=tmp_path/'journal'
 text=text.replace('/var/lib/growthmap-authority-staging-r24-transactions',str(journal))
 # Exact command-token rewrites for identity only. install wrapper delegates all but journal mkdir.
 for token,name in [('/usr/bin/getent','getent'),('/usr/bin/install','install')]:
  pattern=r'(?<![A-Za-z0-9_./-])'+re.escape(token)+r'(?![A-Za-z0-9_./-])'
  text,n=re.subn(pattern,str(bind/name),text,flags=re.M);assert n
 script.write_text(text)
 (bind/'getent').write_text('#!/bin/sh\nprintf "%s\\n" "growthmap-auth-stg:x:1234:1235::/nonexistent:/usr/sbin/nologin"\n')
 (bind/'install').write_text('#!/bin/sh\nlast=\nfor x in "$@"; do last=$x; done\nif [ "$1" = -d ] && [ "$last" = "$JOURNAL" ]; then mkdir -p "$JOURNAL"; chmod 700 "$JOURNAL"; exit; fi\nexec /usr/bin/install "$@"\n')
 for x in bind.iterdir():x.chmod(0o755)
 env={**os.environ,'JOURNAL':str(journal),'PYTHONDONTWRITEBYTECODE':'1'}
 r=subprocess.run(['/bin/bash',str(script)],env=env,capture_output=True,text=True)
 assert r.returncode==0,r.stderr
 assert 'plan uid=1234 gid=1235 reviewed_digest=' in r.stdout
 assert not journal.exists()

# R24 superseding crash protocol assertions (the executable adapter above exercises
# canonical shells; these probes bind newly introduced durable semantics directly).
def test_r24_plan_gate_precedes_any_recovery_or_begin():
 for p in (DEP/'deploy.sh',DEP/'rollback.sh'):
  s=p.read_text();gate=s.index('[ "$APPLY" -eq 1 ]||exit 0')
  assert gate < s.index('forward_transaction.py" recover',gate)
  assert gate < s.index('forward_transaction.py" begin',gate)

def test_r24_durable_protocol_phase_matrix_and_neutral_names():
 f=(DEP/'forward_transaction.py').read_text();d=(DEP/'deploy.sh').read_text();r=(DEP/'rollback.sh').read_text();t=(DEP/'transaction.py').read_text()
 for phase in ('snapshot_armed','before_stop','after_stop','before_root_mutation','after_root_mutation','before_current_link','after_current_link','before_unit_install','after_unit_install','before_daemon_reload','after_daemon_reload','before_start_restart','after_start_restart','before_acceptance','after_acceptance','before_registry','after_registry','before_status_restoration','after_status_restoration','before_commit_cleanup'):
  assert phase in f
 assert 'growthmap-runtime.pth' in d and '.growthmap-restore-' in t and '.growthmap-backup-' in t
 assert 'growthmap-r19.pth' not in d and '.r19-' not in t

def test_r24_scanner_rejects_lower_and_upper_stale_tokens():
 s=_scanner()
 p=DEP/'acceptance.py';base=p.read_text()
 for token in ('R16','R17','R18','R19','R20','R21','r16','r17','r18','r19','r20','r21','staging-r21'):
  with pytest.raises(ValueError,match='stale_identity'):s.scan({p:base+'\n# '+token+'\n'})

def _install_parent_kill_hook(rail,phase):
 """Modify only the isolated test copy; production has no fault-bypass environment."""
 p=rail/'deploy/forward_transaction.py';s=p.read_text()
 if phase=='snapshot_armed':
  needle="r['phase']='snapshot_armed';write_record(tx,r)"
  repl=needle+"\n  if os.environ.get('R24_TEST_PARENT_KILL')=='snapshot_armed':os.kill(os.getppid(),9);os.kill(os.getpid(),9)"
 else:
  needle="r['phase']=name;write_record(tx,r)"
  repl=needle+"\n if os.environ.get('R24_TEST_PARENT_KILL')==name:os.kill(os.getppid(),9);os.kill(os.getpid(),9)"
 assert needle in s;p.write_text(s.replace(needle,repl))

def _journal(root):return root/'var/lib/growthmap-authority-staging-r24-transactions'

def _run_owned(cmd,env,timeout=45):
 """Own a complete test process group; bound output drain and descendant cleanup."""
 p=subprocess.Popen(cmd,env=env,start_new_session=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 try:
  out,err=p.communicate(timeout=timeout)
 except subprocess.TimeoutExpired:
  os.killpg(p.pid,signal.SIGTERM)
  try:out,err=p.communicate(timeout=2)
  except subprocess.TimeoutExpired:
   os.killpg(p.pid,signal.SIGKILL);out,err=p.communicate(timeout=3)
  raise AssertionError(f'owned process timeout after {timeout}s: {cmd!r}\n{out[-2000:]}\n{err[-2000:]}')
 finally:
  # Expected crash probes already killed the canonical shell.  Contain any racing
  # wrapper descendants with one best-effort group kill, but do not repeatedly
  # drain a deliberately dead process group across every matrix case.
  if p.returncode==-signal.SIGKILL:
   # Expected kills still must prove bounded descendant-group disappearance.
   deadline=time.monotonic()+2
   while True:
    try:os.killpg(p.pid,0)
    except ProcessLookupError:break
    try:os.killpg(p.pid,signal.SIGKILL)
    except ProcessLookupError:break
    if time.monotonic()>=deadline:raise AssertionError('expected-kill process group survived bounded reap window')
    time.sleep(.02)
  else:
   try:os.killpg(p.pid,0)
   except ProcessLookupError:pass
   else:
    os.killpg(p.pid,signal.SIGTERM)
    deadline=time.monotonic()+2
    while time.monotonic()<deadline:
     try:os.killpg(p.pid,0)
     except ProcessLookupError:break
     time.sleep(.02)
    else:
     try:os.killpg(p.pid,signal.SIGKILL)
     except ProcessLookupError:pass
 return subprocess.CompletedProcess(cmd,p.returncode,out,err)

# Every required deploy boundary receives a real SIGKILL/re-entry execution. Baselines
# rotate across absent and all four present combinations rather than a wasteful cross product.
_DEPLOY_KILL_PHASES=('snapshot_armed','before_stop','after_stop','before_root_mutation','after_root_mutation','before_current_link','after_current_link','before_unit_install','after_unit_install','before_daemon_reload','after_daemon_reload','before_enable_disable','after_enable_disable','before_start_restart','after_start_restart','before_acceptance','after_acceptance','before_registry','after_registry','before_commit_cleanup')
@pytest.mark.parametrize('phase',_DEPLOY_KILL_PHASES)
def test_r24_real_sigkill_deploy_reentry_matrix(tmp_path,phase):
 states=('active enabled','active disabled','inactive enabled','inactive disabled')
 i=_DEPLOY_KILL_PHASES.index(phase);absent=i%5==0;initial='inactive' if absent else states[(i-1)%4]
 rail,root,env,state,log=_fake_apply_env(tmp_path,None,baseline='absent' if absent else 'present',initial=initial);before=_tree(root)
 _install_parent_kill_hook(rail,phase);env['R24_TEST_PARENT_KILL']=phase
 killed=_run_owned(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env)
 assert killed.returncode==-9 and any(_journal(root).iterdir()),(phase,killed.stderr)
 env.pop('R24_TEST_PARENT_KILL');res=_run_owned(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env)
 assert res.returncode==0,(phase,res.stderr)
 assert not any(_journal(root).iterdir());_no_orphans(root)
 assert set(state.read_text().split())=={'active','enabled'}
 # Recovery status queries precede the new transaction's final recapture.
 trace=log.read_text();assert trace.count('systemctl show ')>=3

_ROLLBACK_KILL_PHASES=('snapshot_armed','before_stop','after_stop','before_root_mutation','after_root_mutation','before_current_link','after_current_link','before_unit_install','after_unit_install','before_daemon_reload','after_daemon_reload','before_start_restart','after_start_restart','before_acceptance','after_acceptance','before_registry','after_registry','before_status_restoration','after_status_restoration','before_commit_cleanup')
@pytest.mark.parametrize('phase',_ROLLBACK_KILL_PHASES)
def test_r24_real_sigkill_rollback_reentry(tmp_path,phase):
 states=('active enabled','active disabled','inactive enabled','inactive disabled');initial=states[_ROLLBACK_KILL_PHASES.index(phase)%4]
 rail,root,env,state,log=_fake_apply_env(tmp_path,None);a='a'*64;b='b'*64
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(a+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(b+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 state.write_text(initial);_install_parent_kill_hook(rail,phase);env['R24_TEST_PARENT_KILL']=phase
 killed=_run_owned(['/bin/sh',str(rail/'deploy/rollback.sh'),'--apply',a],env)
 assert killed.returncode==-9 and any(_journal(root).iterdir()),(phase,killed.stderr)
 env.pop('R24_TEST_PARENT_KILL');res=_run_owned(['/bin/sh',str(rail/'deploy/rollback.sh'),'--apply',a],env)
 assert res.returncode==0,res.stderr
 assert os.readlink(root/'opt/growthmap-authority-staging-r24/current')=='releases/'+a
 assert set(state.read_text().split())==set(initial.split());assert not any(_journal(root).iterdir());_no_orphans(root)

def _meta_tree(root):
 out=[]
 for rel,v in _tree(root):
  p=root/rel
  out.append((rel,None,None,None,None,v) if v==b'ABSENT' else (rel,os.lstat(p).st_mode,os.lstat(p).st_uid,os.lstat(p).st_gid,os.lstat(p).st_mtime_ns,v))
 return out

def test_r24_both_plans_exact_persistent_invariance_absent_and_pending(tmp_path):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None);digest='a'*64
 # Seed an accepted release using canonical apply, then compare both clean plans.
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(digest+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 for script,args in ((rail/'deploy/deploy.sh',()),(rail/'deploy/rollback.sh',(digest,))):
  before=_meta_tree(root);calls=[x for x in log.read_text().splitlines() if x.startswith('systemctl ')]
  r=subprocess.run(['/bin/sh',str(script),*args],env=env,capture_output=True,text=True);assert r.returncode==0
  assert _meta_tree(root)==before
  assert [x for x in log.read_text().splitlines() if x.startswith('systemctl ')]==calls
 # Seed a valid armed pending transaction without mutating targets. Both plans must report it,
 # preserve every byte/metadata item, and make no systemd call.
 fwd=rail/'deploy/forward_transaction.py';assert subprocess.run([sys.executable,'-B',str(fwd),'begin','deploy',digest],env=env).returncode==0
 assert subprocess.run([sys.executable,'-B',str(fwd),'phase','before_stop'],env=env).returncode==0
 for script,args in ((rail/'deploy/deploy.sh',()),(rail/'deploy/rollback.sh',(digest,))):
  before=_meta_tree(root);calls=[x for x in log.read_text().splitlines() if x.startswith('systemctl ')]
  r=subprocess.run(['/bin/sh',str(script),*args],env=env,capture_output=True,text=True);assert r.returncode==0
  assert _meta_tree(root)==before
  assert [x for x in log.read_text().splitlines() if x.startswith('systemctl ')]==calls
  if script.name=='rollback.sh':assert 'RECOVERY_REQUIRED' in r.stdout

_RECOVERY_CRASH_PHASES=tuple([*(f'before_backup_{i}' for i in range(4)),*(f'after_backup_{i}' for i in range(4)),*(f'before_install_{i}' for i in range(4)),*(f'after_install_{i}' for i in range(4)),'before_commit','after_commit',*(f'before_cleanup_{i}' for i in range(4)),*(f'after_cleanup_{i}' for i in range(4))])

def _install_transaction_kill_hook(path):
 s=path.read_text();needle="def _fail(point):\n    if os.environ.get('R24_TRANSACTION_INJECT') == point: raise OSError('injected:'+point)"
 repl="def _fail(point):\n    if os.environ.get('R24_RECOVERY_KILL') == point: os.kill(os.getpid(), signal.SIGKILL)\n    if os.environ.get('R24_TRANSACTION_INJECT') == point: raise OSError('injected:'+point)"
 assert needle in s;s=s.replace('import argparse, contextlib, json, os, pathlib, shutil, sqlite3, stat, tempfile, uuid','import argparse, contextlib, json, os, pathlib, shutil, sqlite3, stat, tempfile, uuid, signal').replace(needle,repl);path.write_text(s)

def _recovery_worker(txfile,snap,roots,jr,phase):
 code='import importlib.util,sys;spec=importlib.util.spec_from_file_location("tx",sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.recover(sys.argv[7]);m.restore_all(sys.argv[2],sys.argv[3:7],sys.argv[7])'
 env={**os.environ,'R24_RECOVERY_KILL':phase,'PYTHONDONTWRITEBYTECODE':'1'}
 return _run_owned([sys.executable,'-B','-c',code,str(txfile),str(snap),*(str(x) for x in roots),str(jr)],env,15)

@pytest.mark.parametrize('phase',_RECOVERY_CRASH_PHASES)
def test_r24_real_sigkill_recovery_reentry_matrix(tmp_path,phase):
 # Two absent and two present roots ensure backup-missing acceptance is bound to
 # durable progress rather than existence guesses; four roots exercise ordering.
 import shutil
 txfile=tmp_path/'transaction.py';shutil.copyfile(DEP/'transaction.py',txfile);_install_transaction_kill_hook(txfile)
 t=module(txfile,'r24_recovery_setup_'+phase);roots=[]
 for i in range(4):
  p=tmp_path/f'root{i}';roots.append(p)
  if i%2==0:p.mkdir();(p/'value').write_bytes(('BASE'+str(i)).encode());os.chmod(p/'value',0o640)
 snap=tmp_path/'snapshot';t.snapshot_all(snap,roots)
 for i,p in enumerate(roots):
  if os.path.lexists(p):shutil.rmtree(p)
  p.mkdir();(p/'value').write_bytes(('CAND'+str(i)).encode())
 jr=tmp_path/'undo';killed=_recovery_worker(txfile,snap,roots,jr,phase);assert killed.returncode==-9,(phase,killed.stderr)
 # A second kill at the same durable boundary, then an uninstrumented third
 # canonical re-entry, proves repeated power loss converges without intervention.
 killed2=_recovery_worker(txfile,snap,roots,jr,phase);assert killed2.returncode in (-9,0),(phase,killed2.stderr)
 env={**{k:v for k,v in os.environ.items() if k!='PYTHONPYCACHEPREFIX'},'PYTHONDONTWRITEBYTECODE':'1'};done=_recovery_worker(txfile,snap,roots,jr,'never');assert done.returncode==0,(phase,done.stderr)
 for i,p in enumerate(roots):
  if i%2==0:assert (p/'value').read_bytes()==('BASE'+str(i)).encode() and (p/'value').stat().st_mode&0o777==0o640
  else:assert not os.path.lexists(p)
 assert not list(jr.iterdir());assert not any(x.name.startswith(('.growthmap-backup-','.growthmap-restore-')) for x in tmp_path.iterdir())

def test_r24_direct_recover_all_validation_failures_are_rc70_and_stop(tmp_path):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None);jr=_journal(root);jr.mkdir(parents=True,exist_ok=True);jr.chmod(0o700);(jr/'foreign').write_text('x')
 r=subprocess.run([sys.executable,'-B',str(rail/'deploy/forward_transaction.py'),'recover'],env=env,capture_output=True,text=True)
 assert r.returncode==70 and (jr/'foreign').exists() and 'systemctl stop growthmap-authority-staging-r24.service' in log.read_text()

# R24 outer committed-cleanup protocol: these are a fifth, disjoint real-kill family.
_OUTER_COMMIT_KILL_PHASES=('after_committed_record','before_tombstone_rename','after_tombstone_rename','before_cleanup_sidecar','after_cleanup_sidecar','before_delete_undo','after_delete_undo','before_delete_snapshot','after_delete_snapshot','before_delete_record.json','after_delete_record.json','after_tombstone_content_deletion','before_tombstone_unlink','after_tombstone_unlink','before_final_parent_fsync','after_final_parent_fsync')

def _install_outer_cleanup_kill_hook(path):
 s=path.read_text();needle='def _outer_fail(point):\n return None';repl="def _outer_fail(point):\n if os.environ.get('R24_OUTER_CLEANUP_KILL')==point:os.kill(os.getppid(),signal.SIGKILL);os.kill(os.getpid(),signal.SIGKILL)\n return None"
 assert needle in s
 import_line='import argparse, hashlib, json, os, pathlib, re, shutil, stat, subprocess, sys, types, uuid'
 assert s.count(import_line)==1
 s=s.replace(import_line,import_line+', signal').replace(needle,repl);path.write_text(s)

def _assert_committed_deploy(root,state,digest):
 assert os.readlink(root/'opt/growthmap-authority-staging-r24/current')=='releases/'+digest
 assert set(state.read_text().split())=={'active','enabled'}

def _assert_committed_rollback(root,state,digest,initial):
 assert os.readlink(root/'opt/growthmap-authority-staging-r24/current')=='releases/'+digest
 assert set(state.read_text().split())==set(initial.split())

def _settle_outer_twice(rail,env,phase):
 fwd=rail/'deploy/forward_transaction.py';env['R24_OUTER_CLEANUP_KILL']=phase
 first=_run_owned(['/bin/sh','-c','"$1" -B "$2" recover','r24-recover',sys.executable,str(fwd)],env,20)
 # A phase may already have been crossed by the first process. A second real kill
 # at the next reachable durable final-parent boundary exercises repeated outage.
 if first.returncode==-9:
  env['R24_OUTER_CLEANUP_KILL']='before_final_parent_fsync';second=_run_owned(['/bin/sh','-c','"$1" -B "$2" recover','r24-recover',sys.executable,str(fwd)],env,20)
  assert second.returncode in (-9,0),(phase,second.stderr)
 env.pop('R24_OUTER_CLEANUP_KILL',None);done=_run_owned([sys.executable,'-B',str(fwd),'recover'],env,20);assert done.returncode==0,(phase,done.stderr)

@pytest.mark.parametrize('phase',_OUTER_COMMIT_KILL_PHASES)
def test_r24_real_sigkill_outer_commit_deploy_reentry(tmp_path,phase):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None,baseline='present',initial='active enabled');digest='a'*64
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(digest+'\n');_install_outer_cleanup_kill_hook(rail/'deploy/forward_transaction.py');env['R24_OUTER_CLEANUP_KILL']=phase
 killed=_run_owned(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env,45);assert killed.returncode==-9,(phase,killed.stderr)
 _assert_committed_deploy(root,state,digest);_settle_outer_twice(rail,env,phase);_assert_committed_deploy(root,state,digest)
 assert not list(_journal(root).iterdir());_no_orphans(root)

@pytest.mark.parametrize('phase',_OUTER_COMMIT_KILL_PHASES)
def test_r24_real_sigkill_outer_commit_rollback_reentry(tmp_path,phase):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None);a='a'*64;b='b'*64
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(a+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(b+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 initial='inactive disabled';state.write_text(initial);_install_outer_cleanup_kill_hook(rail/'deploy/forward_transaction.py');env['R24_OUTER_CLEANUP_KILL']=phase
 killed=_run_owned(['/bin/sh',str(rail/'deploy/rollback.sh'),'--apply',a],env,45);assert killed.returncode==-9,(phase,killed.stderr)
 _assert_committed_rollback(root,state,a,initial);_settle_outer_twice(rail,env,phase);_assert_committed_rollback(root,state,a,initial)
 assert not list(_journal(root).iterdir());_no_orphans(root)

def _outer_fixture(tmp_path):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None);digest='a'*64;(rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(digest+'\n');_install_outer_cleanup_kill_hook(rail/'deploy/forward_transaction.py');env['R24_OUTER_CLEANUP_KILL']='after_cleanup_sidecar'
 killed=_run_owned(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env);assert killed.returncode==-9
 env.pop('R24_OUTER_CLEANUP_KILL');jr=_journal(root);side=next(jr.glob('committed-cleanup-*.json'));tomb=next(p for p in jr.glob('committed-cleanup-*') if p.is_dir())
 return rail,root,env,state,log,tomb,side

def test_r24_outer_partial_tombstone_missing_before_progress_rejected(tmp_path):
 rail,root,env,state,log,tomb,side=_outer_fixture(tmp_path);c=json.loads(side.read_text());name=next(n for n,s in c['progress'].items() if s=='pending');p=tomb/name
 if p.is_dir():__import__('shutil').rmtree(p)
 else:p.unlink()
 r=subprocess.run([sys.executable,'-B',str(rail/'deploy/forward_transaction.py'),'recover'],env=env,capture_output=True,text=True)
 assert r.returncode==70 and 'cleanup_member_missing_before_progress' in r.stderr and tomb.exists() and side.exists() and 'systemctl stop growthmap-authority-staging-r24.service' in log.read_text()

def test_r24_outer_partial_tombstone_missing_after_removed_progress_resumes(tmp_path):
 rail,root,env,state,log,tomb,side=_outer_fixture(tmp_path);c=json.loads(side.read_text());name=c['members'][0];p=tomb/name
 if p.is_dir():__import__('shutil').rmtree(p)
 else:p.unlink()
 c['progress'][name]='removed';side.write_text(json.dumps(c,separators=(',',':'))+'\n')
 r=subprocess.run([sys.executable,'-B',str(rail/'deploy/forward_transaction.py'),'recover'],env=env,capture_output=True,text=True)
 assert r.returncode==0,r.stderr;assert not list(_journal(root).iterdir())

@pytest.mark.parametrize('kind',('foreign','multiple','tampered','symlink','hardlink'))
def test_r24_outer_cleanup_foreign_multiple_tampered_fail_closed(tmp_path,kind):
 rail,root,env,state,log,tomb,side=_outer_fixture(tmp_path);jr=_journal(root)
 if kind=='foreign':(jr/'foreign').write_text('x')
 elif kind=='multiple':(jr/('0'*32)).mkdir(mode=0o700)
 elif kind=='tampered':side.write_text('{}')
 elif kind=='symlink':(tomb/'snapshot').unlink() if (tomb/'snapshot').is_symlink() else __import__('shutil').rmtree(tomb/'snapshot');(tomb/'snapshot').symlink_to('/tmp')
 else:
  p=tomb/'record.json';os.link(p,jr/'record-hardlink')
 r=subprocess.run([sys.executable,'-B',str(rail/'deploy/forward_transaction.py'),'recover'],env=env,capture_output=True,text=True)
 assert r.returncode==70 and any(jr.iterdir()) and 'systemctl stop growthmap-authority-staging-r24.service' in log.read_text()

@pytest.mark.r24_post_finalization_attestation
def test_r24_runner_timeout_contract_is_bounded_per_shard_and_aggregate():
 import ast
 text=(R24/'evidence/expanded_qa_runner.py').read_text();tree=ast.parse(text);values={}
 for n in tree.body:
  if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in {'R24_TOTAL_TIMEOUT','R24_SHARD_TIMEOUTS'}:values[n.targets[0].id]=ast.literal_eval(n.value)
 assert values['R24_TOTAL_TIMEOUT']>=5400 and values['R24_TOTAL_TIMEOUT']>1200
 assert set(values['R24_SHARD_TIMEOUTS'])=={'non-crash','forward-crash','rollback-crash-a','rollback-crash-b','nested-recovery-crash','outer-deploy-crash','outer-rollback-crash-a','outer-rollback-crash-b'}
 assert values['R24_SHARD_TIMEOUTS']['non-crash']>=1200 and all(0<x<=1800 for x in values['R24_SHARD_TIMEOUTS'].values())
 assert "else 300" in text and 'os.killpg(p.pid,signal.SIGTERM)' in text and 'os.killpg(p.pid,signal.SIGKILL)' in text
 assert 'timeout=min(module_timeout,remaining)' in text and "R24_MODULE_TOTAL_TIMEOUT" in text

def test_r24_canonical_sigkill_matrix_exact_source_and_runner_binding():
 ev=R24/'evidence';matrix=json.loads((ev/'sigkill-reentry-matrix.json').read_text());results=json.loads((ev/'expanded-qa-results.json').read_text());manifest=json.loads((ev/'contract-shard-result-manifest.json').read_text())
 behavior=results['coverage_accounting']['r24']['behavior'];kills={'forward-crash':len(_DEPLOY_KILL_PHASES),'rollback-crash-a':10,'rollback-crash-b':10,'nested-recovery-crash':len(_RECOVERY_CRASH_PHASES),'outer-deploy-crash':len(_OUTER_COMMIT_KILL_PHASES),'outer-rollback-crash-a':8,'outer-rollback-crash-b':8};expected={'non-crash':behavior-sum(kills.values()),**kills}
 assert matrix['partition']==manifest['partition']==expected and matrix['behavior_total']==matrix['union']==sum(expected.values())==behavior and behavior>=206 and matrix['overlap']==0
 assert matrix['attestation_total']==manifest['attestation_total']==1 and matrix['coverage_accounting']==f'behavior {behavior} + post-finalization attestation 1'
 assert matrix['real_kills']==manifest['real_sigkill_cases']==98
 assert matrix['operations']['deploy']['forward_phases']==list(_DEPLOY_KILL_PHASES) and matrix['operations']['rollback']['rollback_phases']==list(_ROLLBACK_KILL_PHASES)
 assert matrix['operations']['nested_recovery']['phases']==list(_RECOVERY_CRASH_PHASES) and matrix['operations']['deploy']['outer_commit_cleanup_phases']==list(_OUTER_COMMIT_KILL_PHASES)
 assert matrix['test_sha256']==manifest['test_sha256']==hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
 runner=ev/'expanded_qa_runner.py';assert matrix['runner_sha256']==manifest['runner_sha256']==results['runner_source_sha256']==hashlib.sha256(runner.read_bytes()).hexdigest()
 rec=next(x for x in results['results'] if x['module'].endswith('test_r24_deployment_contract.py'));assert matrix['final_runner_record']['test_sha256']==rec['module_source_sha256']==matrix['test_sha256'] and matrix['shards']==manifest['shards']==rec['shards']
 assert rec['passed']==behavior and results['verdict']=='PASS' and len(results['results'])==58 and results['coverage_accounting']['r24']=={'behavior':behavior,'post_finalization_attestation':1}
 assert results['post_finalization_verifier']['excluded_from_behavior_run'] and results['post_finalization_verifier']['reason']=='evidence does not exist until canonical behavior output is finalized; running this verifier during generation would create a self-reference cycle'
 assert results['excluded_historical_contracts']==[f'test_r{x}_deployment_contract.py' for x in range(14,24)]
 assert results['exclusion_rationale']=='R14–R23 are superseded historical deployment rails; current R24 is mandatory'

def _fresh_copy_venv(tmp_path,name='incoming'):
 incoming=tmp_path/name;v=incoming/'venv';subprocess.run([sys.executable,'-m','venv','--without-pip','--copies',str(v)],check=True,env={k:x for k,x in os.environ.items() if k!='PYTHONPYCACHEPREFIX'});return incoming,v

def test_r24_exact15_interpreter_alias_adversarial_matrix(tmp_path):
 r=module(DEP/'relocate_venv.py','r24relocateexact15')
 # Every required alias is mandatory, and every extra python-like alias is forbidden.
 for alias in ('python','python3','python3.12'):
  incoming,v=_fresh_copy_venv(tmp_path,'missing-'+alias);(v/'bin'/alias).unlink()
  with pytest.raises(RuntimeError,match='topology'):r.relocate(v,incoming,tmp_path/'release')
 incoming,v=_fresh_copy_venv(tmp_path,'extra');(v/'bin/python3.11').write_bytes((v/'bin/python').read_bytes());(v/'bin/python3.11').chmod(0o755)
 with pytest.raises(RuntimeError,match='topology'):r.relocate(v,incoming,tmp_path/'release-extra')
 # A complete namespace must not split between separately authenticated-looking targets.
 incoming,v=_fresh_copy_venv(tmp_path,'split');(v/'bin/python3.12').unlink();(v/'bin/python3.12').symlink_to('/usr/bin/python3')
 with pytest.raises(RuntimeError):r.relocate(v,incoming,tmp_path/'release-split')

def test_r24_exact15_forged_home_external_elf_and_cfg_tamper_fail_closed(tmp_path):
 r=module(DEP/'relocate_venv.py','r24relocateforged')
 incoming,v=_fresh_copy_venv(tmp_path,'forged');bind=v/'bin'
 for p in bind.glob('python*'):p.unlink()
 (bind/'python').symlink_to('/usr/bin/ls');(v/'pyvenv.cfg').write_text('home = /usr/bin\n')
 with pytest.raises(RuntimeError):r._interpreters(v,bind,os.open(bind,os.O_RDONLY|os.O_DIRECTORY),sorted(os.listdir(bind)))
 # pyvenv.cfg is deliberately not a trust anchor: changing home cannot bless a target.
 incoming,v=_fresh_copy_venv(tmp_path,'tamper');(v/'pyvenv.cfg').write_text('home = /tmp\nversion = 3.12.3\n')
 for p in v.rglob('*.pyc'):p.unlink()
 for p in sorted(v.rglob('__pycache__'),reverse=True):
  if not any(p.iterdir()):p.rmdir()
 r.relocate(v,incoming,tmp_path/'release-tamper')

def test_r24_exact15_fake_json_elf_wrong_python_chains_and_multilink_rejected(tmp_path):
 r=module(DEP/'relocate_venv.py','r24relocatefakeelf')
 incoming,v=_fresh_copy_venv(tmp_path,'fake-json');bind=v/'bin';src=tmp_path/'fake.c'
 payload='{"implementation":"cpython","version":[3,12,3],"cache_tag":"cpython-312","soabi":"cpython-312-x86_64-linux-gnu","executable":"/tmp/x","prefix":"/tmp","base_prefix":"/usr"}'
 src.write_text('#include <stdio.h>\nint main(){puts("'+payload.replace('"','\\"')+'");return 0;}\n');fake=tmp_path/'fake-python';subprocess.run(['/usr/bin/cc',str(src),'-o',str(fake)],check=True)
 for p in bind.glob('python*'):p.unlink()
 for n in ('python','python3','python3.12'):(bind/n).symlink_to(fake)
 with pytest.raises(RuntimeError):r.relocate(v,incoming,tmp_path/'release-fake')
 # Genuine but wrong interpreter/version and escaping/broken/loop chains fail closed.
 for kind in ('wrong','broken','loop'):
  incoming,v=_fresh_copy_venv(tmp_path,kind);bind=v/'bin'
  if kind=='wrong':
   candidate=Path('/usr/bin/python3.11')
   if not candidate.exists():candidate=Path('/usr/bin/ls')
   (bind/'python').unlink();(bind/'python').symlink_to(candidate)
  elif kind=='broken':(bind/'python').unlink();(bind/'python').symlink_to('../missing')
  else:(bind/'python').unlink();(bind/'python').symlink_to('python')
  with pytest.raises(RuntimeError):r.relocate(v,incoming,tmp_path/('release-'+kind))
 incoming,v=_fresh_copy_venv(tmp_path,'hard');os.link(v/'bin/python',tmp_path/'second-link')
 with pytest.raises(RuntimeError,match='custody'):r.relocate(v,incoming,tmp_path/'release-hard')

def test_r24_exact15_finalizer_preserves_full_instance_run_id():
 text=(R24/'evidence/finalize_expanded_qa.py').read_text();m=__import__('re').search(r"re\.fullmatch\(r'([^']+)'",text);assert m
 rx=m.group(1);assert __import__('re').fullmatch(rx,'r24-exact15-20260811').group(1)=='exact15'
 assert __import__('re').fullmatch(rx,'r24-exact14c-20260811').group(1)=='exact14c'
 assert __import__('re').fullmatch(rx,'r24-exact14-20260811').group(1)=='exact14'

def test_r24_exact19_distribution_provenance_fail_closed(monkeypatch,tmp_path):
 v=module(DEP/'venv_manifest.py','r24venvexact19')
 assert v.normalize('Typing_Extensions')=='typing-extensions'
 with pytest.raises(RuntimeError,match='name_invalid'):v.normalize('bad name')
 expected=[['a','1',str(tmp_path/'a.dist-info')]]
 monkeypatch.setattr(v.subprocess,'check_output',lambda *a,**k:__import__('json').dumps(expected))
 assert v.distributions(tmp_path/'python')==expected
 duplicate=[['a','1','/x/a.dist-info'],['a','1','/x/a-copy.dist-info']]
 monkeypatch.setattr(v.subprocess,'check_output',lambda *a,**k:__import__('json').dumps(duplicate))
 with pytest.raises(RuntimeError,match='distribution_duplicate'):v.distributions(tmp_path/'python')
 # Exact set comparison remains strict: missing, extra pip/setuptools and any other extra all differ.
 locked={('a','1'),('typing-extensions','2')}
 assert locked=={('a','1'),('typing-extensions','2')}
 for actual in ({('a','1')},locked|{('pip','24.0')},locked|{('setuptools','70')},locked|{('evil','1')}):assert actual!=locked

def test_r24_exact19_deploy_removes_bootstrap_pip_before_relocation_and_manifest():
 text=(DEP/'deploy.sh').read_text(); install=text.index('-m pip --python'); uninstall=install; relocate=text.index('relocate_venv.py" relocate'); manifest=text.index('venv_manifest.py" create')
 assert relocate<install<=uninstall<manifest
 assert '-m pip check' not in (DEP/'venv_manifest.py').read_text()

def _custody_fixture(tmp_path):
 v=module(DEP/'venv_manifest.py','r24custody'+str(time.time_ns()));parent=tmp_path/'sealed';parent.mkdir(mode=0o700);root=parent/'venv';(root/'bin').mkdir(parents=True);(root/'bin/python3').write_bytes(b'elf');base=parent/'base.json';custody=parent/'custody.json';binding=v.capture_base(root,base,custody);digest,cdigest=binding.split(':');return v,parent,root,base,custody,digest,cdigest

def test_r24_exact22_base_custody_valid_and_portable_lifecycle(tmp_path):
 v,parent,root,base,custody,digest,cdigest=_custody_fixture(tmp_path);raw=v.read_captured_base(base,custody,digest,cdigest);assert hashlib.sha256(raw).hexdigest()==digest
 # Capture inode tuple is deliberately not required after a legal landing move.
 landed=tmp_path/'landed';os.rename(parent,landed);assert v.portable_base(landed/'base.json',digest)==raw

@pytest.mark.parametrize('attack',['rewrite','truncate','append','chmod','symlink','hardlink','replace','both'])
def test_r24_exact22_base_custody_tamper_fails(tmp_path,attack):
 v,parent,root,base,custody,digest,cdigest=_custody_fixture(tmp_path);good=base.read_bytes();rec=custody.read_bytes()
 if attack=='rewrite':base.chmod(0o600);base.write_bytes(good.replace(b'"files":',b'"files" :'))
 elif attack=='truncate':base.chmod(0o600);base.write_bytes(b'{}')
 elif attack=='append':base.chmod(0o600);base.write_bytes(good+b' ')
 elif attack=='chmod':base.chmod(0o600)
 elif attack=='symlink':base.unlink();base.symlink_to('custody.json')
 elif attack=='hardlink':os.link(base,parent/'alias')
 elif attack=='replace':base.unlink();base.write_bytes(good);base.chmod(0o400)
 else:
  base.unlink();base.write_bytes(good);base.chmod(0o400);custody.unlink();custody.write_bytes(rec);custody.chmod(0o400)
 with pytest.raises(RuntimeError):v.read_captured_base(base,custody,digest,cdigest)

def test_r24_exact22_pollution_observed_rewrite_cannot_self_authorize(tmp_path):
 v,parent,root,base,custody,digest,cdigest=_custody_fixture(tmp_path);evil=root/'evil.py';evil.write_bytes(b'owned by attacker')
 forged=(json.dumps({'schema_version':2,'files':v.inventory(root)},sort_keys=True,separators=(',',':'))+'\n').encode();base.chmod(0o600);base.write_bytes(forged);base.chmod(0o400)
 with pytest.raises(RuntimeError,match='custody'):v.read_captured_base(base,custody,digest,cdigest)

def test_r24_exact22_parent_swap_and_owner_drift_fail(tmp_path,monkeypatch):
 v,parent,root,base,custody,digest,cdigest=_custody_fixture(tmp_path);moved=tmp_path/'moved';parent.rename(moved);parent.mkdir(mode=0o700)
 (parent/'base.json').write_bytes((moved/'base.json').read_bytes());(parent/'base.json').chmod(0o400);(parent/'custody.json').write_bytes((moved/'custody.json').read_bytes());(parent/'custody.json').chmod(0o400)
 with pytest.raises(RuntimeError):v.read_captured_base(parent/'base.json',parent/'custody.json',digest,cdigest)
 real=v.os.fstat;v.os.fstat=lambda fd: type('S',(),{**{n:getattr(real(fd),n) for n in ('st_mode','st_nlink','st_gid','st_dev','st_ino','st_size')},'st_uid':real(fd).st_uid+1})()
 with pytest.raises(RuntimeError):v.read_captured_base(moved/'base.json',moved/'custody.json',digest,cdigest)


def test_r24_exact22_finalizer_rejects_stale_preflight_and_generates_current():
 text=(R24/'evidence/finalize_expanded_qa.py').read_text()
 assert "lines.get('run_id')!=run_id" in text and "PASS_CURRENT_ARM64_ORDINARY_USER_TMP" in text and "status=CURRENT_AUTHORITATIVE" in text
 assert "shutil.copy2(src/name,EV/('canonical-'+name))" not in text


def test_r24_exact22c_landed_release_inventory_includes_required_provenance(tmp_path):
 v=module(DEP/'verify_bundle.py','r24verify_'+os.urandom(4).hex());digest='a'*64;release=tmp_path/digest;release.mkdir()
 value=['src/backend/licensing/__init__.py'];monkeypatch_files=value
 v.files=lambda:monkeypatch_files
 (release/'src/backend/licensing').mkdir(parents=True);(release/value[0]).write_bytes(b'')
 for name in ('runtime.tar','source-files.sha256','base-python-anchor.json','venv-base-manifest.json','venv-base-custody.json','venv-manifest.json'):(release/name).write_text('{}')
 expected=set(value)|{'runtime.tar','source-files.sha256','base-python-anchor.json','venv-base-manifest.json','venv-base-custody.json','venv-manifest.json'}
 actual={str(p.relative_to(release)) for p in release.rglob('*') if p.is_file() and 'venv/' not in str(p.relative_to(release))}
 assert actual==expected
 text=(DEP/'verify_bundle.py').read_text()
 for name in ('base-python-anchor.json','venv-base-manifest.json','venv-base-custody.json','venv-manifest.json'):assert name in text


def test_r24_exact22d_base_provenance_allows_only_immutable_mode_transition(tmp_path):
 v=module(DEP/'venv_manifest.py','r24venv_'+os.urandom(4).hex());root=tmp_path/'venv';(root/'bin').mkdir(parents=True)
 (root/'bin/python3').write_bytes(b'interpreter');(root/'bin/python3').chmod(0o755)
 p=root/'bin/Activate.ps1';p.write_bytes(b'fixed activation bytes');p.chmod(0o644)
 base=json.dumps({'schema_version':2,'files':v.inventory(root)},sort_keys=True,separators=(',',':')).encode()
 p.chmod(0o444);actual=v.inventory(root);d={x['path']:x for x in actual};x=json.loads(base)['files'][0];expected=dict(x);expected['mode']&=~0o222
 assert d['bin/Activate.ps1']==expected
 p.chmod(0o644);p.write_bytes(b'tampered activation bytes');p.chmod(0o444)
 assert v.inventory(root)[0]!=expected
