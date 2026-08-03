"""Cryptographically verify a source-only index of production review evidence.

A valid result is necessary but insufficient evidence and never authorizes runtime.
Private keys, credentials, and environment secrets are outside this module.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_MAX_BYTES = 32768
_MAX_DEPTH = 8
_ERROR = "production dependency review manifest unavailable"
_SCHEMA = "growthmap-production-dependency-review"
_VERSION = 2
_DOMAIN = b"growthmap-production-dependency-approval-v2\x00"
DEPENDENCIES = (
    "facilitator", "finality", "authority_transport", "session_boundary",
    "monitoring_backup_gate",
)
_ROLES = ("producer", "security_reviewer", "release_reviewer")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?")
_CONTEXT = re.compile(r"[a-z0-9](?:[a-z0-9._:/-]{0,126}[a-z0-9])?")
_METADATA = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
             "st_size", "st_mtime_ns", "st_ctime_ns")
_PIN_KEYS = ("artifact_sha256", "config_sha256", "evidence_sha256")


@dataclass(frozen=True)
class VerifiedReviewerApproval:
    reviewer_id: str
    reviewer_key_sha256: str
    reviewer_role: str
    reviewer_organization: str
    signature: str


@dataclass(frozen=True)
class DependencyEvidence:
    artifact_sha256: str
    config_sha256: str
    evidence_sha256: str
    approvals: tuple[VerifiedReviewerApproval, ...]


@dataclass(frozen=True)
class ValidatedProductionEvidence:
    schema: str
    version: int
    environment: str
    release_commit: str
    ceremony_context_id: str
    public_config_sha256: str
    policy_id: str
    policy_sha256: str
    producer_id: str
    producer_key_sha256: str
    producer_organization: str
    dependencies: Mapping[str, DependencyEvidence]
    manifest_sha256: str


def _pairs(items):
    result, exact, folded = {}, set(), set()
    for key, value in items:
        if type(key) is not str:
            raise ValueError
        collision = unicodedata.normalize("NFKC", key).casefold()
        if key in exact or collision in folded:
            raise ValueError
        exact.add(key); folded.add(collision); result[key] = value
    return result


def _bounded(value, depth=1):
    if depth > _MAX_DEPTH:
        raise ValueError
    if type(value) is dict:
        for key, child in value.items():
            if type(key) is not str: raise ValueError
            _bounded(child, depth + 1)
    elif type(value) is list:
        for child in value: _bounded(child, depth + 1)
    elif type(value) not in (str, int):
        raise ValueError


def _exact(value, keys):
    if type(value) is not dict or set(value) != set(keys): raise ValueError


def _digest(value): return type(value) is str and _SHA256.fullmatch(value) is not None


def _identity(value): return type(value) is str and _ID.fullmatch(value) is not None


def _secure(value):
    return (stat.S_ISREG(value.st_mode) and value.st_uid == os.geteuid() and
            value.st_nlink == 1 and value.st_mode & 0o077 == 0 and
            1 <= value.st_size <= _MAX_BYTES)


def _metadata(value): return tuple(getattr(value, field) for field in _METADATA)


def _load(path):
    fd = None
    failed = False
    raw = None
    try:
        if os.name != "posix" or not hasattr(os, "geteuid"): raise ValueError
        nofollow, nonblock = getattr(os, "O_NOFOLLOW", None), getattr(os, "O_NONBLOCK", None)
        if not isinstance(nofollow, int) or not nofollow or not isinstance(nonblock, int) or not nonblock: raise ValueError
        pathname = os.fspath(path)
        fd = os.open(pathname, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow | nonblock)
        opened, linked = os.fstat(fd), os.lstat(pathname)
        if stat.S_ISLNK(linked.st_mode) or not _secure(opened) or not _secure(linked) or _metadata(opened) != _metadata(linked): raise ValueError
        raw = b""
        while len(raw) <= _MAX_BYTES:
            chunk = os.read(fd, _MAX_BYTES + 1 - len(raw))
            if not chunk: break
            raw += chunk
        reopened, relinked = os.fstat(fd), os.lstat(pathname)
        if (len(raw) != opened.st_size or len(raw) > _MAX_BYTES or stat.S_ISLNK(relinked.st_mode) or
                not _secure(reopened) or not _secure(relinked) or _metadata(opened) != _metadata(reopened) or
                _metadata(opened) != _metadata(relinked)): raise ValueError
    except Exception:
        failed = True
    if fd is not None:
        try:
            os.close(fd)
        except Exception:
            failed = True
    if failed or raw is None:
        raise RuntimeError(_ERROR) from None
    return raw


def _canonical_policy(policy_id, identities):
    serial = {"policy_id": policy_id, "identities": {
        identity: {"public_key": base64.b64encode(value[0]).decode("ascii"),
                   "roles": [value[2]], "organization": value[3]}
        for identity, value in sorted(identities.items())
    }}
    return json.dumps(serial, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _snapshot_inputs(expected_release_commit, expected_public_config_sha256,
                     expected_ceremony_context_id, expected_dependencies, trusted_policy):
    if type(expected_release_commit) is not str or not _COMMIT.fullmatch(expected_release_commit): raise ValueError
    if not _digest(expected_public_config_sha256): raise ValueError
    if type(expected_ceremony_context_id) is not str or not _CONTEXT.fullmatch(expected_ceremony_context_id): raise ValueError
    if type(expected_dependencies) is not dict or set(expected_dependencies) != set(DEPENDENCIES): raise ValueError
    pins, all_digests = {}, set()
    for name in DEPENDENCIES:
        item = expected_dependencies[name]; _exact(item, _PIN_KEYS); copied = {}
        for key in _PIN_KEYS:
            value = item[key]
            if not _digest(value) or value in all_digests: raise ValueError
            all_digests.add(value); copied[key] = value
        pins[name] = MappingProxyType(copied)
    _exact(trusted_policy, ("policy_id", "identities"))
    policy_id, source = trusted_policy["policy_id"], trusted_policy["identities"]
    if not _identity(policy_id) or type(source) is not dict or len(source) < 3: raise ValueError
    identities, fingerprints = {}, set()
    for identity, value in source.items():
        if not _identity(identity): raise ValueError
        _exact(value, ("public_key", "roles", "organization"))
        raw_key, roles, organization = value["public_key"], value["roles"], value["organization"]
        if (type(raw_key) is not bytes or len(raw_key) != 32 or type(roles) is not list or len(roles) != 1 or
                roles[0] not in _ROLES or not _identity(organization)): raise ValueError
        key = bytes(raw_key); Ed25519PublicKey.from_public_bytes(key)
        fingerprint = hashlib.sha256(key).hexdigest()
        if fingerprint in fingerprints: raise ValueError
        fingerprints.add(fingerprint)
        identities[identity] = (key, fingerprint, roles[0], organization)
    role_set = {value[2] for value in identities.values()}
    if set(_ROLES) - role_set: raise ValueError
    policy_sha256 = hashlib.sha256(_canonical_policy(policy_id, identities)).hexdigest()
    return (expected_release_commit, expected_public_config_sha256, expected_ceremony_context_id,
            MappingProxyType(pins), policy_id, policy_sha256, MappingProxyType(identities))


def _approval_statement(*, release_commit, ceremony_context_id, public_config_sha256,
                        policy_id, policy_sha256, producer_id, producer_key_sha256,
                        dependency_name, pins, reviewer_id, reviewer_key_sha256, reviewer_role):
    statement = {
        "schema": _SCHEMA, "version": _VERSION, "environment": "production",
        "release_commit": release_commit, "ceremony_context_id": ceremony_context_id,
        "public_config_sha256": public_config_sha256, "policy_id": policy_id,
        "policy_sha256": policy_sha256, "producer_id": producer_id,
        "producer_key_sha256": producer_key_sha256, "dependency_name": dependency_name,
        **{key: pins[key] for key in _PIN_KEYS}, "reviewer_id": reviewer_id,
        "reviewer_key_sha256": reviewer_key_sha256, "reviewer_role": reviewer_role,
    }
    return _DOMAIN + json.dumps(statement, sort_keys=True, separators=(",", ":")).encode("utf-8")


def approval_statement(**kwargs):
    """Public signing wrapper; verification uses the private canonical builder."""
    return _approval_statement(**kwargs)


def load_production_review_manifest(path, *, expected_release_commit: str,
                                    expected_public_config_sha256: str,
                                    expected_ceremony_context_id: str,
                                    expected_dependencies: Mapping[str, Mapping[str, str]],
                                    trusted_policy: Mapping[str, object]
                                    ) -> ValidatedProductionEvidence:
    """Verify caller-pinned policy approvals; success does not authorize startup."""
    try:
        release, public_digest, context, pins, policy_id, policy_digest, identities = _snapshot_inputs(
            expected_release_commit, expected_public_config_sha256, expected_ceremony_context_id,
            expected_dependencies, trusted_policy)
        raw = _load(path)
        data = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_pairs); _bounded(data)
        if raw != json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"): raise ValueError
        _exact(data, ("schema", "version", "environment", "release_commit", "ceremony_context_id",
                      "public_config_sha256", "policy_id", "policy_sha256", "producer_id",
                      "producer_key_sha256", "dependencies"))
        if (type(data["schema"]) is not str or data["schema"] != _SCHEMA or type(data["version"]) is not int or
                data["version"] != _VERSION or type(data["environment"]) is not str or data["environment"] != "production" or
                type(data["release_commit"]) is not str or data["release_commit"] != release or
                type(data["ceremony_context_id"]) is not str or data["ceremony_context_id"] != context or
                data["public_config_sha256"] != public_digest or data["policy_id"] != policy_id or
                data["policy_sha256"] != policy_digest or not _identity(data["producer_id"]) or
                data["producer_id"] not in identities): raise ValueError
        producer_id = data["producer_id"]
        producer_key, producer_fingerprint, producer_role, producer_org = identities[producer_id]
        if producer_role != "producer" or data["producer_key_sha256"] != producer_fingerprint: raise ValueError
        dependencies = data["dependencies"]; _exact(dependencies, DEPENDENCIES)
        validated, seen_signatures, seen_digests = {}, set(), set()
        for name in DEPENDENCIES:
            item = dependencies[name]; _exact(item, (*_PIN_KEYS, "approvals"))
            for key in _PIN_KEYS:
                if item[key] != pins[name][key] or not _digest(item[key]) or item[key] in seen_digests: raise ValueError
                seen_digests.add(item[key])
            approvals = item["approvals"]
            if type(approvals) is not list or len(approvals) != 2: raise ValueError
            values, reviewer_keys, reviewer_ids, reviewer_orgs, selected_roles = [], set(), set(), set(), set()
            for approval in approvals:
                _exact(approval, ("reviewer_id", "reviewer_key_sha256", "reviewer_role", "signature"))
                reviewer_id, fingerprint, role, encoded = (approval["reviewer_id"], approval["reviewer_key_sha256"],
                                                            approval["reviewer_role"], approval["signature"])
                if (not _identity(reviewer_id) or reviewer_id not in identities or type(encoded) is not str): raise ValueError
                reviewer_key, expected_fingerprint, expected_role, organization = identities[reviewer_id]
                if (role not in ("security_reviewer", "release_reviewer") or role != expected_role or
                        fingerprint != expected_fingerprint or reviewer_key == producer_key or
                        organization == producer_org or fingerprint in reviewer_keys or
                        reviewer_id in reviewer_ids or organization in reviewer_orgs): raise ValueError
                try: signature = base64.b64decode(encoded, validate=True)
                except Exception: raise ValueError from None
                if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != encoded or signature in seen_signatures: raise ValueError
                Ed25519PublicKey.from_public_bytes(reviewer_key).verify(signature, _approval_statement(
                    release_commit=release, ceremony_context_id=context, public_config_sha256=public_digest,
                    policy_id=policy_id, policy_sha256=policy_digest, producer_id=producer_id,
                    producer_key_sha256=producer_fingerprint, dependency_name=name, pins=pins[name],
                    reviewer_id=reviewer_id, reviewer_key_sha256=fingerprint, reviewer_role=role))
                reviewer_keys.add(fingerprint); reviewer_ids.add(reviewer_id); reviewer_orgs.add(organization)
                selected_roles.add(role); seen_signatures.add(signature)
                values.append(VerifiedReviewerApproval(reviewer_id, fingerprint, role, organization, encoded))
            if selected_roles != {"security_reviewer", "release_reviewer"}: raise ValueError
            validated[name] = DependencyEvidence(item["artifact_sha256"], item["config_sha256"],
                                                  item["evidence_sha256"], tuple(values))
        return ValidatedProductionEvidence(_SCHEMA, _VERSION, "production", release, context, public_digest,
                                            policy_id, policy_digest, producer_id, producer_fingerprint,
                                            producer_org, MappingProxyType(validated), hashlib.sha256(raw).hexdigest())
    except Exception:
        raise RuntimeError(_ERROR) from None
