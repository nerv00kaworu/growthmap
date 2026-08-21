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

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:////tmp/growthmap-security-remediation.db"
os.environ["GROWTHMAP_ENV_FILE"] = os.path.join(tempfile.gettempdir(), "growthmap-security-test.env")

from fastapi.testclient import TestClient
from main import app
from api.routes import _is_local_client
from ai.providers.mock import MockProvider

ROOT = Path(__file__).resolve().parents[3]


def select_provider(client, provider):
    response=client.put("/api/providers/selection",json={"provider_id":provider["id"],"expected_selection_revision":provider["selection_revision"]})
    assert response.status_code==200,response.text
    selected=response.json()
    stale=client.put("/api/providers/selection",json={"provider_id":provider["id"],"expected_selection_revision":provider["selection_revision"]})
    assert stale.status_code==409 and stale.json()["detail"]["code"]=="LLM_SELECTION_STALE"
    return {**provider,"selection_revision":selected["selection_revision"]}


class SecurityRemediationTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        from db.database import engine
        asyncio.run(engine.dispose())

    def test_frontend_storage_contract_has_no_secret_or_direct_provider_call(self):
        provider_source = (ROOT / "src/frontend/src/lib/llm-provider.ts").read_text()
        api_source = (ROOT / "src/frontend/src/lib/api.ts").read_text()
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
            provider = select_provider(client,client.post("/api/providers", json={"name": "Mock", "provider_type": "mock", "model_name": "demo"}).json())
            tested = client.post("/api/ai/test-connection", json={"provider_id": provider["id"],"provider_revision":provider["revision"],"selection_revision":provider["selection_revision"]})
            self.assertEqual(tested.status_code, 200, tested.text)
            self.assertTrue(tested.json()["ok"])
            expanded = client.post("/api/ai/expand", json={"node_id": project["root_node_id"], "provider_id": provider["id"], "provider_revision":provider["revision"], "selection_revision":provider["selection_revision"], "count": 2})
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
                    from models.models import ProviderSelection
                    selection=await session.get(ProviderSelection,1)
                    selection.provider_id=legacy.id
                    selection.selection_revision+=1
                    await session.commit()
                    return legacy.id, selection.selection_revision
            for provider_type in ("openai_compatible", "mock"):
                legacy_id, legacy_selection_revision = asyncio.run(seed_unsafe(provider_type))
                rejected = client.put(f"/api/providers/{legacy_id}/secret", json={"api_key": "***"})
                self.assertEqual(rejected.status_code, 400, (provider_type, rejected.text))
                self.assertIn("rebind", rejected.text)
                self.assertIn("GROWTHMAP_LLM_KEY_", rejected.text)
                self.assertNotIn("legacy-secret-value", rejected.text)
                legacy_version=client.get("/api/providers").json()
                legacy_version=next(x["revision"] for x in legacy_version if x["id"]==legacy_id)
                legacy_test = client.post("/api/ai/test-connection", json={"provider_id": legacy_id,"provider_revision":legacy_version,"selection_revision":legacy_selection_revision})
                self.assertEqual(legacy_test.status_code, 400, (provider_type, legacy_test.text))
                self.assertIn("rebind", legacy_test.text)
                project = client.post("/api/projects", json={"name": f"Unsafe AI {provider_type}"}).json()
                resolution = client.post("/api/ai/expand", json={
                    "node_id": project["root_node_id"], "provider_id": legacy_id, "provider_revision":legacy_version, "selection_revision":legacy_selection_revision,
                })
                self.assertEqual(resolution.status_code, 400, (provider_type, resolution.text))
                detail = resolution.json()["detail"]
                self.assertEqual(detail["code"], "LLM_CONFIGURATION_ERROR")
                self.assertIn("rebind", detail["message"])
                self.assertRegex(detail["request_id"], r"^[0-9a-f]{16}$")
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

def test_dedicated_model_patch_is_strict_trimmed_and_bounded():
    with TestClient(app) as client:
        provider=client.post("/api/providers",json={"name":"Model patch","provider_type":"mock","model_name":"old"}).json(); url=f"/api/providers/{provider['id']}/model"
        updated=client.patch(url,json={"model_name":"  new-model  "}); assert updated.status_code==200 and updated.json()["model_name"]=="new-model"
        for body in ({"model_name":""},{"model_name":"x"*129},{"model_name":"ok","endpoint":"https://secret.invalid"}): assert client.patch(url,json=body).status_code==422

def test_generic_provider_patch_has_no_phantom_query_and_rejects_extras():
    with TestClient(app) as client:
        provider=client.post('/api/providers',json={'name':'Before','provider_type':'mock'}).json()
        patched=client.patch(f"/api/providers/{provider['id']}",json={'name':'After','enabled':False})
        assert patched.status_code==200 and patched.json()['name']=='After' and patched.json()['enabled'] is False
        assert client.patch(f"/api/providers/{provider['id']}",json={'unknown':'x'}).status_code==422
        operation=next(x for x in client.get('/openapi.json').json()['paths']['/api/providers/{provider_id}']['patch']['parameters'] if x['name']=='provider_id')
        assert operation['in']=='path'
        assert not [x for x in client.get('/openapi.json').json()['paths']['/api/providers/{provider_id}']['patch']['parameters'] if x['in']=='query']

def test_provider_revision_exact_upper_bound_and_exhaustion(monkeypatch):
    from db.database import async_session
    from models.models import ProviderConfig
    from models.provider_authority import MAX_PROVIDER_REVISION
    async def set_revision(pid, value):
        async with async_session() as db:
            provider=await db.get(ProviderConfig,pid);provider.revision=value;await db.commit()
    with TestClient(app) as client:
        provider=client.post('/api/providers',json={'name':'Bounded','provider_type':'openai_compatible','secret_env_key':'GROWTHMAP_LLM_KEY_BOUNDED'}).json();pid=provider['id']
        asyncio.run(set_revision(pid,MAX_PROVIDER_REVISION-1))
        last=client.patch(f'/api/providers/{pid}',json={'name':'At max'})
        assert last.status_code==200 and last.json()['revision']==MAX_PROVIDER_REVISION
        listed=client.get('/api/providers').json()
        exact=next(x['revision'] for x in listed if x['id']==pid)
        assert type(exact) is int and exact==MAX_PROVIDER_REVISION
        for method,path,body in (
            ('patch',f'/api/providers/{pid}',{'name':'overflow'}),
            ('patch',f'/api/providers/{pid}/model',{'model_name':'overflow'}),
            ('put',f'/api/providers/{pid}/secret',{'api_key':'must-not-write'}),
        ):
            response=getattr(client,method)(path,json=body)
            assert response.status_code==409 and response.json()['detail']['code']=='PROVIDER_REVISION_EXHAUSTED'
        assert os.getenv('GROWTHMAP_LLM_KEY_BOUNDED') is None
        current=next(x for x in client.get('/api/providers').json() if x['id']==pid)
        assert current['revision']==MAX_PROVIDER_REVISION and current['name']=='At max'


def test_profile_version_mismatch_aborts_before_provider_construction(monkeypatch):
    from ai import routes
    called=[]
    monkeypatch.setattr(routes,'get_provider',lambda config: called.append(config))
    with TestClient(app) as client:
        provider=select_provider(client,client.post('/api/providers',json={'name':'Exact','provider_type':'mock'}).json())
        result=client.post('/api/ai/test-connection',json={'provider_id':provider['id'],'provider_revision':provider['revision']+1,'selection_revision':provider['selection_revision']})
        assert result.status_code==409 and result.json()['detail']['code']=='LLM_PROFILE_CHANGED' and not called
