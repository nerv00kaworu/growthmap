"""Minimal signed HTTP client for the production Payment -> Authority edge contract."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class AuthorityHTTPError(RuntimeError):
    pass


class SignedAuthorityHTTPAdapter:
    """Expose only entitlement/revocation operations over the reviewed edge contract."""

    _PATHS = {
        "create_external_entitlement": "/v1/service/entitlements",
        "read_external_entitlement_acknowledgement": "/v1/service/entitlements/read",
        "revoke_external_entitlement": "/v1/service/revocations",
        "read_external_revocation_acknowledgement": "/v1/service/revocations/read",
        "issue_activation_challenge": "/v1/service/activation/challenge",
        "activate_challenge": "/v1/service/activation/complete",
        "create_gift": "/v1/service/gifts/create",
        "list_gifts": "/v1/service/gifts/list",
        "get_gift": "/v1/service/gifts/get",
        "recover_gift": "/v1/service/gifts/recover",
        "revoke_gift": "/v1/service/gifts/revoke",
        "list_gift_devices": "/v1/service/gifts/devices",
        "deactivate_gift_device": "/v1/service/gifts/devices/deactivate",
        "gift_claim_challenge": "/v1/service/gifts/claim/challenge",
        "gift_claim_complete": "/v1/service/gifts/claim/complete",
    }

    def __init__(self, *, origin: str, authority_id: str, audience: str,
                 edge_identity: str, edge_source: str, private_key_file: Path,
                 signer_identity: dict, timeout_seconds: float = 5.0):
        parsed = urllib.parse.urlsplit(origin)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path
                or parsed.query or parsed.fragment or parsed.username or parsed.password
                or parsed.port is None):
            raise AuthorityHTTPError("authority configuration invalid")
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 30:
            raise AuthorityHTTPError("authority configuration invalid")
        try:
            key = serialization.load_pem_private_key(Path(private_key_file).read_bytes(), password=None)
        except Exception:
            raise AuthorityHTTPError("authority credential unavailable") from None
        if not isinstance(key, Ed25519PrivateKey):
            raise AuthorityHTTPError("authority credential unavailable")
        required = {"authority_id", "key_id", "generation", "public_key_sha256", "attestation"}
        if type(signer_identity) is not dict or set(signer_identity) != required or signer_identity["authority_id"] != authority_id:
            raise AuthorityHTTPError("authority configuration invalid")
        self.origin = origin
        self.authority_id = authority_id
        self.audience = audience
        self.edge_identity = edge_identity
        self.edge_source = edge_source
        self.signer_identity = dict(signer_identity)
        self._key = key
        self._timeout = float(timeout_seconds)

    def handshake(self):
        result = self._request("GET", "/v1/authority/identity", None)
        public = {key: self.signer_identity[key] for key in ("authority_id", "key_id", "generation", "public_key_sha256")}
        if type(result) is not dict or any(result.get(key) != value for key, value in public.items()) or result.get("status") != "active":
            raise AuthorityHTTPError("authority identity mismatch")
        return dict(self.signer_identity)

    def _request(self, method: str, path: str, body: dict | None):
        raw = b"" if body is None else json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            nonce = secrets.token_hex(32)
            digest = hashlib.sha256(raw).hexdigest()
            values = (method, path, digest, timestamp, nonce, self.audience, self.authority_id,
                      self.edge_identity, self.edge_source)
            statement = b"growthmap-authority-edge-v1\0" + b"\0".join(value.encode("ascii") for value in values)
            headers.update({
                "Content-Type": "application/json",
                "X-Authority-Timestamp": timestamp,
                "X-Authority-Nonce": nonce,
                "X-Authority-Audience": self.audience,
                "X-Authority-Id": self.authority_id,
                "X-Authority-Service-Auth": base64.b64encode(self._key.sign(statement)).decode("ascii"),
            })
        request = urllib.request.Request(self.origin + path, data=None if body is None else raw,
                                         headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                if response.status != 200 or response.headers.get_content_type() != "application/json":
                    raise AuthorityHTTPError("authority request failed")
                payload = response.read(65_537)
                if len(payload) > 65_536:
                    raise AuthorityHTTPError("authority response invalid")
                return json.loads(payload)
        except AuthorityHTTPError:
            raise
        except (OSError, ValueError, urllib.error.URLError):
            raise AuthorityHTTPError("authority request failed") from None

    def _post(self, operation: str, body: dict):
        return self._request("POST", self._PATHS[operation], body)

    def create_external_entitlement(self, **body):
        return self._post("create_external_entitlement", body)

    def read_external_entitlement_acknowledgement(self, **body):
        return self._post("read_external_entitlement_acknowledgement", body | {"authority_id": self.authority_id})

    def revoke_external_entitlement(self, **body):
        return self._post("revoke_external_entitlement", body)

    def read_external_revocation_acknowledgement(self, **body):
        return self._post("read_external_revocation_acknowledgement", body | {"authority_id": self.authority_id})

    @staticmethod
    def _exact(value, keys):
        if type(value) is not dict or set(value) != set(keys):
            raise AuthorityHTTPError("authority response invalid")

    def issue_activation_challenge(self, *, license_id: str, device_public_key: str):
        result = self._post("issue_activation_challenge", {
            "license_id": license_id, "device_public_key": device_public_key})
        self._exact(result, ("state", "challenge"))
        challenge = result["challenge"]
        self._exact(challenge, ("challenge_id", "nonce", "license_id", "device_public_key"))
        if (result["state"] != "challenge_issued" or challenge["license_id"] != license_id
                or challenge["device_public_key"] != device_public_key
                or type(challenge["challenge_id"]) is not str
                or re.fullmatch(r"gmc_[a-f0-9]{32}", challenge["challenge_id"]) is None
                or type(challenge["nonce"]) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", challenge["nonce"]) is None):
            raise AuthorityHTTPError("authority response invalid")
        return challenge

    def activate_challenge(self, *, challenge_id: str, proof: str, expected_flow_kind: str = "payment"):
        if expected_flow_kind != "payment":
            raise AuthorityHTTPError("authority request invalid")
        result = self._post("activate_challenge", {"challenge_id": challenge_id, "proof": proof})
        self._exact(result, ("state", "certificate"))
        certificate = result["certificate"]
        required = ("schema_version", "certificate_type", "product", "edition", "license_id",
                    "activation_id", "major_version", "device_allowance", "device_id",
                    "device_public_key", "issued_at", "expires_at", "revoked_at",
                    "max_active_projects", "next_check_in_at", "signature")
        self._exact(certificate, required)
        if (result["state"] != "activated" or certificate["schema_version"] != 2
                or certificate["certificate_type"] != "growthmap_device_activation"
                or certificate["product"] != "growthmap"
                or certificate["edition"] not in {"personal", "pro", "studio"}
                or certificate["major_version"] != 1
                or certificate["device_allowance"] not in {1, 2}
                or any(type(certificate[key]) is not str for key in
                       ("license_id", "activation_id", "device_id", "device_public_key",
                        "issued_at", "next_check_in_at", "signature"))):
            raise AuthorityHTTPError("authority response invalid")
        return certificate


# Gift response validation is deliberately exact: an Authority version drift fails closed.
def _gift_public(adapter, value):
    keys = ("gift_id", "license_id", "status", "edition", "major_version", "device_allowance",
            "expires_at", "check_in_days", "created_at", "rotated_at", "revoked_at")
    adapter._exact(value, keys)
    if (type(value["gift_id"]) is not str or re.fullmatch(r"[0-9a-f-]{36}", value["gift_id"]) is None
            or type(value["license_id"]) is not str or value["status"] not in {"active", "revoked"}
            or value["edition"] not in {"personal", "pro", "studio"} or value["major_version"] != 1
            or value["device_allowance"] not in {1, 2} or type(value["check_in_days"]) is not int
            or type(value["created_at"]) is not str):
        raise AuthorityHTTPError("authority response invalid")
    return value


def _claim_result(adapter, result, claim_key, device_public_key):
    adapter._exact(result, ("state", "challenge")); challenge=result["challenge"]
    adapter._exact(challenge, ("challenge_id", "nonce", "license_id", "device_public_key"))
    if (result["state"] != "challenge_issued" or challenge["device_public_key"] != device_public_key
            or re.fullmatch(r"gmc_[a-f0-9]{32}", challenge["challenge_id"] or "") is None
            or type(claim_key) is not str): raise AuthorityHTTPError("authority response invalid")
    return challenge


def _create_gift(self, **policy):
    value=self._post("create_gift", policy); claim=value.pop("claim_key", None)
    _gift_public(self, value)
    if type(claim) is not str or re.fullmatch(r"GMG1\.[0-9a-f-]{36}\.[A-Za-z0-9_-]{32}", claim) is None:
        raise AuthorityHTTPError("authority response invalid")
    return value | {"claim_key": claim}
def _list_gifts(self):
    value=self._post("list_gifts", {}); self._exact(value,("gifts",))
    if type(value["gifts"]) is not list or len(value["gifts"])>10000: raise AuthorityHTTPError("authority response invalid")
    return [_gift_public(self,item) for item in value["gifts"]]
def _get_gift(self,gift_id): return _gift_public(self,self._post("get_gift",{"gift_id":gift_id}))
def _recover_gift(self,gift_id):
    value=self._post("recover_gift",{"gift_id":gift_id});claim=value.pop("claim_key",None);_gift_public(self,value)
    if type(claim) is not str or re.fullmatch(r"GMG1\.[0-9a-f-]{36}\.[A-Za-z0-9_-]{32}",claim) is None:raise AuthorityHTTPError("authority response invalid")
    return value|{"claim_key":claim}
def _revoke_gift(self,gift_id): return _gift_public(self,self._post("revoke_gift",{"gift_id":gift_id}))
def _list_gift_devices(self,gift_id):
    value=self._post("list_gift_devices",{"gift_id":gift_id});self._exact(value,("devices",))
    if type(value["devices"]) is not list:raise AuthorityHTTPError("authority response invalid")
    for item in value["devices"]:
        self._exact(item,("device_id","device_public_key","activated_at","deactivated_at"))
        if type(item["device_id"]) is not str or type(item["device_public_key"]) is not str:raise AuthorityHTTPError("authority response invalid")
    return value["devices"]
def _deactivate_gift_device(self,gift_id,device_id):
    value=self._post("deactivate_gift_device",{"gift_id":gift_id,"device_id":device_id});self._exact(value,("deactivated",))
    if type(value["deactivated"]) is not bool:raise AuthorityHTTPError("authority response invalid")
    return value["deactivated"]
def _gift_claim_challenge(self,claim_key,device_public_key):return _claim_result(self,self._post("gift_claim_challenge",{"claim_key":claim_key,"device_public_key":device_public_key}),claim_key,device_public_key)
def _gift_claim_complete(self,challenge_id,proof):
    result=self._post("gift_claim_complete",{"challenge_id":challenge_id,"proof":proof});self._exact(result,("state","certificate"))
    if result["state"]!="activated":raise AuthorityHTTPError("authority response invalid")
    # Reuse the complete certificate validator without issuing another request.
    certificate=result["certificate"];required=("schema_version","certificate_type","product","edition","license_id","activation_id","major_version","device_allowance","device_id","device_public_key","issued_at","expires_at","revoked_at","max_active_projects","next_check_in_at","signature");self._exact(certificate,required)
    if certificate["schema_version"]!=2 or certificate["certificate_type"]!="growthmap_device_activation":raise AuthorityHTTPError("authority response invalid")
    return certificate
SignedAuthorityHTTPAdapter.create_gift=_create_gift
SignedAuthorityHTTPAdapter.list_gifts=_list_gifts
SignedAuthorityHTTPAdapter.get_gift=_get_gift
SignedAuthorityHTTPAdapter.recover_gift=_recover_gift
SignedAuthorityHTTPAdapter.revoke_gift=_revoke_gift
SignedAuthorityHTTPAdapter.list_gift_devices=_list_gift_devices
SignedAuthorityHTTPAdapter.deactivate_gift_device=_deactivate_gift_device
SignedAuthorityHTTPAdapter.gift_claim_challenge=_gift_claim_challenge
SignedAuthorityHTTPAdapter.gift_claim_complete=_gift_claim_complete
