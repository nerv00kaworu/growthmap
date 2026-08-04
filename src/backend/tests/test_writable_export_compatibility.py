import os,sqlite3,subprocess,sys
from pathlib import Path


def test_writable_export_malformed_json_is_controlled_and_auth_is_preserved(tmp_path):
 db=tmp_path/'malformed.db'
 code='''import os,sqlite3\nfrom fastapi.testclient import TestClient\nfrom main import app\nwith TestClient(app) as c:\n p=c.post('/api/projects',json={'name':'safe'}).json();pid=p['id']\n n=c.post(f'/api/projects/{pid}/nodes',json={'expected_project_revision':p['revision'],'title':'Root','node_type':'concept','status':'active','maturity':'seed'}).json();nid=n['id']\n con=sqlite3.connect(os.environ['RAW_DB']);con.execute('update projects set root_node_id=? where id=?',(nid,pid));con.execute(\"insert into content_blocks(id,node_id,block_type,content,order_index,revision) values('bad',?,'note','not-json',0,1)\",(nid,));con.commit();con.close()\n r=c.get(f'/api/projects/{pid}/export');assert r.status_code==409,r.text;assert r.json()=={'detail':'Project data is not compatible with Markdown export'}\n'''
 env={**os.environ,'DATABASE_URL':f'sqlite+aiosqlite:///{db}','RAW_DB':str(db),'APP_ENV':'test'}
 result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parents[1],env=env,text=True,capture_output=True)
 assert result.returncode==0,result.stdout+result.stderr
