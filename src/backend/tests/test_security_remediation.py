"""Security remediation regressions; all storage and database state is isolated."""
import asyncio
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROWTHMAP_ENV_FILE"] = os.path.join(tempfile.gettempdir(), "growthmap-security-test.env")

from fastapi.testclient import TestClient
from main import app
from api.routes import _is_local_client
from ai.providers.mock import MockProvider

ROOT = Path(__file__).resolve().parents[3]


class SecurityRemediationTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        from db.database import engine
        asyncio.run(engine.dispose())

    def test_frontend_storage_contract_has_no_secret_or_direct_provider_call(self):
        provider_source = (ROOT / "src/frontend/src/lib/llm-provider.ts").read_text(encoding="utf-8")
        api_source = (ROOT / "src/frontend/src/lib/api.ts").read_text(encoding="utf-8")
        self.assertNotIn("apiKey?:", provider_source)
        self.assertNotIn("baseUrl?:", provider_source)
        for forbidden in ("x-api-key", "dangerous-direct-browser-access", "generativelanguage.googleapis.com", "api.openai.com"):
            self.assertNotIn(forbidden, provider_source)
        self.assertNotIn("api_key: config", api_source)
        self.assertNotIn("base_url: config", api_source)

    def test_ai_schema_rejects_per_request_secret_overrides(self):
        with TestClient(app) as client:
            project = client.post("/api/projects", json={"name": "Strict AI schema"}).json()
            provider = client.post("/api/providers", json={"name": "Mock", "provider_type": "mock", "model_name": "demo"}).json()
            payload = {"node_id": project["root_node_id"], "provider_id": provider["id"], "api_key": "must-not-enter-schema", "base_url": "https://evil.invalid"}
            response = client.post("/api/ai/expand", json=payload)
            self.assertEqual(response.status_code, 422, response.text)
            schema = client.get("/openapi.json").json()["components"]["schemas"]
            serialized = json.dumps({name: schema[name] for name in ("ExpandRequest", "DeepenRequest", "ChatRequest", "TestConnectionRequest")})
            self.assertNotIn('"api_key"', serialized)
            self.assertNotIn('"base_url"', serialized)

    def test_ai_provider_id_path_and_test_connection(self):
        with TestClient(app) as client:
            project = client.post("/api/projects", json={"name": "Provider path"}).json()
            provider = client.post("/api/providers", json={"name": "Mock", "provider_type": "mock", "model_name": "demo"}).json()
            tested = client.post("/api/ai/test-connection", json={"provider_id": provider["id"]})
            self.assertEqual(tested.status_code, 200, tested.text)
            self.assertTrue(tested.json()["ok"])
            expanded = client.post("/api/ai/expand", json={"node_id": project["root_node_id"], "provider_id": provider["id"], "count": 2})
            self.assertEqual(expanded.status_code, 200, expanded.text)
            self.assertGreaterEqual(len(expanded.json()["suggestions"]), 1)

    def test_secret_write_boundary_and_response(self):
        self.assertFalse(_is_local_client("192.0.2.10"))
        self.assertTrue(_is_local_client("127.0.0.1"))
        with TestClient(app, client=("192.0.2.10", 50000)) as remote_client:
            remote_provider = remote_client.post("/api/providers", json={"name": "Remote", "provider_type": "openai_compatible", "secret_env_key": "GROWTHMAP_LLM_KEY_REMOTE_REJECT"}).json()
            rejected = remote_client.put(f"/api/providers/{remote_provider['id']}/secret", json={"api_key": "must-not-write"})
            self.assertEqual(rejected.status_code, 403, rejected.text)
        env_path = Path(os.environ["GROWTHMAP_ENV_FILE"])
        env_path.unlink(missing_ok=True)
        with TestClient(app) as client:
            provider = client.post("/api/providers", json={"name": "Secret", "provider_type": "openai_compatible", "secret_env_key": "GROWTHMAP_LLM_KEY_SECURITY_TEST", "model_name": "demo"}).json()
            response = client.put(f"/api/providers/{provider['id']}/secret", json={"api_key": "not-returned"})
            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b"")
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(env_path.stat().st_mode), 0o600)
            self.assertNotIn("not-returned", client.get("/api/providers").text)

    def test_secret_env_key_namespace_rejects_dangerous_create_patch_and_write(self):
        dangerous = ("PATH", "LD_PRELOAD", "PYTHONPATH", "DATABASE_URL", "GROWTHMAP_ENV_FILE", "LLM_API_KEY")
        with TestClient(app) as client:
            for env_key in dangerous:
                created = client.post("/api/providers", json={"name": env_key, "secret_env_key": env_key})
                self.assertEqual(created.status_code, 422, (env_key, created.text))
            provider = client.post("/api/providers", json={"name": "Namespaced", "provider_type": "openai_compatible", "secret_env_key": "GROWTHMAP_LLM_KEY_NAMESPACED"})
            self.assertEqual(provider.status_code, 201, provider.text)
            provider_id = provider.json()["id"]
            for env_key in dangerous:
                patched = client.patch(f"/api/providers/{provider_id}", json={"secret_env_key": env_key})
                self.assertEqual(patched.status_code, 422, (env_key, patched.text))
            from db.database import async_session
            from models.models import ProviderConfig
            async def seed_unsafe(provider_type: str):
                async with async_session() as session:
                    legacy = ProviderConfig(
                        name=f"Unsafe {provider_type}", provider_type=provider_type,
                        secret_env_key="LLM_API_KEY", auth_type="env", enabled=True,
                    )
                    session.add(legacy)
                    await session.commit()
                    await session.refresh(legacy)
                    return legacy.id
            for provider_type in ("openai_compatible", "mock"):
                legacy_id = asyncio.run(seed_unsafe(provider_type))
                rejected = client.put(f"/api/providers/{legacy_id}/secret", json={"api_key": "***"})
                self.assertEqual(rejected.status_code, 400, (provider_type, rejected.text))
                self.assertIn("rebind", rejected.text)
                self.assertIn("GROWTHMAP_LLM_KEY_", rejected.text)
                self.assertNotIn("legacy-secret-value", rejected.text)
                legacy_test = client.post("/api/ai/test-connection", json={"provider_id": legacy_id})
                self.assertEqual(legacy_test.status_code, 400, (provider_type, legacy_test.text))
                self.assertIn("rebind", legacy_test.text)
                project = client.post("/api/projects", json={"name": f"Unsafe AI {provider_type}"}).json()
                resolution = client.post("/api/ai/expand", json={
                    "node_id": project["root_node_id"], "provider_id": legacy_id,
                })
                self.assertEqual(resolution.status_code, 500, (provider_type, resolution.text))
                self.assertIn("rebind", resolution.text)
            valid = client.put(f"/api/providers/{provider_id}/secret", json={"api_key": "***"})
            self.assertEqual(valid.status_code, 204, valid.text)

    @unittest.skipUnless(os.name == "posix", "POSIX launcher policy is covered by the Windows desktop preflight on Windows")
    def test_launcher_rejects_ipv6_loopback_forms_under_declared_policy(self):
        for host in ("::1", "[::1]"):
            env = os.environ.copy()
            env.update({"GROWTHMAP_BACK_HOST": host, "GROWTHMAP_FRONT_HOST": "127.0.0.1"})
            result = subprocess.run([str(ROOT / "scripts/start_growthmap.sh"), "--foreground"], env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("non-loopback", result.stderr)

    def test_trusted_host_rejects_external_host_header(self):
        with TestClient(app) as client:
            response = client.get("/api", headers={"Host": "attacker.example"})
            self.assertEqual(response.status_code, 400)

    @unittest.skipUnless(os.name == "posix", "POSIX launcher policy is covered by the Windows desktop preflight on Windows")
    def test_launcher_refuses_non_loopback_before_prerequisites(self):
        env = os.environ.copy()
        env.update({"GROWTHMAP_BACK_HOST": "0.0.0.0", "GROWTHMAP_FRONT_HOST": "127.0.0.1"})
        result = subprocess.run([str(ROOT / "scripts/start_growthmap.sh"), "--foreground"], env=env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-loopback", result.stderr)
