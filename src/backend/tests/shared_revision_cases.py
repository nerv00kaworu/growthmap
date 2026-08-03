"""Focused F3 shared-revision contract and independent-session concurrency tests."""
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

F3_DATABASE_URL = f"sqlite+aiosqlite:///{tempfile.mkdtemp(prefix='growthmap-f3-')}/db.sqlite"
os.environ["DATABASE_URL"] = F3_DATABASE_URL
os.environ["APP_ENV"] = "test"
os.environ["GROWTHMAP_HUMAN_CONTROL_TOKEN"] = "human-test"
sys.path.insert(0, str(Path(__file__).parents[1]))

from fastapi.testclient import TestClient
from main import app


class SharedRevisionContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from db.database import engine
        if str(engine.url) != F3_DATABASE_URL:
            raise unittest.SkipTest("module imported after another process-global test app; run this focused isolation suite separately")
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.human = {"Authorization": "Bearer human-test"}

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def project(self):
        p = self.client.post("/api/projects", json={"name": "F3 concurrency"}).json()
        return p, self.client.get(f"/api/nodes/{p['root_node_id']}").json()

    def grant(self, project_id):
        response = self.client.post("/api/agent-port/grants", headers=self.human, json={
            "project_id": project_id,
            "permission": "write",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "label": "f3",
            "agent_identity": "concurrency-test",
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["token"]

    def test_openapi_inventory_requires_revision_contract(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        inventory = {
            ("/api/projects/{project_id}", "patch"), ("/api/projects/{project_id}", "delete"),
            ("/api/projects/{project_id}/nodes", "post"), ("/api/nodes/{node_id}", "patch"),
            ("/api/nodes/{node_id}", "delete"), ("/api/edges", "post"),
            ("/api/edges/{edge_id}", "patch"), ("/api/edges/{edge_id}", "delete"),
            ("/api/edges/{edge_id}/promote-mainline", "post"),
            ("/api/nodes/{parent_id}/promote-child/{child_id}", "post"),
            ("/api/nodes/{node_id}/move", "post"), ("/api/nodes/{node_id}/reparent", "post"),
            ("/api/nodes/{node_id}/blocks", "post"), ("/api/blocks/{block_id}", "patch"),
            ("/api/blocks/{block_id}", "delete"), ("/api/projects/{project_id}/branches", "post"),
            ("/api/branches/{branch_id}/merge", "post"), ("/api/branches/{branch_id}", "delete"),
        }
        for path, method in inventory:
            operation = paths[path][method]
            self.assertIn("requestBody", operation, (path, method))
            schema = operation["requestBody"]["content"]["application/json"]["schema"]
            if "$ref" in schema:
                name = schema["$ref"].rsplit("/", 1)[-1]
                schema = self.client.get("/openapi.json").json()["components"]["schemas"][name]
            self.assertIn("expected_project_revision", schema.get("required", []), (path, method, schema))

    def test_stale_edge_patch_is_no_write(self):
        project, root = self.project()
        child = self.client.post(f"/api/projects/{project['id']}/nodes", json={
            "expected_project_revision": project["revision"], "expected_parent_revision": root["revision"], "title": "child", "parent_id": root["id"]
        }).json()
        current = self.client.get(f"/api/projects/{project['id']}").json()
        edge = self.client.post("/api/edges", json={
            "expected_project_revision": current["revision"], "from_node_id": root["id"],
            "to_node_id": child["id"], "relation_type": "supports", "note": "before"
        }).json()
        stale = current["revision"]
        current = self.client.get(f"/api/projects/{project['id']}").json()
        winner = self.client.patch(f"/api/edges/{edge['id']}", json={
            "expected_project_revision": current["revision"], "expected_revision": edge["revision"], "note": "winner"
        })
        self.assertEqual(winner.status_code, 200, winner.text)
        loser = self.client.patch(f"/api/edges/{edge['id']}", json={
            "expected_project_revision": stale, "expected_revision": edge["revision"], "note": "stale-overwrite"
        })
        self.assertEqual(loser.status_code, 409, loser.text)
        rows = self.client.get(f"/api/projects/{project['id']}/edges").json()
        self.assertEqual(next(row for row in rows if row["id"] == edge["id"])["note"], "winner")

    def race(self, calls):
        barrier = Barrier(len(calls))
        def run(call):
            # Separate HTTP clients create separate dependency/session instances.
            # Do not run multiple app lifespan managers concurrently: startup DB
            # initialization itself is not part of the mutation race under test.
            independent_client = TestClient(app)
            barrier.wait()
            return call(independent_client)
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            return [future.result() for future in [pool.submit(run, call) for call in calls]]

    def test_true_independent_gui_vs_gui_concurrency(self):
        project, root = self.project()
        body = {"expected_project_revision": project["revision"], "expected_revision": root["revision"]}
        statuses = self.race([
            lambda c: c.patch(f"/api/nodes/{root['id']}", json={**body, "summary": "gui-a"}).status_code,
            lambda c: c.patch(f"/api/nodes/{root['id']}", json={**body, "summary": "gui-b"}).status_code,
        ])
        self.assertEqual(sorted(statuses), [200, 409], statuses)
        verify = TestClient(app)
        self.assertIn(verify.get(f"/api/nodes/{root['id']}").json()["summary"], {"gui-a", "gui-b"})

    def test_true_independent_gui_vs_agent_concurrency(self):
        project, root = self.project()
        token = self.grant(project["id"])
        gui = lambda c: c.patch(f"/api/nodes/{root['id']}", json={
            "expected_project_revision": project["revision"], "expected_revision": root["revision"], "summary": "gui"
        }).status_code
        agent = lambda c: c.post("/agent/v1/batch", headers={"Authorization": f"Bearer {token}"}, json={
            "expected_project_revision": project["revision"], "idempotency_key": "gui-agent-race",
            "operations": [{"op": "update_node", "node_id": root["id"], "expected_revision": root["revision"], "fields": {"summary": "agent"}}]
        }).status_code
        statuses = self.race([gui, agent])
        self.assertEqual(sorted(statuses), [200, 409], statuses)
        verify = TestClient(app)
        self.assertIn(verify.get(f"/api/nodes/{root['id']}").json()["summary"], {"gui", "agent"})

    def test_concurrent_identical_idempotency_key_has_one_canonical_write(self):
        project, root = self.project()
        token = self.grant(project["id"])
        payload = {
            "expected_project_revision": project["revision"], "idempotency_key": "same-key-race",
            "operations": [{"op": "update_node", "node_id": root["id"], "expected_revision": root["revision"], "fields": {"summary": "once"}}]
        }
        def same(c):
            response = c.post("/agent/v1/batch", headers={"Authorization": f"Bearer {token}"}, json=payload)
            return response.status_code, response.json()
        results = self.race([same, same])
        statuses = [status for status, _ in results]
        self.assertIn(sorted(statuses), ([200, 200], [200, 409]), results)
        if statuses == [200, 200]:
            self.assertEqual(results[0][1], results[1][1])
        else:
            conflict = results[statuses.index(409)][1]["detail"]
            self.assertIn(conflict["code"], {"IDEMPOTENCY_IN_PROGRESS", "REVISION_CONFLICT"})
        verify = TestClient(app)
        current = verify.get(f"/api/projects/{project['id']}").json()
        node = verify.get(f"/api/nodes/{root['id']}").json()
        self.assertEqual(current["revision"], project["revision"] + 1)
        self.assertEqual(node["revision"], root["revision"] + 1)
        self.assertEqual(node["summary"], "once")

    def test_proposal_event_readback_races_are_single_durable_rows(self):
        project, root = self.project()
        token = self.grant(project["id"])
        auth = {"Authorization": f"Bearer {token}"}
        cases = [
            ("/agent/v1/events", {
                "idempotency_key": "event-race", "target_node_id": root["id"],
                "event_type": "progress", "message": "one", "payload": {"stage": "test"},
            }, "events"),
            ("/agent/v1/readbacks", {
                "idempotency_key": "readback-race", "target_node_id": root["id"],
                "summary": "one", "files": ["a.py"], "tests": [{"name": "unit", "status": "passed"}],
            }, "readbacks"),
            ("/agent/v1/proposals", {
                "idempotency_key": "proposal-race", "expected_project_revision": project["revision"],
                "target_node_id": root["id"], "title": "one",
                "operations": [{"op": "update_node", "node_id": root["id"],
                                "expected_revision": root["revision"], "fields": {"summary": "proposal-once"}}],
            }, "proposals"),
        ]
        proposal_id = None
        for path, payload, collection in cases:
            def submit(c, path=path, payload=payload):
                response = c.post(path, headers=auth, json=payload)
                return response.status_code, response.json()
            results = self.race([submit, submit])
            self.assertEqual([status for status, _ in results], [201, 201], results)
            self.assertEqual(results[0][1], results[1][1])
            changed = dict(payload)
            changed["idempotency_key"] = payload["idempotency_key"]
            changed["message" if collection == "events" else "summary" if collection == "readbacks" else "title"] = "different"
            mismatch = TestClient(app).post(path, headers=auth, json=changed)
            self.assertEqual(mismatch.status_code, 409, mismatch.text)
            activity = TestClient(app).get(f"/api/agent-port/activity?project_id={project['id']}", headers=self.human).json()
            self.assertEqual(len(activity[collection]), 1, activity)
            if collection == "proposals": proposal_id = results[0][1]["proposal_id"]

        before = TestClient(app).get(f"/api/projects/{project['id']}").json()["revision"]
        approve = lambda c: (lambda r: (r.status_code, r.json()))(c.post(
            f"/api/agent-port/proposals/{proposal_id}/approve", headers=self.human, json={}))
        approvals = self.race([approve, approve])
        self.assertEqual([status for status, _ in approvals], [200, 200], approvals)
        self.assertTrue(all(body["status"] == "approved" for _, body in approvals))
        verify = TestClient(app)
        self.assertEqual(verify.get(f"/api/projects/{project['id']}").json()["revision"], before + 1)
        node = verify.get(f"/api/nodes/{root['id']}").json()
        self.assertEqual(node["summary"], "proposal-once")
        self.assertEqual(node["revision"], root["revision"] + 1)
        activity = verify.get(f"/api/agent-port/activity?project_id={project['id']}", headers=self.human).json()
        self.assertEqual(activity["proposals"][0]["status"], "approved")
