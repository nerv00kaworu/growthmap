"""Minimal signed HTTP client for the production Payment -> Authority edge contract."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
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
