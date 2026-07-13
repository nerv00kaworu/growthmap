"""Minimal API smoke coverage against an isolated in-memory SQLite database."""
import os
import tempfile
import unittest

# database.py creates its engine during import. This must happen before main is imported
# so the test can never read or mutate the developer's local growthmap.db.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROWTHMAP_ENV_FILE"] = os.path.join(tempfile.gettempdir(), "growthmap-test.env")

from fastapi.testclient import TestClient
from main import app


class GrowthMapApiSmokeTest(unittest.TestCase):
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

    def test_env_backed_provider_profile_never_returns_a_secret(self):
        with TestClient(app) as client:
            created = client.post(
                "/api/providers",
                json={
                    "name": "Local provider",
                    "provider_type": "openai_compatible",
                    "secret_env_key": "NEVER_SENT_TO_BROWSER",
                    "model_name": "demo",
                },
            )
            self.assertEqual(created.status_code, 201)
            provider = created.json()
            self.assertEqual(provider["auth_type"], "env")
            self.assertEqual(provider["secret_env_key"], "NEVER_SENT_TO_BROWSER")
            self.assertNotIn("api_key", provider)

            listed = client.get("/api/providers")
            self.assertEqual(listed.status_code, 200)
            self.assertNotIn("api_key", listed.json()[0])

            secret = client.put(f"/api/providers/{provider['id']}/secret", json={"api_key": "test-secret-value"})
            self.assertEqual(secret.status_code, 204)
            env_path = os.environ["GROWTHMAP_ENV_FILE"]
            with open(env_path, encoding="utf-8") as handle:
                self.assertIn('NEVER_SENT_TO_BROWSER="test-secret-value"', handle.read())
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

            approved = client.post(f"/api/agent-artifacts/{artifact['id']}/approve", json={"review_note": "可採用"})
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
            other = client.post(f"/api/projects/{project['id']}/nodes", json={"title": "Other", "parent_id": root_id}).json()
            edge = client.post("/api/edges", json={"from_node_id": root_id, "to_node_id": other["id"], "relation_type": "supports"})
            self.assertEqual(edge.status_code, 201)
            edge_id = edge.json()["id"]
            self.assertEqual(len(client.get(f"/api/projects/{project['id']}/edges").json()), 2)
            self.assertEqual(client.post("/api/edges", json={"from_node_id": root_id, "to_node_id": other["id"], "relation_type": "supports"}).status_code, 409)
            self.assertEqual(client.post("/api/edges", json={"from_node_id": root_id, "to_node_id": root_id, "relation_type": "supports"}).status_code, 400)
            self.assertEqual(client.post("/api/edges", json={"from_node_id": root_id, "to_node_id": other["id"], "relation_type": "unknown"}).status_code, 400)
            changed = client.patch(f"/api/edges/{edge_id}", json={"weight": 0.65, "note": "人工確認的支持關係"})
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(changed.json()["weight"], 0.65)
            self.assertEqual(changed.json()["note"], "人工確認的支持關係")
            self.assertEqual(client.patch(f"/api/edges/{edge_id}", json={"weight": 1.1}).status_code, 400)
            self.assertEqual(client.delete(f"/api/edges/{edge_id}").status_code, 204)
            tree_edge = next(item for item in client.get(f"/api/projects/{project['id']}/edges").json() if item["relation_type"] == "child_of")
            self.assertEqual(client.delete(f"/api/edges/{tree_edge['id']}").status_code, 400)

    def test_branch_create_compare_merge_and_archive(self):
        with TestClient(app) as client:
            project = client.post("/api/projects", json={"name": "Branch project"}).json()
            root_id = project["root_node_id"]
            child = client.post(
                f"/api/projects/{project['id']}/nodes",
                json={"title": "Source", "parent_id": root_id},
            ).json()

            created = client.post(
                f"/api/projects/{project['id']}/branches",
                json={"name": "Alternative", "source_node_id": child["id"]},
            )
            self.assertEqual(created.status_code, 201)
            branch = created.json()

            subtree = client.get(f"/api/branches/{branch['id']}/subtree")
            self.assertEqual(subtree.status_code, 200)
            branch_root = subtree.json()["tree"]
            self.assertEqual(branch_root["title"], "Source")

            added = client.post(
                f"/api/projects/{project['id']}/nodes",
                json={
                    "title": "Branch-only child",
                    "parent_id": branch_root["id"],
                    "branch_id": branch["id"],
                },
            )
            self.assertEqual(added.status_code, 201)
            self.assertEqual(added.json()["branch_id"], branch["id"])

            refreshed = client.get(f"/api/branches/{branch['id']}/subtree").json()["tree"]
            self.assertEqual(refreshed["children"][0]["title"], "Branch-only child")

            comparison = client.get(f"/api/branches/{branch['id']}/compare")
            self.assertEqual(comparison.status_code, 200)
            self.assertEqual(comparison.json()["diff"]["branch_node_count"], 2)

            invalid_target = client.post(
                f"/api/branches/{branch['id']}/merge",
                json={"target_node_id": branch_root["id"]},
            )
            self.assertEqual(invalid_target.status_code, 400)

            merged = client.post(
                f"/api/branches/{branch['id']}/merge",
                json={"target_node_id": root_id},
            )
            self.assertEqual(merged.status_code, 200)
            self.assertTrue(merged.json()["ok"])
            self.assertEqual(client.get(f"/api/branches/{branch['id']}").json()["status"], "merged")

            archived = client.post(
                f"/api/projects/{project['id']}/branches",
                json={"name": "Archive me", "source_node_id": child["id"]},
            ).json()
            archived_response = client.delete(f"/api/branches/{archived['id']}")
            self.assertEqual(archived_response.status_code, 204)
            self.assertEqual(client.get(f"/api/branches/{archived['id']}").json()["status"], "archived")
            self.assertEqual(
                client.post(f"/api/branches/{archived['id']}/merge", json={"target_node_id": root_id}).status_code,
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
