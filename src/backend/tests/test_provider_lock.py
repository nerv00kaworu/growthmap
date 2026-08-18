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

@pytest.mark.skipif(os.name=='nt',reason='POSIX ownership/mode contract')
def test_private_root_and_hardlink_leaf_rejected(tmp_path,monkeypatch):
 db=tmp_path/'db.sqlite';db.write_bytes(b'x');monkeypatch.setattr(provider_lock,'DATABASE_URL',f'sqlite+aiosqlite:///{db}')
 root=tmp_path/'.growthmap-locks';root.mkdir(mode=0o755)
 with pytest.raises(RuntimeError):provider_lock._open('p')
 os.chmod(root,0o700);fd=provider_lock._open('p');os.close(fd)
 leaf=next(root.iterdir());other=root/'hard';os.link(leaf,other)
 with pytest.raises(RuntimeError):provider_lock._open('p')
