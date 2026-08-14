"""Public i18n API compatibility and complete provider-prompt contracts."""
import os
import tempfile
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROWTHMAP_ENV_FILE"] = os.path.join(tempfile.gettempdir(), "growthmap-i18n-contract.env")

import re
from fastapi.testclient import TestClient
from main import app
import ai.routes as ai_routes

TRADITIONAL_ONLY = re.compile(r"[專節點徑現與個為請這複體構議傳陣僅擇應該種從礎擴張對話歷顧問釐實]" )

class CaptureProvider:
    def __init__(self, calls): self.calls = calls
    async def complete(self, system, user, **kwargs):
        self.calls.append((system, user))
        if "content_blocks" in system:
            return '{"enriched_summary":"Neutral summary","content_blocks":[]}'
        if "suggest" in system.lower() or "子节点" in system or "子節點" in system:
            return '[{"title":"Neutral child","summary":"Neutral detail","node_type":"task"}]'
        return "Neutral reply"


def create_fixture(client):
    project = client.post("/api/projects", json={"name":"Neutral project","description":"Neutral description","goal":"Neutral goal"}).json()
    provider = client.post("/api/providers", json={"name":"Capture","provider_type":"mock","model_name":"capture"}).json()
    node = client.get(f"/api/nodes/{project['root_node_id']}").json()
    patched = client.patch(f"/api/nodes/{node['id']}", json={
        "expected_project_revision": project["revision"], "expected_revision": node["revision"],
        "summary":"Neutral summary",
    })
    assert patched.status_code == 200, patched.text
    project = client.get(f"/api/projects/{project['id']}").json()
    node = client.get(f"/api/nodes/{node['id']}").json()
    block = client.post(f"/api/nodes/{node['id']}/blocks", json={
        "expected_project_revision": project["revision"], "expected_node_revision": node["revision"],
        "block_type":"note", "content":{"title":"Neutral block","body":"Neutral body"},
    })
    assert block.status_code == 201, block.text
    return project, provider


def test_markdown_and_spec_endpoints_support_three_locales_and_omitted_is_traditional():
    with TestClient(app) as client:
        project, _ = create_fixture(client)
        expected = {
            "en": ("Goal", "Content blocks", "Specification", "Table of contents"),
            "zh-CN": ("目标", "内容区块", "规格文档", "目录"),
            "zh-TW": ("目標", "內容區塊", "規格文件", "目錄"),
        }
        for locale, labels in expected.items():
            markdown = client.get(f"/api/projects/{project['id']}/export", params={"locale":locale})
            spec = client.get(f"/api/projects/{project['id']}/export-spec", params={"locale":locale})
            assert markdown.status_code == spec.status_code == 200
            assert labels[0] in markdown.text and labels[1] in markdown.text
            assert labels[2] in spec.text and labels[3] in spec.text
        omitted_markdown = client.get(f"/api/projects/{project['id']}/export")
        omitted_spec = client.get(f"/api/projects/{project['id']}/export-spec")
        assert "目標" in omitted_markdown.text and "內容區塊" in omitted_markdown.text
        assert "規格文件" in omitted_spec.text and "目錄" in omitted_spec.text


def test_ai_request_models_omitted_locale_remains_traditional():
    assert ai_routes.ExpandRequest(node_id="n", provider_id="p").locale == "zh-TW"
    assert ai_routes.DeepenRequest(node_id="n", provider_id="p").locale == "zh-TW"
    assert ai_routes.ChatRequest(node_id="n", provider_id="p", message="m").locale == "zh-TW"


def test_expand_deepen_chat_capture_complete_framework_localization(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_routes, "get_provider", lambda _config: CaptureProvider(calls))
    with TestClient(app) as client:
        for locale in ("en", "zh-CN"):
            project, provider = create_fixture(client)
            base = {"node_id":project["root_node_id"], "provider_id":provider["id"]}
            calls.clear()
            assert client.post("/api/ai/expand", json={**base,"locale":locale,"count":1,"instruction":"Neutral instruction"}).status_code == 200
            assert client.post("/api/ai/deepen", json={**base,"locale":locale,"instruction":"Neutral instruction"}).status_code == 200
            assert client.post("/api/ai/chat", json={**base,"locale":locale,"message":"Neutral question","history":[{"role":"user","content":"Neutral history"}]}).status_code == 200
            assert len(calls) == 3
            # Context is persisted user/model data and may contain any language. Inspect only framework chrome.
            framework_parts = []
            for system, user in calls:
                payload = __import__("json").loads(user)
                payload.pop("context", None)
                framework_parts.extend((system, __import__("json").dumps(payload, ensure_ascii=False)))
            framework = "\n".join(framework_parts)
            if locale == "en": assert not re.search(r"[\u3400-\u9fff]", framework), framework
            else: assert not TRADITIONAL_ONLY.search(framework), f"matches={TRADITIONAL_ONLY.findall(framework)!r} codepoints={[hex(ord(c)) for c in TRADITIONAL_ONLY.findall(framework)]}\n{framework}"
