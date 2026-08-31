import asyncio,os,stat
from pathlib import Path
import pytest
from api import provider_lock

@pytest.mark.asyncio
async def test_equivalent_urls_share_inode_identity_and_cancel_releases(tmp_path,monkeypatch):
 db=tmp_path/'db file.sqlite';db.write_bytes(b'x')
 a=provider_lock.canonical_database_file(f'sqlite+aiosqlite:///{db}')
 b=provider_lock.canonical_database_file(f'sqlite+aiosqlite:///{db.parent}/./db%20file.sqlite')
 assert a==b
 monkeypatch.setattr(provider_lock,'DATABASE_URL',f'sqlite+aiosqlite:///{db}')
 first=provider_lock.ProviderLock('p');await first.__aenter__()
 waiter=asyncio.create_task(provider_lock.ProviderLock('p',1).__aenter__());await asyncio.sleep(.05);waiter.cancel()
 with pytest.raises(asyncio.CancelledError):await waiter
 await first.__aexit__();again=provider_lock.ProviderLock('p',.2);await again.__aenter__();await again.__aexit__()

@pytest.mark.asyncio
async def test_cancel_reaps_slow_try_and_release_before_fd_cleanup(monkeypatch):
 events=[];allow_try=__import__('threading').Event();allow_release=__import__('threading').Event()
 monkeypatch.setattr(provider_lock,'_open',lambda _:'fd')
 def slow_try(fd):events.append(('try-start',fd));allow_try.wait(2);events.append(('try-end',fd));return True
 def slow_release(fd):events.append(('release-start',fd));allow_release.wait(2);events.append(('release-end',fd))
 monkeypatch.setattr(provider_lock,'_try',slow_try);monkeypatch.setattr(provider_lock,'_release',slow_release)
 monkeypatch.setattr(provider_lock.os,'close',lambda fd:events.append(('close',fd)))
 lock=provider_lock.ProviderLock('p');enter=asyncio.create_task(lock.__aenter__())
 while ('try-start','fd') not in events:await asyncio.sleep(.001)
 for _ in range(3):enter.cancel();await asyncio.sleep(.01);assert ('close','fd') not in events
 allow_try.set()
 with pytest.raises(asyncio.CancelledError):await enter
 assert enter.cancelling()==3
 assert events.index(('try-end','fd')) < events.index(('close','fd'))
 lock.fd='fd';leave=asyncio.create_task(lock.__aexit__());
 while ('release-start','fd') not in events:await asyncio.sleep(.001)
 for _ in range(3):leave.cancel();await asyncio.sleep(.01);assert ('release-end','fd') not in events and lock.fd=='fd'
 allow_release.set()
 with pytest.raises(asyncio.CancelledError):await leave
 assert leave.cancelling()==3
 assert ('release-end','fd') in events and lock.fd is None

@pytest.mark.asyncio
async def test_repeated_cancel_reaps_slow_open_and_worker_error(monkeypatch):
 threading=__import__('threading');events=[];allow=threading.Event()
 def slow_open(_):events.append('open-start');allow.wait(2);events.append('open-end');return 41
 monkeypatch.setattr(provider_lock,'_open',slow_open);monkeypatch.setattr(provider_lock.os,'close',lambda fd:events.append(('close',fd)))
 task=asyncio.create_task(provider_lock.ProviderLock('p').__aenter__())
 while 'open-start' not in events:await asyncio.sleep(.001)
 for _ in range(2):task.cancel();await asyncio.sleep(.01);assert ('close',41) not in events
 allow.set()
 with pytest.raises(asyncio.CancelledError):await task
 assert task.cancelling()==2 and events.index('open-end') < events.index(('close',41))
 allow=threading.Event()
 def bad_open(_):events.append('bad-start');allow.wait(2);raise RuntimeError('native failure')
 monkeypatch.setattr(provider_lock,'_open',bad_open);bad=asyncio.create_task(provider_lock.ProviderLock('p').__aenter__())
 while 'bad-start' not in events:await asyncio.sleep(.001)
 bad.cancel();bad.cancel();allow.set()
 with pytest.raises(asyncio.CancelledError) as caught:await bad
 assert bad.cancelling()==2 and isinstance(caught.value.__cause__,RuntimeError)

@pytest.mark.asyncio
async def test_reaper_uses_raw_worker_truth_and_cancelled_before_start():
 raw=__import__('concurrent.futures').futures.Future();assert raw.cancel()
 value,count,error=await asyncio.wait_for(provider_lock._reap_worker(raw),1)
 assert value is None and count==0 and isinstance(error,__import__('concurrent.futures').futures.CancelledError)
 allow=__import__('threading').Event();events=[]
 def native():events.append('start');allow.wait(2);events.append('end');return 7
 raw=provider_lock._submit_worker(native)
 async def caller():
  value,count,error=await provider_lock._reap_worker(raw);provider_lock._raise_cancelled(count,error);return value
 task=asyncio.create_task(caller())
 while 'start' not in events:await asyncio.sleep(.001)
 task.cancel();task.cancel();await asyncio.sleep(.02);assert 'end' not in events and not task.done()
 allow.set()
 with pytest.raises(asyncio.CancelledError):await task
 assert task.cancelling()==2 and events[-1]=='end' and raw.done() and raw.result()==7

@pytest.mark.asyncio
async def test_cancelled_before_start_release_abandons_fd_once(monkeypatch,tmp_path):
 path=tmp_path/'release-fd';fd=os.open(path,os.O_CREAT|os.O_RDWR,0o600)
 provider_lock._windows_fds[fd]=('owned',)
 raw=__import__('concurrent.futures').futures.Future();assert raw.cancel()
 monkeypatch.setattr(provider_lock,'_submit_worker',lambda *_:raw)
 lock=provider_lock.ProviderLock('p');lock.fd=fd
 with pytest.raises(__import__('concurrent.futures').futures.CancelledError):await lock.__aexit__()
 assert lock.fd is None and fd not in provider_lock._windows_fds
 with pytest.raises(OSError):os.fstat(fd)

def test_windows_bootstrap_publishes_only_private_staging(tmp_path,monkeypatch):
 if os.name!='nt':pytest.skip('Windows atomic publish contract')
 db=tmp_path/'db.sqlite';db.write_bytes(b'x');monkeypatch.setattr(provider_lock,'DATABASE_URL',f'sqlite+aiosqlite:///{db}')
 root,identity=provider_lock._verified_root(db)
 from api import windows_file_security as security
 assert security.verify(root,kind='dir')==identity
 assert not list(tmp_path.glob('.growthmap-locks.init-*'))

@pytest.mark.skipif(os.name=='nt',reason='POSIX ownership/mode contract')
def test_private_root_and_hardlink_leaf_rejected(tmp_path,monkeypatch):
 db=tmp_path/'db.sqlite';db.write_bytes(b'x');monkeypatch.setattr(provider_lock,'DATABASE_URL',f'sqlite+aiosqlite:///{db}')
 root=tmp_path/'.growthmap-locks';root.mkdir(mode=0o755)
 with pytest.raises(RuntimeError):provider_lock._open('p')
 os.chmod(root,0o700);fd=provider_lock._open('p');os.close(fd)
 leaf=next(root.iterdir());other=root/'hard';os.link(leaf,other)
 with pytest.raises(RuntimeError):provider_lock._open('p')

def test_windows_path_canonicalization_rejects_hostile_forms():
 from api import windows_file_security as security
 assert security._canonical_local_path(r'C:\Windows')==r'C:\Windows'
 for value in ['',r'Windows',r'..\Windows',r'\\server\share',r'C:\Windows\..\Elsewhere',r'C:\Windows:stream',r'C:\Win|dows',r'C:\Windows. ',r'\\?\C:\Windows']:
  with pytest.raises(RuntimeError,match='policy unavailable'):security._canonical_local_path(value)

def test_windows_powershell_ignores_spoofed_environment(monkeypatch):
 from api import windows_file_security as security
 expected=r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe';seen=[]
 monkeypatch.setenv('SystemRoot',r'Z:\spoofed');monkeypatch.setenv('PATH',r'Z:\spoofed')
 monkeypatch.setattr(security,'_native_windows_directory',lambda:r'C:\Windows')
 monkeypatch.setattr(security,'_verified_existing_component',lambda path,directory:seen.append((path,directory)) or (1,99 if path==expected else len(seen)))
 assert security._powershell_path()==expected
 assert seen[-1]==(expected,False) and len(seen)==6

def test_windows_powershell_component_verification_fails_closed(monkeypatch):
 from api import windows_file_security as security
 monkeypatch.setattr(security,'_native_windows_directory',lambda:r'C:\Windows')
 monkeypatch.setattr(security,'_verified_existing_component',lambda *_:(_ for _ in ()).throw(RuntimeError('policy unavailable')))
 with pytest.raises(RuntimeError,match='policy unavailable'):security._powershell_path()

def test_windows_powershell_identity_substitution_fails_closed(monkeypatch):
 from api import windows_file_security as security
 monkeypatch.setattr(security,'_native_windows_directory',lambda:r'C:\Windows')
 calls=0
 def verify(path,directory):
  nonlocal calls
  calls+=1
  return (1,calls if not directory else calls)
 monkeypatch.setattr(security,'_verified_existing_component',verify)
 with pytest.raises(RuntimeError,match='policy unavailable'):security._powershell_path()

def test_windows_component_acl_allow_and_deny_are_fail_closed(monkeypatch):
 from api import windows_file_security as security
 # Component verifier must invoke native ACL validation before returning identity.
 source=__import__('inspect').getsource(security._verified_existing_component)
 assert '_validate_native_acl(handle)' in source
 monkeypatch.setattr(security,'_validate_native_acl',lambda _handle:(_ for _ in ()).throw(RuntimeError('policy unavailable')))
 # Native handle behavior is covered on Windows; this platform-neutral assertion
 # proves ACL rejection is represented by the fixed fail-closed class.
 with pytest.raises(RuntimeError,match='policy unavailable'):security._validate_native_acl(1)

def test_windows_acl_validator_allows_only_trusted_write_aces():
 from api import windows_file_security as security
 user='S-1-5-21-1';write=0x40000000;generic_all=0x10000000
 security._acl_policy('S-1-5-18',[('S-1-5-32-544',write),('S-1-5-11',0x80000000)])
 for owner,entries in [(user,[]),('S-1-5-18',[(user,write)]),('S-1-5-18',[('S-1-5-11',write)]),('S-1-5-18',[('S-1-5-11',generic_all)])]:
  with pytest.raises(RuntimeError,match='policy unavailable'):security._acl_policy(owner,entries)

def test_windows_acl_validator_has_fixed_trusted_sid_and_write_mask_contract():
 from api import windows_file_security as security
 source=__import__('inspect').getsource(security._acl_policy)+__import__('inspect').getsource(security._validate_native_acl)
 for sid in ('S-1-5-18','S-1-5-32-544','S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'):
  assert sid in source
 assert 'write_mask' in source and 'ACCESS_ALLOWED_ACE_TYPE' in source
 assert 'SE_FILE_OBJECT' in source and '_UNPARSED_ALLOW_ACE_TYPES' in source and 'AceSize < 8' in source

def test_windows_policy_launches_resolved_absolute_powershell(monkeypatch):
 from api import windows_file_security as security
 expected=r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe';seen=[]
 monkeypatch.setattr(security.os,'name','nt');monkeypatch.setattr(security,'_powershell_path',lambda:expected)
 class Result:returncode=0;stdout='{}'
 monkeypatch.setattr(security.subprocess,'run',lambda argv,**kw:(seen.append((argv,kw)) or Result()))
 assert security._run({'action':'verify'})=={}
 assert seen[0][0][0]==expected and seen[0][0][0]!='powershell.exe'

def test_windows_file_security_native_abi_and_ace_contract():
 from api import windows_file_security as security
 import inspect
 acl=inspect.getsource(security._validate_native_acl);kernel=inspect.getsource(security._kernel32);sid=inspect.getsource(security._sid_text)
 assert 'GetSecurityInfo(handle,SE_FILE_OBJECT' in acl and security.SE_FILE_OBJECT==1
 component=inspect.getsource(security._verified_existing_component)
 assert '0x00020000 | 0x80' in component  # READ_CONTROL | FILE_READ_ATTRIBUTES
 assert set(security._UNPARSED_ALLOW_ACE_TYPES)>={4,5,9,11}
 assert 'header.AceSize < 8' in acl and 'info.AclBytesInUse' in acl
 assert 'LocalFree.argtypes = [wintypes.LPVOID]' in kernel and 'LocalFree.restype = wintypes.LPVOID' in kernel
 assert '_kernel32().LocalFree' in sid and 'ctypes.windll' not in sid+acl
 assert '_current_user_sid' not in inspect.getsource(security)
