"""Candidate HTTP boundary. Real x402/CDP facilitator integration is intentionally blocked."""
from __future__ import annotations
import base64, hashlib, hmac, json, os
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from .service import Config, PaymentService

class MockFacilitator:
    """Deterministic tests only: signature is base64url JSON; never production."""
    def __init__(self): self.settled={}
    def verify(self,signature,requirements):
        try: value=json.loads(base64.urlsafe_b64decode(signature+'='*(-len(signature)%4)))
        except Exception as e: raise ValueError("malformed payment signature") from e
        required=requirements["accepts"][0]
        for key in ("network","asset","amount","payTo"):
            if str(value.get(key))!=str(required[key]): raise ValueError(f"wrong {key}")
        if value.get("orderId")!=required["extra"]["orderId"]: raise ValueError("wrong order")
        return value
    def settle(self,signature,requirements):
        value=self.verify(signature,requirements);nonce=value.get("nonce")
        if not nonce: raise ValueError("missing nonce")
        prior=self.settled.get(nonce)
        result=prior or {"success":True,"transaction":value.get("transaction") or "mock:"+hashlib.sha256(signature.encode()).hexdigest()}
        self.settled[nonce]=result;return result

def load_key(path: str|None):
    if not path:return None
    key=serialization.load_pem_private_key(Path(path).read_bytes(),password=None)
    if not isinstance(key,Ed25519PrivateKey):raise RuntimeError("Ed25519 key required")
    return key

def create_app(config:Config,facilitator=None):
    service=PaymentService(config,facilitator);app=FastAPI(title="GrowthMap Payments Candidate",version="1.0-candidate")
    def admin(request:Request,authorization:str|None,csrf:str|None):
        if request.headers.get("origin") not in {"https://admin.invalid","http://testserver"}:raise HTTPException(403,"origin")
        if csrf!="test-csrf" or not authorization or not hmac.compare_digest(hashlib.sha256(authorization.removeprefix("Bearer ").encode()).hexdigest(),config.admin_secret_hash):raise HTTPException(403,"admin authentication/CSRF")
    @app.post('/v1/orders')
    async def create(body:dict): return service.create_order(body.get('rail',''),body.get('email',''),body.get('license_name','Personal'))
    @app.post('/v1/orders/{oid}/purchase')
    async def purchase(oid:str,payment_signature:str|None=Header(None,alias='PAYMENT-SIGNATURE')):
        try: challenge=service.challenge(oid)
        except (KeyError,ValueError) as e: raise HTTPException(410,str(e))
        if not payment_signature:return JSONResponse(status_code=402,content={"error":"payment_required"},headers={"PAYMENT-REQUIRED":base64.b64encode(json.dumps(challenge,separators=(',',':')).encode()).decode()})
        if facilitator is None:raise HTTPException(503,"real facilitator integration blocked")
        try:
            verified=facilitator.verify(payment_signature,challenge)
        except Exception as e:
            raise HTTPException(409,"payment verification failed") from e
        try:
            # Serialize verify-before-settle tier check through local allocation. A multi-instance
            # deployment must replace this with a database advisory lock/official SDK transaction.
            with service._lock:
                with service._db() as db:
                    row=db.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone();confirmed=db.execute("SELECT count(*) FROM orders WHERE confirmed_at IS NOT NULL").fetchone()[0]
                    expected=10_000_000 if confirmed<50 else 29_000_000
                if not row or row["state"]!="pending_payment" or int(verified["amount"])!=expected or int(row["quoted_amount"])!=expected:
                    with service._db() as db: db.execute("UPDATE orders SET state='manual_review',updated_at=? WHERE id=?",(service.now(),oid))
                    raise HTTPException(409,"stale quote: no settlement; manual review/requote")
                settled=facilitator.settle(payment_signature,challenge)
                if not settled.get("success"):raise RuntimeError("ambiguous settlement")
                current=service.confirm_payment_and_allocate_sale(oid,"authorization:"+verified["nonce"],int(verified["amount"]),"USDC",tx_hash=settled["transaction"],actor="x402.settle")
            return {"order_id":oid,"state":"license_issued","license":json.loads(current["license_json"]),"transaction":settled["transaction"]}
        except HTTPException:raise
        except Exception as e:
            # Candidate flags ambiguity; operator must reconcile. It never retries settlement here.
            with service._db() as db: db.execute("UPDATE orders SET state='manual_review',updated_at=? WHERE id=?",(service.now(),oid))
            raise HTTPException(409,"verification/settlement ambiguous; manual review required") from e
    @app.post('/v1/orders/{oid}/paypal-submit')
    async def paypal_submit(oid:str,body:dict):
        # Submission is a claim only. Screenshot/file input is intentionally absent.
        tx=str(body.get('transaction_id','')).strip()
        if not tx or len(tx)>120:raise HTTPException(422,"transaction id")
        with service._db() as db:
            try: db.execute("INSERT INTO external_events(event_hash,source,order_id,received_at) VALUES(?,?,?,?)",(service._hash('paypal:'+tx),'paypal-claim',oid,service.now()))
            except Exception as e:raise HTTPException(409,"duplicate transaction id") from e
            db.execute("UPDATE orders SET payer_ref=?,updated_at=? WHERE id=? AND rail='paypal'",(tx,service.now(),oid))
        return {"state":"pending_payment","notice":"Manual PayPal dashboard verification required; screenshots are not evidence."}
    @app.get('/v1/admin/orders')
    async def list_orders(request:Request,authorization:str|None=Header(None),csrf:str|None=Header(None,alias='X-CSRF-Token')):
        admin(request,authorization,csrf)
        with service._db() as db:return [dict(r) for r in db.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 200")]
    @app.post('/v1/admin/orders/{oid}/paypal-confirm')
    async def paypal_confirm(oid:str,body:dict,request:Request,authorization:str|None=Header(None),csrf:str|None=Header(None,alias='X-CSRF-Token')):
        admin(request,authorization,csrf)
        try:return service.paypal_confirm(oid,body['transaction_id'],body['attestation'])
        except (ValueError,KeyError) as e:raise HTTPException(409,str(e))
    @app.post('/v1/admin/orders/{oid}/{action}')
    async def admin_action(oid:str,action:str,request:Request,authorization:str|None=Header(None),csrf:str|None=Header(None,alias='X-CSRF-Token')):
        admin(request,authorization,csrf)
        mapping={'reject':'rejected','refund':'refunded','revoke':'revoked'}
        if action not in mapping:raise HTTPException(404,"action")
        with service._db() as db:
            db.execute("BEGIN IMMEDIATE");row=db.execute("SELECT state FROM orders WHERE id=?",(oid,)).fetchone()
            if not row:raise HTTPException(404,"order")
            target=mapping[action];db.execute("UPDATE orders SET state=?,updated_at=? WHERE id=?",(target,service.now(),oid));service._audit(db,'admin',f'order.{action}',oid,{'from':row['state'],'to':target});db.commit()
        return {'order_id':oid,'state':target,'offline_notice':'Existing offline license remains usable until signed revocation/check-in.' if target in {'refunded','revoked'} else None}
    @app.get('/v1/recovery/{code}')
    async def recovery(code:str):
        # Deployment must attach rate limiting; response is deliberately non-enumerating.
        with service._db() as db:row=db.execute("SELECT state,license_json FROM orders WHERE recovery_code_hash=?",(service._hash(code),)).fetchone()
        if not row:return {'state':'not_found_or_unavailable'}
        return {'state':row['state'],'license':json.loads(row['license_json']) if row['state']=='license_issued' and row['license_json'] else None}
    app.state.payments=service
    return app

def from_env():
    production=os.getenv('GROWTHMAP_PAYMENTS_ENV')=='production';recipient=os.getenv('GROWTHMAP_X402_RECIPIENT','')
    return create_app(Config(Path(os.getenv('GROWTHMAP_PAYMENTS_DB','payments.sqlite3')),recipient,os.getenv('GROWTHMAP_ADMIN_SECRET_SHA256',''),load_key(os.getenv('GROWTHMAP_SIGNING_KEY_FILE')),production=production),None if production else MockFacilitator())
