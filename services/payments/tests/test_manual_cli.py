import json,os,subprocess,sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from desktop.entitlements import verify_document
ROOT=Path(__file__).resolve().parents[3]

def run(*args,check=True):
 env=dict(os.environ);env['PYTHONPATH']=f"{ROOT/'services/payments'}:{ROOT/'src/backend'}";return subprocess.run([sys.executable,'-m','growthmap_payments.manual_cli',*map(str,args)],env=env,capture_output=True,text=True,check=check)

def setup(tmp_path):
 private=tmp_path/'secret'/'issuer.pem';public=tmp_path/'public.pem';run('generate-key','--private-key',private,'--public-key',public);mac=tmp_path/'secret'/'mac.bin';mac.write_bytes(os.urandom(32));os.chmod(mac,0o600);return private,public,mac,tmp_path/'checkpoint.json',tmp_path/'payments.sqlite'

def common(private,mac,checkpoint,db):return ['--db',db,'--signing-key',private,'--mac-key',mac,'--checkpoint',checkpoint]

def test_manual_cli_paypal_issues_verifiable_license_and_rejects_duplicate(tmp_path):
 private,public,mac,checkpoint,db=setup(tmp_path);created=json.loads(run('create-order',*common(private,mac,checkpoint,db),'--rail','paypal','--email','buyer@example.test','--license-name','Buyer').stdout);out=tmp_path/'license.json';issued=run('issue',*common(private,mac,checkpoint,db),'--rail','paypal','--order-id',created['order_id'],'--proof','PAYPAL-TX-1','--amount','10.00','--status','COMPLETED','--currency','USD','--payee-verified','--output',out);assert json.loads(issued.stdout)['sale_ordinal']==1;assert verify_document(json.loads(out.read_text()),public).mutations_allowed
 duplicate=run('create-order',*common(private,mac,checkpoint,db),'--rail','paypal','--email','buyer2@example.test',check=True);oid=json.loads(duplicate.stdout)['order_id'];failed=run('issue',*common(private,mac,checkpoint,db),'--rail','paypal','--order-id',oid,'--proof','PAYPAL-TX-1','--amount','10.00','--status','COMPLETED','--currency','USD','--payee-verified','--output',tmp_path/'duplicate.json',check=False);assert failed.returncode!=0 and not (tmp_path/'duplicate.json').exists()

def test_manual_cli_base_requires_final_exact_boundary(tmp_path):
 private,public,mac,checkpoint,db=setup(tmp_path);created=json.loads(run('create-order',*common(private,mac,checkpoint,db),'--rail','x402','--email','base@example.test').stdout);tx='0x'+'a'*64;bad=run('issue',*common(private,mac,checkpoint,db),'--rail','base','--order-id',created['order_id'],'--proof',tx,'--amount','10.00','--network','eip155:1','--final','--output',tmp_path/'bad.json',check=False);assert bad.returncode!=0 and not (tmp_path/'bad.json').exists();out=tmp_path/'base.json';run('issue',*common(private,mac,checkpoint,db),'--rail','base','--order-id',created['order_id'],'--proof',tx,'--amount','10.00','--sender','0x'+'2'*40,'--final','--output',out);assert verify_document(json.loads(out.read_text()),public).mutations_allowed

def test_key_generation_never_overwrites(tmp_path):
 private=tmp_path/'private.pem';public=tmp_path/'public.pem';run('generate-key','--private-key',private,'--public-key',public);assert private.stat().st_mode&0o777==0o600;failed=run('generate-key','--private-key',private,'--public-key',tmp_path/'other.pem',check=False);assert failed.returncode!=0
