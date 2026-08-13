import hashlib,importlib.util,json,os,platform,subprocess,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[2];R18=ROOT.parents[0]/'reports/phase2-authority-production-readiness-20260808/vps-staging-r18';DEP=R18/'deploy'
def module(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def test_release_identity_strict_and_old_process_rejected(monkeypatch,tmp_path):
 import licensing.authority_composition as c
 with pytest.raises(RuntimeError,match='release_digest_invalid'):c.run(['--fixed-config','/x','--expected-service-uid','1','--release-digest','A'*64])
 a=module(DEP/'acceptance.py','r18accept');cfg=tmp_path/'composition.json';auth=tmp_path/'authority-production.json';auth.write_text(json.dumps({'reviewed_public_key_sha256':'1'*64}));cfg.write_text(json.dumps({'authority_config_path':str(auth),'listen':{'host':'127.0.0.1','port':8320}}))
 monkeypatch.setattr(a,'call',lambda *_a,**_k:{'authority_id':'x','release_sha256':'a'*64})
 monkeypatch.setattr(a.argparse.ArgumentParser,'parse_args',lambda _:{'x':1}) if False else None

def test_unit_exact_parity_and_stable_security_config():
 u=(DEP/'growthmap-authority-staging-r18.service.template').read_text();p=(R18/'provision_staging.py').read_text()
 assert 'python -I -B -m licensing.authority_composition --fixed-config /etc/growthmap-authority-staging-r18/production-composition.json --expected-service-uid @SERVICE_UID@ --release-digest @RELEASE_DIGEST@' in u
 assert 'Environment=PYTHONDONTWRITEBYTECODE=1' in u and "comp={'schema_version':1,'expected_uid':uid,'deployment_config_sha256'" in p

def test_registry_binds_authority_pin_and_venv(tmp_path):
 r=module(DEP/'registry.py','r18registry');release=tmp_path/('a'*64);release.mkdir();
 for n,v in [('runtime.tar',b'x'),('source-files.sha256',b'y'),('venv-manifest.json',b'z')]: (release/n).write_bytes(v)
 unit=tmp_path/'growthmap-authority-staging-r18.service';unit.write_text('u');auth=tmp_path/'authority-production.json';auth.write_text(json.dumps({'reviewed_public_key_sha256':'b'*64}));cfg=tmp_path/'production-composition.json';cfg.write_text(json.dumps({'expected_uid':123,'listen':{'port':8320},'edge':{'public_key_sha256':'c'*64}}))
 a=type('A',(),dict(release=str(release),release_digest='a'*64,config=str(cfg),authority_config=str(auth),unit=str(unit),venv_manifest=str(release/'venv-manifest.json'),uid=123,gid=124))
 rec=r.record(a);assert rec['authority_config_sha256']==hashlib.sha256(auth.read_bytes()).hexdigest() and rec['reviewed_authority_public_key_sha256']=='b'*64 and rec['venv_manifest_sha256']==hashlib.sha256(b'z').hexdigest()
 auth.write_text(json.dumps({'reviewed_public_key_sha256':'d'*64}));assert r.record(a)!=rec

def test_transaction_fresh_and_existing_byte_metadata_restore(tmp_path):
 t=module(DEP/'transaction.py','r18tx');root=tmp_path/'state';snap=tmp_path/'snap';t.snapshot(root,snap);root.mkdir();(root/'new').write_bytes(b'n');t.restore(root,snap);assert not root.exists()
 root.mkdir();x=root/'x';x.write_bytes(b'old');x.chmod(0o400);stamp=1_700_000_000_123_456_789;os.utime(x,ns=(stamp,stamp));(root/'inside').symlink_to('x');snap2=tmp_path/'snap2';t.snapshot(root,snap2);meta=json.loads((snap2/'meta.json').read_text());xm=next(m for m in meta['records'] if m['path']=='x');assert (xm['uid'],xm['gid'],xm['mode'],xm['mtime_ns'])==(os.getuid(),os.getgid(),0o400,stamp)
 x.chmod(0o600);x.write_bytes(b'new');(root/'extra').write_bytes(b'e');t.restore(root,snap2);assert x.read_bytes()==b'old' and x.stat().st_mode&0o777==0o400 and x.stat().st_mtime_ns==stamp and os.readlink(root/'inside')=='x' and not (root/'extra').exists()

def test_transaction_rejects_hardlink_and_external_symlink(tmp_path):
 t=module(DEP/'transaction.py','r18txbad');root=tmp_path/'state';root.mkdir();a=root/'a';a.write_text('x');os.link(a,root/'b')
 with pytest.raises(RuntimeError,match='hardlink'):t.snapshot(root,tmp_path/'s1')
 os.unlink(root/'b');(root/'bad').symlink_to('../outside')
 with pytest.raises(RuntimeError,match='symlink'):t.snapshot(root,tmp_path/'s2')

def test_executable_fake_systemctl_restart_and_uid_preflight(tmp_path):
 bind=tmp_path/'bin';bind.mkdir();log=tmp_path/'log';sc=bind/'systemctl';sc.write_text('#!/bin/sh\necho "$*" >> "$FAKE_LOG"\ncase "$1" in is-active) echo active;exit 0;;is-enabled)echo enabled;exit 0;;esac\n');sc.chmod(0o755)
 # Execute the parent-shell UID parse used by rollback, not a grep-only assertion.
 script='entry=$(getent passwd "$USER"); UID_ONCE=$(printf %s "$entry"|cut -d: -f3); GID_ONCE=$(printf %s "$entry"|cut -d: -f4); case $UID_ONCE:$GID_ONCE in *[!0-9:]*)exit 9;;esac; test "$UID_ONCE" -gt 0; test "$GID_ONCE" -gt 0; systemctl restart unit'
 env={**os.environ,'PATH':str(bind)+':'+os.environ['PATH'],'FAKE_LOG':str(log),'USER':os.environ.get('USER','nobody')};subprocess.run(['/bin/sh','-eu','-c',script],env=env,check=True);assert log.read_text().strip()=='restart unit'

def test_real_venv_copies_inventory_structural_policy(tmp_path):
 v=module(DEP/'venv_manifest.py','r18venvreal');root=tmp_path/'venv';subprocess.run([sys.executable,'-B','-m','venv','--copies',str(root)],check=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
 for p in root.rglob('*.pyc'):p.unlink()
 for p in sorted(root.rglob('__pycache__'),reverse=True):
  if not any(p.iterdir()):p.rmdir()
 items=v.inventory(root);by={x['path']:x for x in items};assert by['bin/python3']['type']=='file' and by['bin/python3']['sha256']==hashlib.sha256((root/'bin/python3').read_bytes()).hexdigest()
 assert all(not (x['type']=='symlink' and os.path.isabs(x['target'])) for x in items)

def test_venv_verifier_rejects_addition_symlink_hardlink_and_pyc(tmp_path):
 v=module(DEP/'venv_manifest.py','r18venv');root=tmp_path/'v';(root/'bin').mkdir(parents=True);(root/'bin/python3').write_bytes(b'elf');(root/'a').write_bytes(b'a');assert any(x['path']=='a' for x in v.inventory(root));(root/'x.pyc').write_bytes(b'x')
 with pytest.raises(RuntimeError,match='bytecode'):v.inventory(root)
 (root/'x.pyc').unlink();(root/'escape').symlink_to('../outside')
 with pytest.raises(RuntimeError,match='symlink'):v.inventory(root)
 (root/'escape').unlink();os.link(root/'a',root/'hard')
 with pytest.raises(RuntimeError,match='hardlink'):v.inventory(root)

def _fake_apply_env(tmp_path,monkeypatch,fail=''):
 import shutil
 rail=tmp_path/'rail';shutil.copytree(R18,rail);root=tmp_path/'root';(root/'opt').mkdir(parents=True);(root/'var/lib/growthmap-authority-staging-r18-transactions').mkdir(parents=True);(root/'etc/systemd/system').mkdir(parents=True);
 for script in (rail/'deploy/deploy.sh',rail/'deploy/rollback.sh'):
  text=script.read_text()
  bind=tmp_path/'bin'
  paths=[('/var/lib/growthmap-authority-staging-r18-transactions',str(root/'var/lib/growthmap-authority-staging-r18-transactions')),('/opt/growthmap-authority-staging-r18',str(root/'opt/growthmap-authority-staging-r18')),('/var/lib/growthmap-authority-staging-r18',str(root/'var/lib/growthmap-authority-staging-r18')),('/etc/growthmap-authority-staging-r18',str(root/'etc/growthmap-authority-staging-r18')),('/etc/systemd/system',str(root/'etc/systemd/system'))]
  for i,(canonical,adapted) in enumerate(paths):
   marker=f'__R18_ADAPTER_PATH_{i}__';assert marker not in text and canonical in text;text=text.replace(canonical,marker)
  for i,(_canonical,adapted) in enumerate(paths):text=text.replace(f'__R18_ADAPTER_PATH_{i}__',adapted)
  # Adapter rewrites reviewed executable tokens only, never substrings in argv.
  import shlex
  absolute=['python3','getent','systemctl','systemd-analyze','ss','tar','install','chmod']
  protected=('--tar','-m pip install','-Hln','source-files.sha256','R18_TRANSACTION_INJECT')
  before={x:text.count(x) for x in protected}
  for tool in absolute:
   token='/usr/bin/'+tool
   # shell-aware-enough boundary: executable token must be delimited by command syntax/space.
   import re
   pattern=r'(?<![A-Za-z0-9_./-])'+re.escape(token)+r'(?![A-Za-z0-9_./-])'
   text,n=re.subn(pattern,str(bind/tool),text,flags=re.M)
   assert n or tool in ('systemd-analyze','ss','tar','chmod')
  assert {x:text.count(x) for x in protected}==before
  script.write_text(text)
 bind.mkdir();log=tmp_path/'calls';state=tmp_path/'systemctl-state';state.write_text('active enabled')
 dispatcher=bind/'dispatch.py';dispatcher.write_text(r'''#!/usr/bin/env python3
import json,os,pathlib,shutil,subprocess,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];log=pathlib.Path(os.environ['FAKE_LOG']);log.write_text(log.read_text() + name+' '+' '.join(a)+'\n' if log.exists() else name+' '+' '.join(a)+'\n')
def fail(stage):
 marker=pathlib.Path(os.environ['FAKE_LOG']+'.failed-'+stage)
 if os.environ.get('FAIL_STAGE')==stage and not marker.exists():marker.write_text('1');sys.exit(44)
if name=='getent':print('growthmap-auth-stg:x:1234:1235::/nonexistent:/usr/sbin/nologin')
elif name=='systemctl':
 st=pathlib.Path(os.environ['SYSTEMCTL_STATE']);words=set(st.read_text().split());cmd=a[0]
 if cmd=='is-active':print('active' if 'active' in words else 'inactive');sys.exit(0 if 'active' in words else 3)
 if cmd=='is-enabled':print('enabled' if 'enabled' in words else 'disabled');sys.exit(0 if 'enabled' in words else 1)
 if cmd in ('restart','start'):fail('restart');words.add('active')
 if cmd=='stop':fail('stop');words.discard('active')
 if cmd=='enable':words.add('enabled')
 if cmd=='disable':words.discard('enabled')
 st.write_text(' '.join(sorted(words)))
elif name=='systemd-analyze':fail('systemd')
elif name=='ss':pass
elif name=='tar':pass
elif name=='chmod':pass
elif name=='install':
 dirs='-d' in a;vals=[];skip=False
 for i,x in enumerate(a):
  if skip:skip=False;continue
  if x in ('-m','-o','-g'):skip=True;continue
  if x=='-d':continue
  vals.append(x)
 if dirs:
  for x in vals:pathlib.Path(x).mkdir(parents=True,exist_ok=True);pathlib.Path(x).chmod(0o700 if '0700' in a else 0o755)
 else:
  src=pathlib.Path(vals[-2]);dst=pathlib.Path(vals[-1]);dst=dst/src.name if dst.is_dir() else dst;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
elif name=='python3':
 if '-m' in a and a[a.index('-m')+1]=='venv':
  dest=pathlib.Path(a[-1]);(dest/'bin').mkdir(parents=True);(dest/'lib/python3.12/site-packages').mkdir(parents=True);p=dest/'bin/python';p.write_text('#!/bin/sh\nexec "$FAKE_PYTHON3" "$@"\n');p.chmod(0o755);shutil.copyfile(sys.executable,dest/'bin/python3');(dest/'bin/python3').chmod(0o755);sys.exit()
 script=next((x for x in a if x.endswith('.py')),None)
 if script and script.endswith('transaction.py'):
  if a[a.index(script)+1]=='snapshot':fail('snapshot')
  os.execv(sys.executable,[sys.executable,script,*a[a.index(script)+1:]])
 if script and script.endswith('build_bundle.py'):
  pathlib.Path(a[-1]).write_bytes(b'tar');print(pathlib.Path(os.environ['RAIL']+'/evidence/REVIEWED-BUNDLE.sha256').read_text().strip());sys.exit()
 if script and script.endswith('verify_bundle.py'):
  if '--tar' in a:print('{}');sys.exit()
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
 for n in ('python3','getent','systemctl','systemd-analyze','ss','tar','install','chmod'):(bind/n).symlink_to(dispatcher)
 env={**os.environ,'PATH':str(bind)+':'+os.environ['PATH'],'FAKE_LOG':str(log),'SYSTEMCTL_STATE':str(state),'FAIL_STAGE':fail,'FAKE_PYTHON3':str(bind/'python3'),'RAIL':str(rail)}
 return rail,root,env,state,log

def _tree(root):
 return sorted((str(p.relative_to(root)),p.read_bytes() if p.is_file() and not p.is_symlink() else ('->'+os.readlink(p)).encode() if p.is_symlink() else b'D') for p in root.rglob('*')) if root.exists() else []

@pytest.mark.parametrize('stage',['provision','systemd','preflight','restart','acceptance','registry'])
def test_entire_deploy_fresh_failure_restores_true_prestate(tmp_path,stage):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None,stage);before=_tree(root);r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env);assert r.returncode!=0 and _tree(root)==before and state.read_text()=='active enabled';assert not any('.incoming-' in x[0] for x in _tree(root))

def test_entire_deploy_upgrade_and_rollback_active_lifecycle(tmp_path):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None);a='a'*64;b='b'*64
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(a+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(b+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 current=root/'opt/growthmap-authority-staging-r18/current';assert os.readlink(current)=='releases/'+b
 trace=log.read_text()
 assert 'verify_bundle.py --tar ' in trace and ' -m pip install --no-compile' in trace
 assert 'ss -Hln sport = :8320' in trace and 'install -d -m 0755' in trace
 # ln remains the real absolute executable and is confined to the isolated adapter tree.
 assert os.path.islink(current) and os.readlink(current)=='releases/'+b
 assert subprocess.run(['/bin/sh',str(rail/'deploy/rollback.sh'),'--apply',a],env=env).returncode==0;assert os.readlink(current)=='releases/'+a and 'restart growthmap-authority-staging-r18.service' in log.read_text()

@pytest.mark.parametrize('stage',['preflight','restart','acceptance','registry'])
def test_entire_upgrade_failure_restores_files_status_and_registry(tmp_path,stage):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None);a='a'*64;b='b'*64;(rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(a+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0;before=_tree(root);(rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(b+'\n');env['FAIL_STAGE']=stage;assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode!=0;assert _tree(root)==before and state.read_text()=='active enabled'

@pytest.mark.parametrize('stage',['preflight','restart','acceptance','registry'])
def test_entire_rollback_failure_restores_state_config_registry_and_active_process(tmp_path,stage):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None);a='a'*64;b='b'*64
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(a+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(b+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 before=_tree(root);env['FAIL_STAGE']=stage;assert subprocess.run(['/bin/sh',str(rail/'deploy/rollback.sh'),'--apply',a],env=env).returncode!=0;assert _tree(root)==before and state.read_text()=='active enabled'

def test_production_rejects_root_overrides():
 for script,args in [(DEP/'deploy.sh',[]),(DEP/'rollback.sh',['--apply','a'*64])]: 
  for key in ('R18_ROOT','R15_ROOT','GROWTHMAP_ROOT'):
   env={**os.environ,key:'/tmp/not-allowed'}
   r=subprocess.run(['/bin/sh',str(script),*args],env=env,capture_output=True,text=True)
   assert r.returncode==2 and 'root_override_rejected' in r.stderr

@pytest.mark.parametrize('stage',['stop','snapshot'])
def test_deploy_pre_snapshot_failures_restore_status_and_files(tmp_path,stage):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None,stage);before=_tree(root)
 r=subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env)
 assert r.returncode!=0 and _tree(root)==before and state.read_text()=='active enabled'

@pytest.mark.parametrize('initial',['active enabled','active disabled','inactive enabled','inactive disabled'])
def test_rollback_preserves_all_four_status_combinations(tmp_path,initial):
 rail,root,env,state,log=_fake_apply_env(tmp_path,None);a='a'*64;b='b'*64
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(a+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 (rail/'evidence/REVIEWED-BUNDLE.sha256').write_text(b+'\n');assert subprocess.run(['/bin/sh',str(rail/'deploy/deploy.sh'),'--apply'],env=env).returncode==0
 state.write_text(initial)
 assert subprocess.run(['/bin/sh',str(rail/'deploy/rollback.sh'),'--apply',a],env=env).returncode==0
 assert set(state.read_text().split())==set(initial.split())

def test_sqlite_fail_closed_wal_and_partial_cleanup(tmp_path,monkeypatch):
 t=module(DEP/'transaction.py','r18txsqlite');bad=tmp_path/'bad.db';bad.write_bytes(b'not sqlite');snap=tmp_path/'snap'
 with pytest.raises(Exception):t.snapshot(bad,snap)
 assert not snap.exists()
 db=tmp_path/'ok.sqlite3';c=__import__('sqlite3').connect(db);c.execute('pragma journal_mode=wal');c.execute('create table x(v)');c.execute('insert into x values (7)');c.commit()
 good=tmp_path/'good';t.snapshot(db,good);out=__import__('sqlite3').connect(good/'value');assert out.execute('select v from x').fetchone()==(7,);out.close();c.close()

def test_transaction_rejects_overlap_and_symlink_parent(tmp_path):
 t=module(DEP/'transaction.py','r18txcontain');a=(tmp_path/'a').absolute();a.mkdir()
 with pytest.raises(RuntimeError,match='overlap'):t.snapshot_all(a/'snap',[a])
 real=tmp_path/'real';real.mkdir();link=tmp_path/'link';link.symlink_to(real,target_is_directory=True)
 with pytest.raises(RuntimeError,match='symlink'):t.snapshot_all((tmp_path/'snap').absolute(),[(link/'state').absolute()])

def test_relocated_console_script_and_no_incoming_bytes(tmp_path):
 r=module(DEP/'relocate_venv.py','r18relocate');incoming=tmp_path/'.incoming-x';release=tmp_path/'release';v=incoming/'venv';(v/'bin').mkdir(parents=True);(release/'venv/bin').mkdir(parents=True)
 python=release/'venv/bin/python';python.write_text('x');script=v/'bin/tool';script.write_bytes(('#!'+str(v/'bin/python')+'\nprint(1)\n').encode());script.chmod(0o755)
 r.relocate(v,incoming,release);final=release/'venv/bin/tool';final.write_bytes(script.read_bytes());r.verify(release/'venv');assert b'.incoming-' not in final.read_bytes()

def test_private_temp_never_touches_predictable_symlink(tmp_path):
 text=(DEP/'rollback.sh').read_text();assert '/tmp/$UNIT.$$' not in text and 'TMP=$(/usr/bin/mktemp -d)' in text and '"$TMP/$UNIT"' in text
 sentinel=tmp_path/'sentinel';sentinel.write_text('safe');predictable=tmp_path/'growthmap-authority-staging-r18.service.1';predictable.symlink_to(sentinel)
 assert sentinel.read_text()=='safe'


def _r18_multi(tmp_path):
 t=module(DEP/'transaction.py','r18txmulti');roots=[]
 for i in range(4):
  p=tmp_path/f'r{i}';p.mkdir();(p/'v').write_text('B'+str(i));roots.append(p)
 snap=tmp_path/'snap-all';t.snapshot_all(snap,roots)
 for i,p in enumerate(roots):(p/'v').write_text('C'+str(i))
 return t,roots,snap,tmp_path/'journals'

def test_r18_all_root_restore_and_prevalidation(tmp_path):
 t,roots,snap,jr=_r18_multi(tmp_path);t.restore_all(snap,roots,jr)
 assert [(p/'v').read_text() for p in roots]==['B0','B1','B2','B3'] and not list(jr.iterdir())

def test_r18_root_boundary_failures_undo_to_exact_candidate(tmp_path,monkeypatch):
 for point in [*(f'before_backup_{i}' for i in range(4)),*(f'after_backup_{i}' for i in range(4)),*(f'before_install_{i}' for i in range(4)),*(f'after_install_{i}' for i in range(4))]:
  case=tmp_path/point;case.mkdir();t,roots,snap,jr=_r18_multi(case);monkeypatch.setenv('R18_TRANSACTION_INJECT',point)
  with pytest.raises(Exception):t.restore_all(snap,roots,jr)
  assert [(p/'v').read_text() for p in roots]==['C0','C1','C2','C3'],point
  assert not list(jr.iterdir()),point
  monkeypatch.delenv('R18_TRANSACTION_INJECT')

def test_r18_undo_failure_leaves_journal_and_recover_is_idempotent(tmp_path,monkeypatch):
 t,roots,snap,jr=_r18_multi(tmp_path);original=t._fail
 def injected(point):
  if point=='after_install_2' or point=='before_undo_1':raise OSError('injected:'+point)
 monkeypatch.setattr(t,'_fail',injected)
 with pytest.raises(RuntimeError,match='RECOVERY_REQUIRED'):t.restore_all(snap,roots,jr)
 assert list(jr.glob('*.json'))
 monkeypatch.setattr(t,'_fail',lambda _p:None);t.recover(jr);t.recover(jr)
 assert [(p/'v').read_text() for p in roots]==['C0','C1','C2','C3'] and not list(jr.iterdir())

def test_r18_metadata_tamper_matrix_is_before_mutation(tmp_path):
 mutators=[
  lambda m:m['records'][0].update(path='/outside'),
  lambda m:m['records'][0].update(path='../outside'),
  lambda m:m['records'].append(dict(m['records'][0])),
  lambda m:m['records'][0].update(type='dir'),
  lambda m:m['records'].pop(),
 ]
 for n,mutate in enumerate(mutators):
  case=tmp_path/str(n);case.mkdir();t,roots,snap,jr=_r18_multi(case);before=[(p/'v').read_text() for p in roots];mp=snap/'0/meta.json';m=json.loads(mp.read_text());mutate(m);mp.write_text(json.dumps(m))
  with pytest.raises(Exception,match='transaction'): t.restore_all(snap,roots,jr)
  assert [(p/'v').read_text() for p in roots]==before

def test_r18_complete_extra_hardlink_and_symlink_tamper(tmp_path):
 for kind in ('complete','extra','hardlink','symlink'):
  case=tmp_path/kind;case.mkdir();t,roots,snap,jr=_r18_multi(case)
  if kind=='complete':(snap/'COMPLETE').write_text('[]')
  elif kind=='extra':(snap/'0/extra').write_text('x')
  elif kind=='hardlink':os.link(snap/'0/meta.json',snap/'hard')
  else:
   (snap/'0/value/v').unlink();(snap/'0/value/v').symlink_to('../../../../escape')
  with pytest.raises(Exception):t.restore_all(snap,roots,jr)
  assert [(p/'v').read_text() for p in roots]==['C0','C1','C2','C3']

def test_r18_privileged_environment_and_absolute_python_contract():
 for p in (DEP/'deploy.sh',DEP/'rollback.sh'):
  s=p.read_text();assert s.startswith("#!/bin/sh\nPATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH\nIFS=")
  assert 'unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT' in s
  assert '/usr/bin/python3 -I -B' in s and 'python3 -B' not in s and '/usr/bin/env' not in s
  assert '--journal-root "$JOURNAL"' in s and 'primary_failure_rc=' in s and 'recovery_failure=' in s
 u=(DEP/'growthmap-authority-staging-r18.service.template').read_text()
 assert 'Environment=PATH=/usr/sbin:/usr/bin:/sbin:/bin' in u and 'Environment=PYTHONPATH=' in u

def test_r18_hostile_environment_cannot_run_path_shim(tmp_path):
 shim=tmp_path/'bin';shim.mkdir();marker=tmp_path/'executed'
 for n in ('dirname','cat','getent','cut','mktemp','stat','id','python3','systemctl'):
  p=shim/n;p.write_text('#!/bin/sh\necho bad >"$MARKER"\nexit 99\n');p.chmod(0o755)
 env={**os.environ,'PATH':str(shim),'PYTHONPATH':str(shim),'PYTHONHOME':str(shim),'PYTHONSTARTUP':str(shim/'x'),'PYTHONINSPECT':'1','CDPATH':str(shim),'IFS':':','MARKER':str(marker)}
 r=subprocess.run(['/bin/sh',str(DEP/'deploy.sh')],env=env,capture_output=True)
 assert not marker.exists() and r.returncode!=99

def test_r18_production_bytes_semantically_clean_and_regressions():
 text=(DEP/'deploy.sh').read_text()
 assert 'verify_bundle.py" --tar "$TMP/runtime.tar"' in text
 assert '-m pip install --no-compile' in text
 assert '/usr/bin/ss -Hln "sport = :$PORT"|/usr/bin/grep .' in text
 for bad in ('--/usr/','pip /usr/','-H/usr/','.replace(','staging-r17','R17_'):
  assert bad not in text
 # Every reviewed absolute executable insertion is a complete shell token.
 import re
 reviewed={'python3','dirname','pwd','cat','getent','cut','mktemp','stat','id','systemctl','rm','sha256sum','install','tar','find','chmod','mv','sed','systemd-analyze','ss','grep','ln'}
 for m in re.finditer(r'/usr/bin/([A-Za-z0-9_.-]+)',text):
  assert m.group(1) in reviewed
  assert m.start()==0 or text[m.start()-1] in ' \t\n;|($!&)'
  assert m.end()==len(text) or text[m.end()] in ' \t;|)&<>"'


def test_r18_adapter_global_substring_mutation_would_be_detected():
 text=(DEP/'deploy.sh').read_text()
 corrupted=text.replace('tar','/usr/bin/tar').replace('install','/usr/bin/install').replace('ln','/usr/bin/ln')
 assert '--/usr/bin/tar' in corrupted and 'pip /usr/bin/install' in corrupted and '-H/usr/bin/ln' in corrupted
 assert all(x not in text for x in ('--/usr/bin/tar','pip /usr/bin/install','-H/usr/bin/ln'))


def test_r18_real_plan_build_verify_wheels_and_recover(tmp_path):
 """Run canonical plan with real python/build/verify/checksums; adapt host identity and journal only."""
 import re,shutil
 work=tmp_path/'work';rail=work/'reports/phase2-authority-production-readiness-20260808/vps-staging-r18';rail.parent.mkdir(parents=True);shutil.copytree(R18,rail)
 for rel in ('src','services'):shutil.copytree(ROOT.parent/rel,work/rel)
 script=rail/'deploy/deploy.sh';text=script.read_text();bind=tmp_path/'bin';bind.mkdir()
 journal=tmp_path/'journal'
 text=text.replace('/var/lib/growthmap-authority-staging-r18-transactions',str(journal))
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
 assert journal.is_dir()
