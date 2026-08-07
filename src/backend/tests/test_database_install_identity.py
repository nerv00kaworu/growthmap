import os
from pathlib import Path
import pytest
from desktop import database_maintenance as dm
from tests.test_database_maintenance import fixture


def _env(monkeypatch, staged, live, old, capture):
    meta=dm.validate(staged)
    values={
        'GROWTHMAP_MAINTENANCE_OLD':str(old),'GROWTHMAP_MAINTENANCE_CAPTURE':str(capture),
        'GROWTHMAP_EXPECTED_SHA256':meta['sha256'],'GROWTHMAP_EXPECTED_SIZE':str(meta['size']),
        'GROWTHMAP_EXPECTED_DEVICE':str(meta['device']),'GROWTHMAP_EXPECTED_INODE':str(meta['inode']),
        'GROWTHMAP_MAX_ACTIVE_PROJECTS':'1',
    }
    for key,value in values.items():monkeypatch.setenv(key,value)


def test_same_bytes_new_inode_capture_swap_is_rejected(tmp_path,monkeypatch):
    live=tmp_path/'live.db';staged=tmp_path/'staged.db';old=tmp_path/'old.db';capture=tmp_path/'capture.db'
    fixture(live);fixture(staged)
    _env(monkeypatch,staged,live,old,capture)
    def swap(path):
        replacement=path.with_suffix('.swap');replacement.write_bytes(path.read_bytes());os.replace(replacement,path)
    with pytest.raises(ValueError,match='identity changed'):dm.install_database(staged,live,_test_before_install=swap)
    assert dm.validate(live)['counts']['activeProjects']==1 and not old.exists()


def test_ordinary_install_preserves_identity_when_meaningful(tmp_path,monkeypatch):
    live=tmp_path/'live.db';staged=tmp_path/'staged.db';old=tmp_path/'old.db';capture=tmp_path/'capture.db'
    fixture(live);fixture(staged);_env(monkeypatch,staged,live,old,capture)
    result=dm.install_database(staged,live);identity=result['installed']['identity'];stat=live.lstat()
    if identity['meaningful']: assert (stat.st_dev,stat.st_ino)==(identity['device'],identity['inode'])
    assert result['installed']['counts']['activeProjects']==1 and old.exists()
