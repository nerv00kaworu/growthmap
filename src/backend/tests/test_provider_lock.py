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
