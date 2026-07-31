"""Offline/manual payment operator CLI. Secrets are file paths only, never CLI values."""
from __future__ import annotations
import argparse,json,os,re,sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from .service import Config,PaymentService,BASE_NETWORK,BASE_USDC
BASE_PAYEE="0x81d30e175a22c1c2f78b3db6fc0600a6e1cb3591"

def private_path(value:str)->Path:
 p=Path(value).expanduser().resolve()
 if not p.is_file():raise argparse.ArgumentTypeError("secret file does not exist")
 return p

def output_path(value:str)->Path:
 p=Path(value).expanduser().resolve()
 if p.exists():raise argparse.ArgumentTypeError("refusing to overwrite output")
 return p

def load_private(path:Path)->Ed25519PrivateKey:
 key=serialization.load_pem_private_key(path.read_bytes(),password=None)
 if not isinstance(key,Ed25519PrivateKey):raise RuntimeError("Ed25519 private key required")
 return key

def service(a)->PaymentService:
 return PaymentService(Config(a.db,BASE_PAYEE,"",load_private(a.signing_key),purchase_resource_base="https://manual.invalid",isolated_test=True,settlement_mac_key=a.mac_key.read_bytes(),settlement_checkpoint_path=a.checkpoint))

def write_private(path:Path,data:bytes):
 path.parent.mkdir(parents=True,exist_ok=True)
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())

def generate(a):
 key=Ed25519PrivateKey.generate();write_private(a.private_key,key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));a.public_key.parent.mkdir(parents=True,exist_ok=True);write_private(a.public_key,key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo));print(json.dumps({"private_key":str(a.private_key),"public_key":str(a.public_key)},separators=(",",":")))

def create(a):print(json.dumps(service(a).create_order(a.rail,a.email,a.license_name),separators=(",",":")))

def issue(a):
 s=service(a)
 if a.rail=="paypal":
  if not(a.status=="COMPLETED" and a.currency=="USD" and a.payee_verified):raise SystemExit("PayPal evidence must be COMPLETED USD with independently verified payee")
  s.paypal_submit(a.order_id,a.proof);row=s.paypal_confirm(a.order_id,a.proof,{"amount":a.amount,"currency":"USD","status":"COMPLETED","payee_verified":True},actor=a.actor)
 else:
  if a.network!=BASE_NETWORK or a.asset.lower()!=BASE_USDC.lower() or a.recipient.lower()!=BASE_PAYEE.lower() or not a.final or not re.fullmatch(r"0x[0-9a-fA-F]{64}",a.proof):raise SystemExit("Base evidence must be final chain 8453 native Circle USDC to configured recipient with a transaction hash")
  amount=PaymentService.paypal_minor(a.amount)*10_000
  row=s.confirm_payment_and_allocate_sale(a.order_id,a.proof,amount,"USDC",payer_ref=a.sender,tx_hash=a.proof,actor=a.actor)
 if row["state"]!="license_issued":raise SystemExit(f"issuance failed closed in state {row['state']}")
 a.output.parent.mkdir(parents=True,exist_ok=True);write_private(a.output,(row["license_json"]+"\n").encode());print(json.dumps({"order_id":a.order_id,"state":row["state"],"sale_ordinal":row["sale_ordinal"],"license_id":row["license_id"],"output":str(a.output)},separators=(",",":")))

def common(p):
 p.add_argument("--db",type=Path,required=True);p.add_argument("--signing-key",type=private_path,required=True);p.add_argument("--mac-key",type=private_path,required=True);p.add_argument("--checkpoint",type=Path,required=True)

def parser():
 p=argparse.ArgumentParser(prog="growthmap-manual-payments");sub=p.add_subparsers(dest="command",required=True)
 g=sub.add_parser("generate-key");g.add_argument("--private-key",type=output_path,required=True);g.add_argument("--public-key",type=output_path,required=True);g.set_defaults(func=generate)
 c=sub.add_parser("create-order");common(c);c.add_argument("--rail",choices=("paypal","x402"),required=True);c.add_argument("--email",required=True);c.add_argument("--license-name",default="Personal");c.set_defaults(func=create)
 i=sub.add_parser("issue");common(i);i.add_argument("--rail",choices=("paypal","base"),required=True);i.add_argument("--order-id",required=True);i.add_argument("--proof",required=True);i.add_argument("--amount",required=True);i.add_argument("--output",type=output_path,required=True);i.add_argument("--actor",default="manual-operator");i.add_argument("--status");i.add_argument("--currency");i.add_argument("--payee-verified",action="store_true");i.add_argument("--network",default=BASE_NETWORK);i.add_argument("--asset",default=BASE_USDC);i.add_argument("--recipient",default=BASE_PAYEE);i.add_argument("--sender");i.add_argument("--final",action="store_true");i.set_defaults(func=issue)
 return p

def main(argv=None):a=parser().parse_args(argv);a.func(a)
if __name__=="__main__":main()
