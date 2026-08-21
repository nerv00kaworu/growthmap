"""Minimal API smoke coverage against an isolated in-memory SQLite database."""
import os
import tempfile
import unittest

# database.py creates its engine during import. This must happen before main is imported
# so the test can never read or mutate the developer's local growthmap.db.
# Override rather than setdefault: tests must never inherit an operator/developer DB URL.
_ISOLATED_DIR = tempfile.mkdtemp(prefix="growthmap-smoke-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_ISOLATED_DIR}/growthmap.db"
os.environ["GROWTHMAP_ENV_FILE"] = os.path.join(_ISOLATED_DIR, "growthmap.env")
os.environ["GROWTHMAP_CREDENTIAL_DIR"] = os.path.join(_ISOLATED_DIR, "credentials")

from fastapi.testclient import TestClient
from main import app


class GrowthMapApiSmokeTest(unittest.TestCase):
    def project_revision(self, client, project_id):
        return client.get(f"/api/projects/{project_id}").json()["revision"]

    def node_revision(self, client, node_id):
        return client.get(f"/api/nodes/{node_id}").json()["revision"]

    def create_node(self, client, project, **data):
        payload = {"expected_project_revision": self.project_revision(client, project["id"]), **data}
        if payload.get("parent_id"):
            payload["expected_parent_revision"] = self.node_revision(client, payload["parent_id"])
        return client.post(f"/api/projects/{project['id']}/nodes", json=payload)

    def patch_node(self, client, project_id, node_id, data):
        return client.patch(f"/api/nodes/{node_id}", json={"expected_project_revision": self.project_revision(client, project_id), "expected_revision": self.node_revision(client, node_id), **data})

    @classmethod
    def tearDownClass(cls):
        """Release test runs must close the isolated engine cleanly."""
        import asyncio
        from db.database import engine
        asyncio.run(engine.dispose())

    def test_authoring_health_and_openapi_exclude_player_runtime(self):
        with TestClient(app) as client:
            health = client.get("/api/health/deep")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json(), {"status": "ok", "surface": "authoring"})
            self.assertEqual(client.get("/api").json()["version"], "0.1.0-authoring.2")
            openapi = client.get("/openapi.json").json()
            self.assertEqual(openapi["info"]["version"], "0.1.0-authoring.2")
            paths = openapi["paths"]
            self.assertTrue("/api/projects" in paths)
            self.assertFalse(any(path.startswith("/api/player") for path in paths))

    def test_project_lifecycle_basics(self):
        with TestClient(app) as client:
            response = client.get("/api")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "running")

            response = client.get("/api/projects")
            self.assertEqual(response.status_code, 200)

            response = client.post(
                "/api/projects",
                json={"name": "Smoke project", "description": "Isolated API check"},
            )
            self.assertEqual(response.status_code, 201)
            project = response.json()
            self.assertTrue(project["id"])
            self.assertTrue(project["root_node_id"])

            response = client.get(f"/api/nodes/{project['root_node_id']}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["title"], "Smoke project")

            response = client.get(f"/api/projects/{project['id']}/nodes")
            self.assertEqual(response.status_code, 200)
            nodes = response.json()
            self.assertEqual(len(nodes), 1)
            self.assertEqual(nodes[0]["id"], project["root_node_id"])
            subtree = client.get(f"/api/nodes/{project['root_node_id']}/subtree").json()
            self.assertEqual(subtree["project_id"], project["id"])

    def test_node_formal_fields_round_trip_and_subtree_visibility(self):
        with TestClient(app) as client:
            project = client.post("/api/projects", json={"name": "Formal fields"}).json()
            node_id = project["root_node_id"]
            payload = {
                "description": "正式描述",
                "rules_text": "正式規則",
                "constraints_text": "正式限制",
                "examples_text": "正式範例",
                "questions_text": "正式問題",
                "decision_notes": "正式決策",
                "status": "active",
                "workflow_status": "review",
                "priority": 2,
                "confidence": 0.86,
                "file_paths": ["docs/spec.md", "assets/map.json"],
            }
            patched = self.patch_node(client, project["id"], node_id, payload)
            self.assertEqual(patched.status_code, 200)
            self.assertEqual({key: patched.json()[key] for key in payload}, payload)

            node = client.get(f"/api/nodes/{node_id}").json()
            subtree = client.get(f"/api/nodes/{node_id}/subtree").json()
            for key, value in payload.items():
                self.assertEqual(node[key], value)
                self.assertEqual(subtree[key], value)
            self.assertEqual(subtree["content_blocks"], [])

    def test_export_import_preserves_all_formal_node_fields(self):
        """Canonical authoring JSON round-trip must not silently drop editor fields."""
        with TestClient(app) as client:
            project = client.post("/api/projects", json={"name": "Export formal fields"}).json()
            node_id = project["root_node_id"]
            payload = {
                "description": "正式描述", "rules_text": "規則", "constraints_text": "限制",
                "examples_text": "範例", "questions_text": "問題", "decision_notes": "裁決",
                "status": "paused", "maturity": "stable", "workflow_status": "review",
                "priority": 7, "confidence": 0.91, "file_paths": ["docs/a.md", "src/b.py"],
                "tags": ["release", "canonical"],
            }
            self.assertEqual(self.patch_node(client, project["id"], node_id, payload).status_code, 200)
            exported = client.get(f"/api/projects/{project['id']}/export-json")
            self.assertEqual(exported.status_code, 200, exported.text)
            imported = client.post("/api/projects/import-json", json=exported.json())
            self.assertEqual(imported.status_code, 201, imported.text)
            restored = client.get(f"/api/nodes/{imported.json()['root_node_id']}").json()
            for key, value in payload.items():
                self.assertEqual(restored[key], value, key)

    def test_env_backed_provider_profile_never_returns_a_secret(self):
        with TestClient(app) as client:
            created = client.post(
                "/api/providers",
                json={
                    "name": "Local provider",
                    "provider_type": "openai_compatible",
                    "secret_env_key": "GROWTHMAP_LLM_KEY_NEVER_SENT_TO_BROWSER",
                    "model_name": "demo",
                },
            )
            self.assertEqual(created.status_code, 201)
            provider = created.json()
            self.assertEqual(provider["auth_type"], "env")
            self.assertEqual(provider["secret_env_key"], "GROWTHMAP_LLM_KEY_NEVER_SENT_TO_BROWSER")
            self.assertNotIn("api_key", provider)

            listed = client.get("/api/providers")
            self.assertEqual(listed.status_code, 200)
            self.assertNotIn("api_key", listed.json()[0])

            secret = client.put(f"/api/providers/{provider['id']}/secret", json={"api_key": "test-secret-value"})
            self.assertEqual(secret.status_code, 204)
            env_path = os.environ["GROWTHMAP_ENV_FILE"]
            with open(env_path, encoding="utf-8") as handle:
                self.assertIn('GROWTHMAP_LLM_KEY_NEVER_SENT_TO_BROWSER="test-secret-value"', handle.read())
            if os.name == "posix":
                self.assertEqual(os.stat(env_path).st_mode & 0o777, 0o600)

    def test_manual_agent_session_lifecycle_never_dispatches_ai(self):
        with TestClient(app) as client:
            project = client.post("/api/projects", json={"name": "Agent project"}).json()
            root_id = project["root_node_id"]
            created = client.post("/api/agent-sessions", json={
                "project_id": project["id"],
                "assigned_node_id": root_id,
                "objective": "人工審查節點風險",
                "mode": "one_shot",
            })
            self.assertEqual(created.status_code, 201)
            session = created.json()
            self.assertEqual(session["status"], "idle")

            invalid_scope = client.post("/api/agent-sessions", json={
                "project_id": project["id"], "assigned_node_id": root_id,
                "assigned_branch_root_id": root_id, "objective": "invalid",
            })
            self.assertEqual(invalid_scope.status_code, 400)

            active = client.patch(f"/api/agent-sessions/{session['id']}", json={"status": "active"})
            self.assertEqual(active.status_code, 200)
            review = client.patch(f"/api/agent-sessions/{session['id']}", json={"status": "waiting_review", "result_summary": "發現兩個待確認風險"})
            self.assertEqual(review.status_code, 200)
            completed = client.patch(f"/api/agent-sessions/{session['id']}", json={"status": "completed"})
            self.assertEqual(completed.status_code, 200)
            self.assertEqual(client.patch(f"/api/agent-sessions/{session['id']}", json={"status": "active"}).status_code, 400)

            listed = client.get(f"/api/agent-sessions?project_id={project['id']}&status=completed")
            self.assertEqual(len(listed.json()), 1)
            history = client.get(f"/api/agent-sessions/{session['id']}/history")
            self.assertTrue(any(row["action_type"] == "agent_session_created" for row in history.json()))

    def test_agent_artifacts_are_reviewed_before_transactional_writeback(self):
        with TestClient(app) as client:
            project = client.post("/api/projects", json={"name": "Artifact project"}).json()
            root_id = project["root_node_id"]
            session = client.post("/api/agent-sessions", json={
                "project_id": project["id"], "assigned_node_id": root_id,
                "objective": "提出可審核產物",
            }).json()
            client.patch(f"/api/agent-sessions/{session['id']}", json={"status": "active"})

            proposal = client.post(f"/api/agent-sessions/{session['id']}/artifacts", json={
                "target_node_id": root_id, "artifact_type": "create_child",
                "payload": {"title": "Approved child", "summary": "由人工核准"},
            })
            self.assertEqual(proposal.status_code, 201)
            artifact = proposal.json()
            self.assertEqual(artifact["status"], "pending")
            self.assertEqual(len(client.get(f"/api/nodes/{root_id}/children").json()), 0)

            approved = client.post(f"/api/agent-artifacts/{artifact['id']}/approve", json={"review_note": "可採用", "expected_project_revision": project["revision"], "expected_node_revision": 1})
            self.assertEqual(approved.status_code, 200)
            self.assertEqual(approved.json()["status"], "applied")
            self.assertEqual(client.get(f"/api/nodes/{root_id}/children").json()[0]["title"], "Approved child")
            self.assertEqual(client.post(f"/api/agent-artifacts/{artifact['id']}/approve", json={}).status_code, 400)

            rejected = client.post(f"/api/agent-sessions/{session['id']}/artifacts", json={
                "target_node_id": root_id, "artifact_type": "update_node", "payload": {"summary": "不採用"},
            }).json()
            self.assertEqual(client.post(f"/api/agent-artifacts/{rejected['id']}/reject", json={"review_note": "不符合範圍"}).json()["status"], "rejected")
            self.assertNotEqual(client.get(f"/api/nodes/{root_id}").json()["summary"], "不採用")

    def test_graph_edges_list_validate_and_delete_non_tree_relations(self):
        with TestClient(app) as client:
            project = client.post("/api/projects", json={"name": "Graph project"}).json()
            root_id = project["root_node_id"]
            other = self.create_node(client, project, **{"title": "Other", "parent_id": root_id}).json()
            edge = client.post("/api/edges", json={"expected_project_revision": self.project_revision(client, project["id"]), "from_node_id": root_id, "to_node_id": other["id"], "relation_type": "supports"})
            self.assertEqual(edge.status_code, 201)
            edge_id = edge.json()["id"]
            self.assertEqual(len(client.get(f"/api/projects/{project['id']}/edges").json()), 2)
            self.assertEqual(client.post("/api/edges", json={"expected_project_revision": self.project_revision(client, project["id"]), "from_node_id": root_id, "to_node_id": other["id"], "relation_type": "supports"}).status_code, 409)
            self.assertEqual(client.post("/api/edges", json={"expected_project_revision": self.project_revision(client, project["id"]), "from_node_id": root_id, "to_node_id": root_id, "relation_type": "supports"}).status_code, 400)
            self.assertEqual(client.post("/api/edges", json={"expected_project_revision": self.project_revision(client, project["id"]), "from_node_id": root_id, "to_node_id": other["id"], "relation_type": "unknown"}).status_code, 400)
            changed = client.patch(f"/api/edges/{edge_id}", json={"expected_project_revision": self.project_revision(client, project["id"]), "expected_revision": edge.json()["revision"], "weight": 0.65, "note": "人工確認的支持關係"})
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(changed.json()["weight"], 0.65)
            self.assertEqual(changed.json()["note"], "人工確認的支持關係")
            self.assertEqual(client.patch(f"/api/edges/{edge_id}", json={"expected_project_revision": self.project_revision(client, project["id"]), "expected_revision": changed.json()["revision"], "weight": 1.1}).status_code, 400)
            self.assertEqual(client.request("DELETE", f"/api/edges/{edge_id}", json={"expected_project_revision": self.project_revision(client, project["id"]), "expected_revision": changed.json()["revision"]}).status_code, 204)
            tree_edge = next(item for item in client.get(f"/api/projects/{project['id']}/edges").json() if item["relation_type"] == "child_of")
            self.assertEqual(client.request("DELETE", f"/api/edges/{tree_edge['id']}", json={"expected_project_revision": self.project_revision(client, project["id"]), "expected_revision": tree_edge["revision"]}).status_code, 400)

    def test_legacy_null_edge_fields_are_tolerated(self):
        """歷史 NULL 欄位不得再讓 edges/mainline-path 回傳 500。"""
        with TestClient(app) as client:
            project = client.post("/api/projects", json={"name": "Legacy graph project"}).json()
            root_id = project["root_node_id"]
            first = self.create_node(
                client, project,
                **{"title": "First", "parent_id": root_id},
            ).json()
            second = self.create_node(
                client, project,
                **{"title": "Second", "parent_id": root_id},
            ).json()

            # 用測試專用 session 模擬舊 DB 的空白 weight/note；主線唯一性另由 DB 約束測試。
            from db.database import async_session
            from sqlalchemy import update
            from models.models import Edge
            import asyncio

            async def seed_legacy_rows():
                async with async_session() as session:
                    await session.execute(
                        update(Edge)
                        .where(
                            Edge.project_id == project["id"],
                            Edge.from_node_id == root_id,
                            Edge.relation_type == "child_of",
                        )
                        .values(weight=None, note=None)
                    )
                    await session.commit()

            asyncio.run(seed_legacy_rows())

            edges = client.get(f"/api/projects/{project['id']}/edges")
            self.assertEqual(edges.status_code, 200, edges.text)
            tree_edges = [row for row in edges.json() if row["relation_type"] == "child_of"]
            self.assertEqual(len(tree_edges), 2)
            self.assertTrue(all(row["weight"] == 1.0 and row["note"] == "" for row in tree_edges))

            path = client.get(f"/api/projects/{project['id']}/mainline-path")
            self.assertEqual(path.status_code, 200, path.text)
            self.assertEqual([row["id"] for row in path.json()["path"]], [root_id, first["id"]])
            self.assertNotEqual(first["id"], second["id"])

    def test_import_normalizes_duplicate_mainlines_and_legacy_null_fields(self):
        with TestClient(app) as client:
            payload = {
                "project": {"name": "Imported graph", "root_node_id": "old-root"},
                "nodes": [
                    {"id": "old-root", "title": "Root"},
                    {"id": "old-a", "title": "A"},
                    {"id": "old-b", "title": "B"},
                ],
                "edges": [
                    {"from_node_id": "old-root", "to_node_id": "old-a", "relation_type": "child_of", "is_mainline": True, "weight": None, "note": None},
                    {"from_node_id": "old-root", "to_node_id": "old-b", "relation_type": "child_of", "is_mainline": True, "weight": None, "note": None},
                ],
                "content_blocks": [],
            }
            imported = client.post("/api/projects/import-json", json=payload)
            self.assertEqual(imported.status_code, 201, imported.text)
            project_id = imported.json()["id"]
            edges = client.get(f"/api/projects/{project_id}/edges").json()
            self.assertEqual(len(edges), 2)
            self.assertEqual(sum(row["is_mainline"] for row in edges), 1)
            self.assertTrue(all(row["weight"] == 1.0 and row["note"] == "" for row in edges))
            self.assertEqual(client.get(f"/api/projects/{project_id}/mainline-path").status_code, 200)

    def test_database_rejects_a_new_duplicate_mainline(self):
        with TestClient(app) as client:
            project = client.post("/api/projects", json={"name": "Mainline constraint"}).json()
            root_id = project["root_node_id"]
            self.create_node(client, project, **{"title": "First", "parent_id": root_id})
            second = self.create_node(client, project, **{"title": "Second", "parent_id": root_id}).json()

            # 繞過 API 的直接 SQL 寫入也必須被 DB trigger／partial unique index 阻擋。
            from db.database import async_session
            from sqlalchemy import update
            from sqlalchemy.exc import IntegrityError
            from models.models import Edge
            import asyncio

            async def force_duplicate():
                async with async_session() as session:
                    edge = (await session.execute(
                        __import__("sqlalchemy").select(Edge).where(
                            Edge.to_node_id == second["id"], Edge.relation_type == "child_of"
                        )
                    )).scalar_one()
                    edge.is_mainline = True
                    try:
                        await session.commit()
                    except IntegrityError:
                        await session.rollback()
                        return True
                    return False

            self.assertTrue(asyncio.run(force_duplicate()))

    def test_branch_create_compare_merge_and_archive(self):
        with TestClient(app) as client:
            project = client.post("/api/projects", json={"name": "Branch project"}).json()
            root_id = project["root_node_id"]
            child = self.create_node(
                client, project,
                **{"title": "Source", "parent_id": root_id},
            ).json()
            source_main = self.create_node(
                client, project,
                **{"title": "Source main", "parent_id": child["id"]},
            ).json()
            source_side = self.create_node(
                client, project,
                **{"title": "Source side", "parent_id": child["id"]},
            ).json()
            formal_payload = {
                "workflow_status": "review", "file_paths": ["docs/branch.md"],
                "priority": 4, "confidence": 0.78, "rules_text": "branch rule",
                "constraints_text": "branch constraint", "examples_text": "branch example",
                "questions_text": "branch question", "decision_notes": "branch decision",
            }
            self.assertEqual(self.patch_node(client, project["id"], child["id"], formal_payload).status_code, 200)

            created = client.post(
                f"/api/projects/{project['id']}/branches",
                json={"expected_project_revision": self.project_revision(client, project["id"]), "name": "Alternative", "source_node_id": child["id"]},
            )
            self.assertEqual(created.status_code, 201)
            branch = created.json()

            subtree = client.get(f"/api/branches/{branch['id']}/subtree")
            self.assertEqual(subtree.status_code, 200)
            branch_root = subtree.json()["tree"]
            self.assertEqual(branch_root["title"], "Source")
            for key, value in formal_payload.items():
                self.assertEqual(branch_root[key], value, key)
            branch_edges = client.get(f"/api/projects/{project['id']}/edges?relation_type=child_of").json()
            copied_child_edges = [row for row in branch_edges if row["from_node_id"] == branch_root["id"]]
            self.assertEqual(sum(row["is_mainline"] for row in copied_child_edges), 1)
            self.assertEqual({row["title"] for row in branch_root["children"]}, {"Source main", "Source side"})
            self.assertNotEqual(source_main["id"], source_side["id"])

            added = self.create_node(
                client, project,
                **{
                    "title": "Branch-only child",
                    "parent_id": branch_root["id"],
                    "branch_id": branch["id"],
                },
            )
            self.assertEqual(added.status_code, 201)
            self.assertEqual(added.json()["branch_id"], branch["id"])

            refreshed = client.get(f"/api/branches/{branch['id']}/subtree").json()["tree"]
            self.assertIn("Branch-only child", {row["title"] for row in refreshed["children"]})

            comparison = client.get(f"/api/branches/{branch['id']}/compare")
            self.assertEqual(comparison.status_code, 200)
            self.assertEqual(comparison.json()["diff"]["branch_node_count"], 4)

            invalid_target = client.post(
                f"/api/branches/{branch['id']}/merge",
                json={"target_node_id": branch_root["id"], "expected_project_revision": self.project_revision(client, project["id"]), "expected_revision": branch["revision"], "expected_target_revision": branch_root["revision"]},
            )
            self.assertEqual(invalid_target.status_code, 400)

            root_before_merge = client.get(f"/api/nodes/{root_id}").json()
            branch_nodes_before = {row["id"]: row["revision"] for row in [refreshed, *refreshed["children"]]}
            project_before_merge = self.project_revision(client, project["id"])
            merged = client.post(
                f"/api/branches/{branch['id']}/merge",
                json={"target_node_id": root_id, "expected_project_revision": project_before_merge, "expected_revision": branch["revision"], "expected_target_revision": root_before_merge["revision"]},
            )
            self.assertEqual(merged.status_code, 200)
            self.assertTrue(merged.json()["ok"])
            self.assertEqual(self.project_revision(client, project["id"]), project_before_merge + 1)
            self.assertEqual(client.get(f"/api/nodes/{root_id}").json()["revision"], root_before_merge["revision"] + 1)
            merged_branch = client.get(f"/api/branches/{branch['id']}").json()
            self.assertEqual(merged_branch["status"], "merged")
            self.assertEqual(merged_branch["revision"], branch["revision"] + 1)
            nodes_after = {row["id"]: row for row in client.get(f"/api/projects/{project['id']}/nodes").json()}
            for node_id, revision in branch_nodes_before.items():
                self.assertEqual(nodes_after[node_id]["revision"], revision + 1)
                self.assertIsNone(client.get(f"/api/nodes/{node_id}").json()["branch_id"])
            merged_edge = next(row for row in client.get(f"/api/projects/{project['id']}/edges?relation_type=child_of").json() if row["from_node_id"] == root_id and row["to_node_id"] == branch_root["id"])
            self.assertEqual(merged_edge["revision"], 1)

            archived = client.post(
                f"/api/projects/{project['id']}/branches",
                json={"expected_project_revision": self.project_revision(client, project["id"]), "name": "Archive me", "source_node_id": child["id"]},
            ).json()
            archived_response = client.request("DELETE", f"/api/branches/{archived['id']}", json={"expected_project_revision": self.project_revision(client, project["id"]), "expected_revision": archived["revision"]})
            self.assertEqual(archived_response.status_code, 204)
            self.assertEqual(client.get(f"/api/branches/{archived['id']}").json()["status"], "archived")
            self.assertEqual(
                client.post(f"/api/branches/{archived['id']}/merge", json={"target_node_id": root_id, "expected_project_revision": self.project_revision(client, project["id"]), "expected_revision": archived["revision"] + 1, "expected_target_revision": client.get(f"/api/nodes/{root_id}").json()["revision"]}).status_code,
                400,
            )

            active_branches = client.get(f"/api/projects/{project['id']}/branches")
            self.assertEqual(active_branches.status_code, 200)
            self.assertFalse(any(row["id"] == archived["id"] for row in active_branches.json()))

            all_branches = client.get(f"/api/projects/{project['id']}/branches?include_inactive=true")
            self.assertEqual(all_branches.status_code, 200)
            self.assertEqual(next(row for row in all_branches.json() if row["id"] == archived["id"])["status"], "archived")

            history = client.get(f"/api/branches/{archived['id']}/history")
            self.assertEqual(history.status_code, 200)
            self.assertTrue(any(row["action_type"] == "archive_branch" for row in history.json()))


if __name__ == "__main__":
    unittest.main()
