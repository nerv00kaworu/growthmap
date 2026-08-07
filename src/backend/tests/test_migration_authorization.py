import hashlib, hmac, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).parents[1]
MARKER_KEYS = ("schemaVersion", "kind", "backupId", "sha256", "size", "projects", "fromVersion", "toVersion", "createdAt")


def trial(path):
    now = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps({"schema_version": 1, "installation_id": "test-installation", "started_at": now, "last_seen_at": now}))


def base_env(tmp_path):
    return {**os.environ, "GROWTHMAP_DESKTOP_MODE": "1", "GROWTHMAP_FRESH_INSTALL": "0", "GROWTHMAP_MIGRATION_REQUIRED": "1", "GROWTHMAP_SESSION_TOKEN": "session-secret", "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path/'db.sqlite'}", "GROWTHMAP_LICENSE_FILE": str(tmp_path/"license.json"), "GROWTHMAP_TRIAL_STATE_FILE": str(tmp_path/"trial.json")}


def run(tmp_path, extra):
    env = {**base_env(tmp_path), **extra}
    token, nonce, mode = env["GROWTHMAP_SESSION_TOKEN"], "V" * 43, "free"
    env.update(GROWTHMAP_STARTUP_VERDICT_MODE=mode, GROWTHMAP_STARTUP_VERDICT_NONCE=nonce, GROWTHMAP_STARTUP_VERDICT_MAC=hmac.new(token.encode(), f"growthmap-startup-v1:{mode}:{nonce}".encode(), hashlib.sha256).hexdigest())
    code = "from fastapi.testclient import TestClient\nfrom main import app\nwith TestClient(app): pass\n"
    return subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, text=True, capture_output=True)


def marker_fixture(tmp_path):
    import sqlite3
    backups = tmp_path / "backups"
    backups.mkdir()
    backup = backups / "backup-2026-07-28T00-00-00-000Z-11111111-1111-4111-8111-111111111111.db"
    connection = sqlite3.connect(backup)
    connection.execute("create table evidence(id integer)")
    connection.commit()
    connection.close()
    digest, size, created = hashlib.sha256(backup.read_bytes()).hexdigest(), backup.stat().st_size, datetime.now(timezone.utc).isoformat()
    manifest = {"format": "growthmap-backup-v1", "createdAt": created, "file": backup.name, "size": size, "projects": 0, "sha256": digest, "durability": {"fileFsync": True, "directoryFsync": True}}
    Path(str(backup) + ".json").write_text(json.dumps(manifest, separators=(",", ":")))
    doc = {"schemaVersion": 1, "kind": "pre-migration-backup", "backupId": backup.name, "sha256": digest, "size": size, "projects": 0, "fromVersion": "1.0.0", "toVersion": "1.0.0", "createdAt": created}
    marker = tmp_path / "migration-authorization.json"
    marker.write_text(json.dumps(doc, separators=(",", ":")))
    return marker, backup, doc


def signed_env(marker, doc, token="session-secret"):
    canonical = json.dumps({key: doc[key] for key in MARKER_KEYS}, separators=(",", ":"), ensure_ascii=False)
    return {"GROWTHMAP_MIGRATION_MARKER_FILE": str(marker), "GROWTHMAP_MIGRATION_MARKER_MAC": hmac.new(token.encode(), canonical.encode(), hashlib.sha256).hexdigest()}


def test_inherited_boolean_or_missing_mac_never_authorizes_migration(tmp_path):
    trial(tmp_path / "trial.json")
    marker, _, doc = marker_fixture(tmp_path)
    assert run(tmp_path, {"GROWTHMAP_MIGRATION_AUTHORIZED": "1"}).returncode != 0
    assert run(tmp_path, {"GROWTHMAP_MIGRATION_MARKER_FILE": str(marker)}).returncode != 0
    assert run(tmp_path, {"GROWTHMAP_MIGRATION_MARKER_FILE": str(marker), "GROWTHMAP_MIGRATION_MARKER_MAC": "0" * 64}).returncode != 0


def test_valid_exact_marker_succeeds_consumes_and_replay_fails(tmp_path):
    trial(tmp_path / "trial.json")
    marker, _, doc = marker_fixture(tmp_path)
    env = signed_env(marker, doc)
    first = run(tmp_path, env)
    assert first.returncode == 0, first.stderr
    assert not marker.exists()
    assert run(tmp_path, env).returncode != 0


def test_mutated_marker_timestamp_durability_and_manifest_shape_fail(tmp_path):
    for mutation in ("marker", "timestamp", "durability", "extra", "missing"):
        case = tmp_path / mutation
        case.mkdir()
        trial(case / "trial.json")
        marker, backup, doc = marker_fixture(case)
        env = signed_env(marker, doc)
        if mutation == "marker":
            doc["projects"] = 1
            marker.write_text(json.dumps(doc, separators=(",", ":")))
        else:
            manifest_path = Path(str(backup) + ".json")
            manifest = json.loads(manifest_path.read_text())
            if mutation == "timestamp": manifest["createdAt"] = 17
            if mutation == "durability": manifest["durability"] = None
            if mutation == "extra": manifest["extra"] = True
            if mutation == "missing": del manifest["projects"]
            manifest_path.write_text(json.dumps(manifest, separators=(",", ":")))
        assert run(case, {**env, "GROWTHMAP_LICENSE_FILE": str(case/"license.json"), "GROWTHMAP_TRIAL_STATE_FILE": str(case/"trial.json"), "DATABASE_URL": f"sqlite+aiosqlite:///{case/'db.sqlite'}"}).returncode != 0, mutation
