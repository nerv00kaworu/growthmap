import base64
import json
import logging
import re
import subprocess
import tempfile
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256
from fastapi.testclient import TestClient

from growthmap_payments.gift_bridge import (ADMIN_EMAIL, ADMIN_ORIGIN, AccessJWTVerifier,
    SessionCodec, create_gift_admin_app, create_public_gift_claim_app)


def b64(value): return base64.urlsafe_b64encode(value).decode().rstrip("=")


def jwt(key, *, issuer, audience, email=ADMIN_EMAIL, exp=None, kid="one"):
    header=b64(json.dumps({"alg":"RS256","kid":kid,"typ":"JWT"},separators=(",",":")).encode())
    claims=b64(json.dumps({"iss":issuer,"aud":audience,"email":email,"exp":exp or int(time.time())+300},separators=(",",":")).encode())
    signature=key.sign((header+"."+claims).encode(),padding.PKCS1v15(),SHA256())
    return header+"."+claims+"."+b64(signature)


def verifier(key, issuer="https://team.cloudflareaccess.com", audience="aud"):
    numbers=key.public_key().public_numbers()
    # Match Cloudflare's live response shape: standards-based keys plus legacy
    # certificate fields that are not verification inputs.
    jwks={"keys":[{"kty":"RSA","alg":"RS256","kid":"one","n":b64(numbers.n.to_bytes((numbers.n.bit_length()+7)//8,"big")),"e":b64(numbers.e.to_bytes((numbers.e.bit_length()+7)//8,"big"))}],"public_cert":{"kid":"one","cert":"legacy"},"public_certs":[{"kid":"one","cert":"legacy"}]}
    return AccessJWTVerifier(issuer=issuer,audience=audience,email=ADMIN_EMAIL,jwks_url=issuer+"/cdn-cgi/access/certs",fetcher=lambda _:json.dumps(jwks).encode())


class Authority:
    def __init__(self): self.gifts=[];self.create_calls=0
    def list_gifts(self): return list(self.gifts)
    def create_gift(self,**_):
        self.create_calls+=1;gift={"gift_id":f"00000000-0000-4000-8000-{self.create_calls:012d}","status":"active","claim_key":f"GMG1.00000000-0000-4000-8000-{self.create_calls:012d}."+"s"*32};self.gifts.append({k:v for k,v in gift.items() if k!="claim_key"});return gift
    def get_gift(self,gift_id): return next(x for x in self.gifts if x["gift_id"]==gift_id)
    def recover_gift(self,gift_id): return self.get_gift(gift_id)|{"claim_key":f"GMG1.{gift_id}."+"r"*32}
    def revoke_gift(self,gift_id): return self.get_gift(gift_id)|{"status":"revoked"}
    def list_gift_devices(self,_): return []
    def deactivate_gift_device(self,_,__): return True
    def gift_claim_challenge(self,claim_key,device_public_key): return {"challenge_id":"gmc_"+"a"*32,"nonce":"n"*24,"license_id":"gm_"+"b"*32,"device_public_key":device_public_key}
    def gift_claim_complete(self,challenge_id,proof): return {"schema_version":2,"certificate_type":"growthmap_device_activation"}


def login(client,key,**claims):
    token=jwt(key,issuer="https://team.cloudflareaccess.com",audience="aud",**claims)
    response=client.get("/",headers={"Cf-Access-Jwt-Assertion":token})
    return response


def test_jwt_signature_issuer_audience_expiry_and_exact_email():
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048);verify=verifier(key)
    assert verify.verify(jwt(key,issuer=verify.issuer,audience="aud"))["email"]==ADMIN_EMAIL
    bad=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    cases=[jwt(bad,issuer=verify.issuer,audience="aud"),jwt(key,issuer="https://wrong.cloudflareaccess.com",audience="aud"),jwt(key,issuer=verify.issuer,audience="wrong"),jwt(key,issuer=verify.issuer,audience="aud",exp=int(time.time())-1),jwt(key,issuer=verify.issuer,audience="aud",email="other@example.com")]
    for token in cases:
        try: verify.verify(token)
        except Exception: pass
        else: raise AssertionError("invalid Access JWT accepted")


def test_forged_email_header_denied_and_route_separation():
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048);authority=Authority()
    app=create_gift_admin_app(authority=authority,access=verifier(key),sessions=SessionCodec(b"k"*32,ttl=300))
    client=TestClient(app)
    assert client.get("/",headers={"Cf-Access-Authenticated-User-Email":ADMIN_EMAIL}).status_code==403
    public=TestClient(create_public_gift_claim_app(authority=authority))
    assert public.get("/v1/admin/gifts").status_code==404
    assert public.get("/v1/admin/gifts").headers["cache-control"]=="no-store"


def test_csrf_origin_batch_and_one_time_secret_not_in_list_or_logs(caplog):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048);authority=Authority()
    client=TestClient(create_gift_admin_app(authority=authority,access=verifier(key),sessions=SessionCodec(b"k"*32,ttl=300)),base_url="https://admin-api.growthmap.work")
    page=login(client,key);assert page.status_code==200
    assert "可直接交給親友的 GMG1 授權碼" in page.text
    assert "複製授權碼" in page.text and "下載 TXT" in page.text
    script=re.search(r"<script>([\s\S]*)</script>",page.text)
    assert script is not None
    with tempfile.NamedTemporaryFile("w",suffix=".js",encoding="utf-8") as rendered:
        rendered.write(script.group(1));rendered.flush()
        syntax=subprocess.run(["node","--check",rendered.name],capture_output=True,text=True)
    assert syntax.returncode==0,syntax.stderr
    csrf=page.text.split("name=csrf content='")[1].split("'")[0]
    body={"count":2,"edition":"personal","major_version":1,"seat_limit":2,"expires_at":None,"check_in_days":30}
    assert client.post("/v1/admin/gifts/create",json=body).status_code==403
    assert client.post("/v1/admin/gifts/create",json=body,headers={"Origin":"https://evil.example","X-CSRF-Token":csrf}).status_code==403
    with caplog.at_level(logging.DEBUG):
        created=client.post("/v1/admin/gifts/create",json=body,headers={"Origin":ADMIN_ORIGIN,"X-CSRF-Token":csrf})
    assert created.status_code==201 and created.json()["complete"] is True and authority.create_calls==2
    plaintext=[row["gift"]["claim_key"] for row in created.json()["results"]]
    listed=client.get("/v1/admin/gifts").text
    assert all(secret not in listed and secret not in caplog.text for secret in plaintext)


def test_public_claim_success_and_generic_failure():
    client=TestClient(create_public_gift_claim_app(authority=Authority()))
    ok=client.post("/v1/gifts/claim/challenge",json={"claim_key":"GMG1.x.y","device_public_key":"d"*44})
    assert ok.status_code==200 and ok.json()["state"]=="challenge_issued" and ok.headers["cache-control"]=="no-store"
    assert client.post("/v1/gifts/claim/challenge",json={}).status_code in {400,422}
