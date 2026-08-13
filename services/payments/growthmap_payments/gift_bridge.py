"""Private Cloudflare-Access Gift Admin and public signed Authority claim bridge."""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import re
import secrets
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from .authority_http import SignedAuthorityHTTPAdapter

ADMIN_ORIGIN = "https://admin-api.growthmap.work"
ADMIN_EMAIL = "nerv00kaworu@gmail.com"
MAX_BODY = 16_384


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


@dataclass(frozen=True)
class GiftBridgeConfig:
    access_issuer: str
    access_audience: str
    access_email: str
    access_jwks_url: str
    session_hmac_key_file: Path
    authority_origin: str
    authority_id: str
    authority_audience: str
    edge_identity: str
    edge_source: str
    edge_private_key_file: Path
    signer_identity: dict[str, Any]
    session_ttl_seconds: int = 900


def load_gift_bridge_config(path: Path | str) -> GiftBridgeConfig:
    try:
        raw = json.loads(Path(path).read_text("utf-8"))
    except Exception as exc:
        raise RuntimeError("gift bridge config unavailable") from exc
    fields = {"access_issuer", "access_audience", "access_email", "access_jwks_url",
              "session_hmac_key_file", "authority_origin", "authority_id", "authority_audience",
              "edge_identity", "edge_source", "edge_private_key_file", "signer_identity",
              "session_ttl_seconds"}
    if type(raw) is not dict or set(raw) != fields:
        raise RuntimeError("gift bridge config invalid")
    issuer = raw["access_issuer"]
    if (type(issuer) is not str or re.fullmatch(r"https://[a-z0-9-]+\.cloudflareaccess\.com", issuer) is None
            or raw["access_jwks_url"] != issuer + "/cdn-cgi/access/certs"
            or type(raw["access_audience"]) is not str or not raw["access_audience"]
            or raw["access_email"] != ADMIN_EMAIL or type(raw["session_ttl_seconds"]) is not int
            or not 60 <= raw["session_ttl_seconds"] <= 1800):
        raise RuntimeError("gift bridge config invalid")
    for key in ("session_hmac_key_file", "edge_private_key_file"):
        if type(raw[key]) is not str or not Path(raw[key]).is_absolute():
            raise RuntimeError("gift bridge config invalid")
    return GiftBridgeConfig(**{**raw, "session_hmac_key_file": Path(raw["session_hmac_key_file"]),
                               "edge_private_key_file": Path(raw["edge_private_key_file"])})


class AccessJWTVerifier:
    """Validate the Access assertion itself; never consume the email convenience header."""
    def __init__(self, *, issuer: str, audience: str, email: str, jwks_url: str,
                 ttl_seconds: int = 300, clock=time.time, fetcher=None):
        self.issuer, self.audience, self.email, self.jwks_url = issuer, audience, email, jwks_url
        self.ttl, self.clock, self.fetcher = ttl_seconds, clock, fetcher or self._fetch
        self._expires, self._keys = 0.0, {}

    @staticmethod
    def _fetch(url: str) -> bytes:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status != 200 or response.headers.get_content_type() != "application/json":
                raise ValueError
            data = response.read(65_537)
            if len(data) > 65_536: raise ValueError
            return data

    def _refresh(self):
        value = json.loads(self.fetcher(self.jwks_url))
        # Cloudflare's live JWKS response includes legacy public_cert/public_certs
        # alongside the standards-based keys array. Ignore those non-authoritative
        # extras; only parsed RSA/RS256 JWKs participate in verification.
        if type(value) is not dict or type(value.get("keys")) is not list: raise ValueError
        keys = {}
        for item in value["keys"]:
            if (type(item) is not dict or item.get("kty") != "RSA" or item.get("alg") != "RS256"
                    or type(item.get("kid")) is not str or type(item.get("n")) is not str
                    or type(item.get("e")) is not str): continue
            n, e = int.from_bytes(_b64decode(item["n"]), "big"), int.from_bytes(_b64decode(item["e"]), "big")
            keys[item["kid"]] = rsa.RSAPublicNumbers(e, n).public_key()
        if not keys: raise ValueError
        self._keys, self._expires = keys, self.clock() + self.ttl

    def verify(self, token: str) -> dict[str, Any]:
        try:
            if type(token) is not str or len(token) > 8192: raise ValueError
            first, second, third = token.split(".")
            header, claims = json.loads(_b64decode(first)), json.loads(_b64decode(second))
            if type(header) is not dict or set(header) - {"alg", "kid", "typ"} or header.get("alg") != "RS256": raise ValueError
            if type(claims) is not dict: raise ValueError
            now = int(self.clock()); exp = claims.get("exp"); nbf = claims.get("nbf", 0); aud = claims.get("aud")
            audiences = [aud] if type(aud) is str else aud
            if (claims.get("iss") != self.issuer or type(audiences) is not list or self.audience not in audiences
                    or type(exp) is not int or exp <= now or exp > now + 86400
                    or type(nbf) is not int or nbf > now + 30 or claims.get("email") != self.email): raise ValueError
            if self.clock() >= self._expires or header.get("kid") not in self._keys: self._refresh()
            key = self._keys.get(header.get("kid"))
            if key is None: raise ValueError
            key.verify(_b64decode(third), (first + "." + second).encode("ascii"), padding.PKCS1v15(), SHA256())
            return claims
        except Exception:
            raise HTTPException(403, "request denied") from None


class SessionCodec:
    def __init__(self, key: bytes, *, ttl: int, clock=time.time):
        if type(key) is not bytes or len(key) < 32: raise RuntimeError("session key unavailable")
        self.key, self.ttl, self.clock = key, ttl, clock
    def issue(self, email: str) -> tuple[str, str]:
        csrf = secrets.token_urlsafe(24)
        raw = json.dumps({"email": email, "exp": int(self.clock()) + self.ttl, "csrf": csrf},
                         sort_keys=True, separators=(",", ":")).encode()
        return _b64encode(raw) + "." + _b64encode(hmac.new(self.key, raw, hashlib.sha256).digest()), csrf
    def verify(self, token: str) -> dict[str, Any]:
        try:
            payload, mac = token.split("."); raw = _b64decode(payload)
            if not hmac.compare_digest(_b64decode(mac), hmac.new(self.key, raw, hashlib.sha256).digest()): raise ValueError
            value = json.loads(raw)
            if (type(value) is not dict or set(value) != {"email", "exp", "csrf"} or value["email"] != ADMIN_EMAIL
                    or type(value["exp"]) is not int or value["exp"] <= int(self.clock())
                    or type(value["csrf"]) is not str): raise ValueError
            return value
        except Exception: raise HTTPException(403, "request denied") from None


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    count: StrictInt = Field(default=1, ge=1, le=20)
    edition: StrictStr = "personal"
    major_version: StrictInt = 1
    seat_limit: StrictInt = 2
    expires_at: None = None
    check_in_days: StrictInt = Field(default=30, ge=1, le=365)
class GiftIdBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    gift_id: StrictStr
class DeviceBody(GiftIdBody):
    device_id: StrictStr
class ClaimBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    claim_key: StrictStr; device_public_key: StrictStr
class CompleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    challenge_id: StrictStr; proof: StrictStr


async def _body(request: Request, model):
    raw = await request.body()
    if not raw or len(raw) > MAX_BODY: raise HTTPException(400, "invalid request")
    try: return model.model_validate_json(raw)
    except ValidationError: raise HTTPException(400, "invalid request") from None


def _security(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def create_public_gift_claim_app(*, authority: SignedAuthorityHTTPAdapter) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    @app.middleware("http")
    async def boundary(request, call_next):
        if request.url.path not in {"/v1/gifts/claim/challenge", "/v1/gifts/claim/complete"}: return _security(JSONResponse({"detail":"resource unavailable"},404))
        try: response = await call_next(request)
        except Exception: response = JSONResponse({"detail":"resource unavailable"},404)
        return _security(response)
    @app.post("/v1/gifts/claim/challenge")
    async def challenge(request: Request):
        value=await _body(request,ClaimBody)
        try:return {"state":"challenge_issued","challenge":authority.gift_claim_challenge(value.claim_key,value.device_public_key)}
        except Exception:raise HTTPException(404,"resource unavailable") from None
    @app.post("/v1/gifts/claim/complete")
    async def complete(request: Request):
        value=await _body(request,CompleteBody)
        try:return {"state":"activated","certificate":authority.gift_claim_complete(value.challenge_id,value.proof)}
        except Exception:raise HTTPException(404,"resource unavailable") from None
    return app


def create_gift_admin_app(*, authority: SignedAuthorityHTTPAdapter, access: AccessJWTVerifier,
                          sessions: SessionCodec) -> FastAPI:
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None,redirect_slashes=False)
    @app.middleware("http")
    async def boundary(request,call_next):
        try:response=await call_next(request)
        except HTTPException as exc:response=JSONResponse({"detail":"request denied" if exc.status_code in {401,403} else "resource unavailable"},exc.status_code)
        except Exception:response=JSONResponse({"detail":"resource unavailable"},404)
        return _security(response)
    def authenticate(request:Request, *, mutate=False):
        token=request.cookies.get("gm_gift_admin"); issued=None
        if token: identity=sessions.verify(token)
        else:
            assertion=request.headers.get("Cf-Access-Jwt-Assertion","");claims=access.verify(assertion)
            token,csrf=sessions.issue(claims["email"]);identity={"email":claims["email"],"csrf":csrf};issued=token
        if mutate:
            if request.headers.get("Origin") != ADMIN_ORIGIN or not hmac.compare_digest(request.headers.get("X-CSRF-Token",""),identity["csrf"]):raise HTTPException(403,"request denied")
        return identity,issued
    def result(payload,status=200,issued=None):
        response=JSONResponse(payload,status_code=status)
        if issued:response.set_cookie("gm_gift_admin",issued,max_age=sessions.ttl,secure=True,httponly=True,samesite="strict",path="/")
        return response
    @app.get("/")
    async def page(request:Request):
        identity,issued=authenticate(request);gifts=authority.list_gifts()
        rows="".join(f"<tr><td><code>{html.escape(g['gift_id'])}</code></td><td>{html.escape(g['status'])}</td><td>{g['device_allowance']}</td><td>{html.escape(g['created_at'])}</td><td><button data-action='recover' data-id='{html.escape(g['gift_id'])}'>恢復金鑰</button> <button data-action='devices' data-id='{html.escape(g['gift_id'])}'>裝置</button> <button data-action='revoke' data-id='{html.escape(g['gift_id'])}'>撤銷</button></td></tr>" for g in gifts)
        script="""const csrf=document.querySelector('meta[name=csrf]').content;const out=document.getElementById('result');function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}function keysFrom(j){const keys=[];if(j&&typeof j.claim_key==='string')keys.push(j.claim_key);for(const row of j?.results||[]){if(row?.ok&&typeof row.gift?.claim_key==='string')keys.push(row.gift.claim_key)}return keys}function show(j){const keys=keysFrom(j);if(!keys.length){out.innerHTML='<pre>'+escapeHtml(JSON.stringify(j,null,2))+'</pre>';return}out.innerHTML='<div class=notice><strong>請把下方「親友授權碼」私訊給對方</strong><p>對方安裝 GrowthMap 後，選擇「輸入授權碼解鎖」，貼上完整 GMG1 授權碼。首次啟用需要連網。</p></div>'+keys.map((k,i)=>'<section class=key-card><label>親友授權碼 '+(i+1)+'</label><code>'+escapeHtml(k)+'</code><div><button type=button data-copy="'+escapeHtml(k)+'">複製授權碼</button> <button type=button data-download="'+escapeHtml(k)+'" data-index="'+(i+1)+'">下載 TXT</button></div></section>').join('');out.querySelectorAll('[data-copy]').forEach(b=>b.onclick=async()=>{await navigator.clipboard.writeText(b.dataset.copy);b.textContent='已複製 ✓'});out.querySelectorAll('[data-download]').forEach(b=>b.onclick=()=>{const text='GrowthMap 親友授權碼\n\n'+b.dataset.download+'\n\n使用方式：安裝 GrowthMap → 輸入授權碼解鎖 → 貼上完整授權碼。首次啟用需要連網。\n';const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));a.download='GrowthMap-Gift-License-'+b.dataset.index+'.txt';a.click();URL.revokeObjectURL(a.href)});}async function call(path,body){out.textContent='處理中…';const r=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});const j=await r.json();show(j);if(!r.ok)throw new Error('request failed');return j}document.getElementById('create').onsubmit=async e=>{e.preventDefault();const n=Number(document.getElementById('count').value);await call('/v1/admin/gifts/create',{count:n,edition:'personal',major_version:1,seat_limit:2,expires_at:null,check_in_days:30});};document.querySelectorAll('button[data-action]').forEach(b=>b.onclick=async()=>{const action=b.dataset.action,id=b.dataset.id;if(action==='revoke'&&!confirm('確定撤銷這組親友授權？'))return;await call('/v1/admin/gifts/'+action,{gift_id:id});});"""
        response=HTMLResponse(f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name=csrf content='{html.escape(identity['csrf'])}'><title>GrowthMap Gift Admin</title><style>body{{font:16px system-ui;background:#0b1020;color:#eef2ff;margin:0;padding:32px}}main{{max-width:1100px;margin:auto}}section,table{{background:#151d35;border:1px solid #2b385d;border-radius:14px;padding:18px;margin:18px 0}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #2b385d}}button,input{{font:inherit;padding:8px 12px}}button{{cursor:pointer}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#070b15;padding:16px;border-radius:10px}}.notice{{border-left:4px solid #60a5fa;padding:12px 16px;background:#101a31}}.key-card{{display:grid;gap:12px}}.key-card code{{display:block;overflow-wrap:anywhere;background:#070b15;padding:14px;border-radius:8px;color:#a7f3d0;user-select:all}}</style></head><body><main><h1>GrowthMap 親友版管理</h1><p>預設 Personal v1、永久、2 台裝置。金鑰只會在建立或恢復時顯示一次。</p><section><form id='create'><label>生成數量（1–20） <input id='count' type='number' min='1' max='20' value='1' required></label> <button type='submit'>生成親友金鑰</button></form></section><table><thead><tr><th>Gift ID</th><th>狀態</th><th>裝置上限</th><th>建立時間</th><th>操作</th></tr></thead><tbody>{rows}</tbody></table><h2>授權碼／操作結果</h2><div id='result'><p>生成後，這裡會顯示可直接交給親友的 GMG1 授權碼。</p></div></main><script>{script}</script></body></html>")
        if issued:response.set_cookie("gm_gift_admin",issued,max_age=sessions.ttl,secure=True,httponly=True,samesite="strict",path="/")
        return response
    @app.get("/v1/admin/gifts")
    async def listing(request:Request):
        _,issued=authenticate(request);return result({"gifts":authority.list_gifts()},issued=issued)
    @app.post("/v1/admin/gifts/create")
    async def create(request:Request):
        _,issued=authenticate(request,mutate=True);value=await _body(request,CreateBody)
        if value.edition not in {"personal","pro","studio"} or value.major_version!=1 or value.seat_limit not in {1,2}:raise HTTPException(400,"invalid request")
        outcomes=[]
        # No retries: every index is attempted at most once and explicitly represented.
        for index in range(value.count):
            try:outcomes.append({"index":index,"ok":True,"gift":authority.create_gift(**value.model_dump(exclude={"count"}))})
            except Exception:outcomes.append({"index":index,"ok":False,"error":"creation_failed"});break
        return result({"complete":len(outcomes)==value.count and all(x["ok"] for x in outcomes),"results":outcomes},201 if all(x["ok"] for x in outcomes) else 503,issued)
    async def id_action(request, action):
        _,issued=authenticate(request,mutate=True);value=await _body(request,GiftIdBody);return result(action(value.gift_id),issued=issued)
    @app.post("/v1/admin/gifts/get")
    async def get(request:Request):return await id_action(request,authority.get_gift)
    @app.post("/v1/admin/gifts/recover")
    async def recover(request:Request):return await id_action(request,authority.recover_gift)
    @app.post("/v1/admin/gifts/revoke")
    async def revoke(request:Request):return await id_action(request,authority.revoke_gift)
    @app.post("/v1/admin/gifts/devices")
    async def devices(request:Request):return await id_action(request,lambda gift_id:{"devices":authority.list_gift_devices(gift_id)})
    @app.post("/v1/admin/gifts/devices/deactivate")
    async def deactivate(request:Request):
        _,issued=authenticate(request,mutate=True);value=await _body(request,DeviceBody)
        return result({"deactivated":authority.deactivate_gift_device(value.gift_id,value.device_id)},issued=issued)
    return app


def build_gift_bridge(config: GiftBridgeConfig, *, public: bool):
    key=config.session_hmac_key_file.read_bytes()
    adapter=SignedAuthorityHTTPAdapter(origin=config.authority_origin,authority_id=config.authority_id,
        audience=config.authority_audience,edge_identity=config.edge_identity,edge_source=config.edge_source,
        private_key_file=config.edge_private_key_file,signer_identity=config.signer_identity)
    if public:return create_public_gift_claim_app(authority=adapter)
    access=AccessJWTVerifier(issuer=config.access_issuer,audience=config.access_audience,email=config.access_email,jwks_url=config.access_jwks_url)
    return create_gift_admin_app(authority=adapter,access=access,sessions=SessionCodec(key,ttl=config.session_ttl_seconds))
