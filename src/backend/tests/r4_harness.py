import os,tempfile
from pathlib import Path
from tests.database_harness import rebind_database,dispose_database


def setup_r4(name):
 old=(os.environ.get('DATABASE_URL'),os.environ.get('GROWTHMAP_HUMAN_CONTROL_TOKEN'))
 root=tempfile.TemporaryDirectory(prefix=f'growthmap-{name}-')
 url=f"sqlite+aiosqlite:///{Path(root.name)/f'{name}.db'}"
 os.environ['DATABASE_URL']=url;os.environ['GROWTHMAP_HUMAN_CONTROL_TOKEN']='human-test'
 rebind_database(url)
 return old,root


def teardown_r4(state):
 old,root=state;dispose_database()
 for key,value in zip(('DATABASE_URL','GROWTHMAP_HUMAN_CONTROL_TOKEN'),old):
  if value is None:os.environ.pop(key,None)
  else:os.environ[key]=value
 root.cleanup()
