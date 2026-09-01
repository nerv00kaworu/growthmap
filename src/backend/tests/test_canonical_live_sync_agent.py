"""Fresh-process Agent Port → canonical live-sync acceptance tests.

Run standalone to keep ``main``'s database engine and desktop-mode imports isolated:
``python -m pytest -q src/backend/tests/test_canonical_live_sync_agent.py``.
"""
import asyncio
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Must precede importing main/db modules.
_TMP = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP.name}/agent-live-sync.sqlite"
os.environ["APP_ENV"] = "test"
os.environ["GROWTHMAP_HUMAN_CONTROL_TOKEN"] = "agent-live-human"
sys.path.insert(0, str(Path(__file__).parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import select, text
import main
from api import change_routes
from api.canonical_changes import MAX_SAFE_INTEGER, change_hub
from db.database import async_session
from models.models import CanonicalChange, Edge, Node, Project

# The real route is desktop-only. Keep normal app requests in authoring mode;
# ``changes`` below opens this one route's runtime gate only for its request.


class CanonicalLiveSyncAgent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.client.__enter__()
        cls.human = {"Authorization": "Bearer agent-live-human"}

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        _TMP.cleanup()

    def setUp(self):
        project = self.client.post("/api/projects", json={"name": "agent live sync"}).json()
        self.pid, self.root = project["id"], project["root_node_id"]

    def grant(self, permission="write"):
        response = self.client.post("/api/agent-port/grants", headers=self.human, json={
            "project_id": self.pid, "permission": permission,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "label": "canonical-live", "agent_identity": "agent-live-test",
        })
        self.assertEqual(response.status_code, 201, response.text)
        return {"Authorization": "Bearer " + response.json()["token"]}

    def project(self):
        response = self.client.get(f"/api/projects/{self.pid}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def changes(self, since):
        # The desktop middleware reads the same security module. Temporarily
        # make the existing human capability the desktop launch capability too.
        old_mode, old_token = change_routes.desktop_security.DESKTOP_MODE, change_routes.desktop_security.SESSION_TOKEN
        change_routes.desktop_security.DESKTOP_MODE = True
        change_routes.desktop_security.SESSION_TOKEN = "agent-live-human"
        try:
            return self.client.get(f"/api/projects/{self.pid}/changes?since_revision={since}", headers=self.human)
        finally:
            change_routes.desktop_security.DESKTOP_MODE = old_mode
            change_routes.desktop_security.SESSION_TOKEN = old_token

    async def rows(self):
        async with async_session() as db:
            return (await db.execute(select(CanonicalChange).where(
                CanonicalChange.project_id == self.pid).order_by(CanonicalChange.project_revision)
            )).scalars().all()

    def journal(self):
        return asyncio.run(self.rows())

    def create_child_body(self, key, revision=None, parent_revision=None, child_id=None):
        project = self.project()
        root = self.client.get(f"/api/nodes/{self.root}").json()
        return {"expected_project_revision": project["revision"] if revision is None else revision,
                "idempotency_key": key,
                "operations": [{"op": "create_node", "id": child_id or str(uuid.uuid4()),
                                "parent_id": self.root,
                                "expected_parent_revision": root["revision"] if parent_revision is None else parent_revision,
                                "title": "agent-created child"}]}

    def test_batch_create_receipt_journal_and_incremental_delta(self):
        auth = self.grant()
        before = self.project()["revision"]
        body = self.create_child_body("live-create-001", revision=before)
        receipt = self.client.post("/agent/v1/batch", headers=auth, json=body)
        self.assertEqual(receipt.status_code, 200, receipt.text)
        receipt = receipt.json()
        child_id = receipt["results"][0]["id"]
        self.assertEqual(receipt["project_revision"], before + 1)

        async def canonical_state():
            async with async_session() as db:
                child = await db.get(Node, child_id)
                edge = (await db.execute(select(Edge).where(Edge.project_id == self.pid,
                    Edge.from_node_id == self.root, Edge.to_node_id == child_id,
                    Edge.relation_type == "child_of"))).scalar_one()
                journal = (await db.execute(select(CanonicalChange).where(
                    CanonicalChange.project_id == self.pid,
                    CanonicalChange.project_revision == before + 1))).scalar_one()
                return child, edge, journal
        child, edge, journal = asyncio.run(canonical_state())
        self.assertEqual(child.project_id, self.pid)
        self.assertEqual(edge.from_node_id, self.root)
        self.assertEqual(edge.to_node_id, child_id)
        self.assertEqual(edge.relation_type, "child_of")
        self.assertEqual(journal.project_revision, receipt["project_revision"])

        delta = self.changes(before)
        self.assertEqual(delta.status_code, 200, delta.text)
        delta = delta.json()
        self.assertFalse(delta["full_refresh_required"])
        self.assertTrue(delta["complete"])
        self.assertEqual({item["id"] for item in delta["nodes"]}, {self.root, child_id})
        self.assertEqual([(item["from_node_id"], item["to_node_id"], item["relation_type"])
                          for item in delta["edges"]], [(self.root, child_id, "child_of")])

    def test_exact_replay_and_mismatch_do_not_create_second_change(self):
        auth = self.grant()
        body = self.create_child_body("live-replay-001")
        first = self.client.post("/agent/v1/batch", headers=auth, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        first = first.json()
        count = len(self.journal())
        replay = self.client.post("/agent/v1/batch", headers=auth, json=body)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), first)
        self.assertEqual(self.project()["revision"], first["project_revision"])
        self.assertEqual(len(self.journal()), count)
        mismatch = {**body, "operations": [{**body["operations"][0], "title": "different"}]}
        bad = self.client.post("/agent/v1/batch", headers=auth, json=mismatch)
        self.assertEqual(bad.status_code, 409, bad.text)
        self.assertEqual(self.project()["revision"], first["project_revision"])
        self.assertEqual(len(self.journal()), count)

    def test_proposal_approval_is_one_journaled_revision_and_reapproval_is_safe(self):
        auth = self.grant("propose")
        before = self.project()["revision"]
        body = self.create_child_body("live-proposal-001", revision=before)
        body.update({"target_node_id": self.root, "title": "review this child"})
        proposal = self.client.post("/agent/v1/proposals", headers=auth, json=body)
        self.assertEqual(proposal.status_code, 201, proposal.text)
        proposal_id = proposal.json()["proposal_id"]
        self.assertEqual(self.project()["revision"], before)
        approved = self.client.post(f"/api/agent-port/proposals/{proposal_id}/approve", headers=self.human, json={})
        self.assertEqual(approved.status_code, 200, approved.text)
        receipt = approved.json()["receipt"]
        self.assertEqual(receipt["project_revision"], before + 1)
        activity = self.client.get(f"/api/agent-port/activity?project_id={self.pid}", headers=self.human).json()
        self.assertEqual(next(row for row in activity["proposals"] if row["id"] == proposal_id)["status"], "approved")
        rows = [r for r in self.journal() if r.project_revision == before + 1]
        self.assertEqual(len(rows), 1)
        child_id = receipt["results"][0]["id"]
        delta = self.changes(before).json()
        self.assertFalse(delta["full_refresh_required"])
        self.assertIn(child_id, {node["id"] for node in delta["nodes"]})
        again = self.client.post(f"/api/agent-port/proposals/{proposal_id}/approve", headers=self.human, json={})
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["status"], "approved")
        self.assertEqual(self.project()["revision"], before + 1)
        self.assertEqual(len([r for r in self.journal() if r.project_revision == before + 1]), 1)

    def test_gui_node_http_entity_max_rolls_back_project_journal_and_wake(self):
        async def set_root(revision):
            async with async_session() as db:
                await db.execute(text("UPDATE nodes SET revision=:r WHERE id=:id"), {"r": revision, "id": self.root})
                await db.commit()
        asyncio.run(set_root(MAX_SAFE_INTEGER - 1))
        before = self.project()["revision"]
        ok = self.client.patch(f"/api/nodes/{self.root}", json={
            "expected_project_revision": before, "expected_revision": MAX_SAFE_INTEGER - 1,
            "summary": "exact max"})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()["revision"], MAX_SAFE_INTEGER)
        at_max_project = self.project()["revision"]
        before_journal = len(self.journal())
        async def rejected_without_wake():
            sub = change_hub.subscribe()
            try:
                failed = await asyncio.to_thread(self.client.patch, f"/api/nodes/{self.root}", json={
                    "expected_project_revision": at_max_project, "expected_revision": MAX_SAFE_INTEGER,
                    "summary": "must roll back"})
                await asyncio.sleep(0.05)
                return failed, sub.queue.empty()
            finally: change_hub.unsubscribe(sub)
        failed, no_wake = asyncio.run(rejected_without_wake())
        self.assertEqual(failed.status_code, 409, failed.text)
        self.assertEqual(failed.json()["detail"]["code"], "REVISION_EXHAUSTED")
        self.assertTrue(no_wake)
        self.assertEqual(self.project()["revision"], at_max_project)
        node = self.client.get(f"/api/nodes/{self.root}").json()
        self.assertEqual((node["revision"], node["summary"]), (MAX_SAFE_INTEGER, "exact max"))
        self.assertEqual(len(self.journal()), before_journal)

    def test_referenced_entity_exhaustion_precedes_agent_project_claim_and_writes(self):
        auth = self.grant()
        async def set_root(revision):
            async with async_session() as db:
                await db.execute(text("UPDATE nodes SET revision=:r WHERE id=:id"), {"r": revision, "id": self.root})
                await db.commit()
        asyncio.run(set_root(MAX_SAFE_INTEGER))
        before_project = self.project()["revision"]
        before_nodes = len(self.client.get(f"/api/projects/{self.pid}/nodes").json())
        before_journal = len(self.journal())
        update = {"expected_project_revision": before_project, "idempotency_key": "entity-max-update",
                  "operations": [{"op": "update_node", "node_id": self.root,
                                  "expected_revision": MAX_SAFE_INTEGER, "fields": {"summary": "forbidden"}}]}
        create = {"expected_project_revision": before_project, "idempotency_key": "entity-max-create",
                  "operations": [{"op": "create_node", "id": str(uuid.uuid4()), "parent_id": self.root,
                                  "expected_parent_revision": MAX_SAFE_INTEGER, "title": "forbidden child"}]}
        async def rejected_without_wake():
            sub = change_hub.subscribe()
            try:
                responses = [await asyncio.to_thread(self.client.post, "/agent/v1/batch", headers=auth, json=body)
                             for body in (update, create)]
                await asyncio.sleep(0.05)
                return responses, sub.queue.empty()
            finally: change_hub.unsubscribe(sub)
        responses, no_wake = asyncio.run(rejected_without_wake())
        for response in responses:
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()["detail"]["code"], "REVISION_EXHAUSTED")
        self.assertTrue(no_wake)
        self.assertEqual(self.project()["revision"], before_project)
        self.assertEqual(len(self.client.get(f"/api/projects/{self.pid}/nodes").json()), before_nodes)
        self.assertEqual(len(self.journal()), before_journal)
        self.assertEqual(self.client.get(f"/api/nodes/{self.root}").json()["summary"], "")

        asyncio.run(set_root(MAX_SAFE_INTEGER - 1))
        success = {**create, "idempotency_key": "entity-max-create-success",
                   "operations": [{**create["operations"][0], "id": str(uuid.uuid4()),
                                   "expected_parent_revision": MAX_SAFE_INTEGER - 1}]}
        reached = self.client.post("/agent/v1/batch", headers=auth, json=success)
        self.assertEqual(reached.status_code, 200, reached.text)
        self.assertEqual(self.client.get(f"/api/nodes/{self.root}").json()["revision"], MAX_SAFE_INTEGER)

    def test_max_boundary_and_stale_failure_leave_no_journal_or_wake(self):
        auth = self.grant()
        async def set_max_minus_one():
            async with async_session() as db:
                await db.execute(text("UPDATE projects SET revision=:revision WHERE id=:id"),
                                 {"revision": MAX_SAFE_INTEGER - 1, "id": self.pid})
                await db.commit()
        asyncio.run(set_max_minus_one())
        root = self.client.get(f"/api/nodes/{self.root}").json()
        body = {"expected_project_revision": MAX_SAFE_INTEGER - 1, "idempotency_key": "live-max-001",
                "operations": [{"op": "update_node", "node_id": self.root,
                                "expected_revision": root["revision"], "fields": {"summary": "at max"}}]}
        reached = self.client.post("/agent/v1/batch", headers=auth, json=body)
        self.assertEqual(reached.status_code, 200, reached.text)
        self.assertEqual(reached.json()["project_revision"], MAX_SAFE_INTEGER)
        count = len(self.journal())
        nodes_before = len(self.client.get(f"/api/projects/{self.pid}/nodes").json())
        at_max = {**body, "idempotency_key": "live-max-002", "expected_project_revision": MAX_SAFE_INTEGER,
                  "operations": [{"op": "update_node", "node_id": self.root,
                                  "expected_revision": root["revision"] + 1, "fields": {"summary": "must fail"}}]}
        stale = self.create_child_body("live-stale-001", revision=MAX_SAFE_INTEGER - 1)
        async def fail_without_wake():
            # Keep a live hub loop while HTTP mutations run in a worker thread;
            # a rejected CAS must not enqueue an invalidation.
            sub = change_hub.subscribe()
            try:
                failed = await asyncio.to_thread(self.client.post, "/agent/v1/batch", headers=auth, json=at_max)
                stale_failed = await asyncio.to_thread(self.client.post, "/agent/v1/batch", headers=auth, json=stale)
                await asyncio.sleep(0.05)
                return failed, stale_failed, sub.queue.empty()
            finally:
                change_hub.unsubscribe(sub)
        failed, stale_failed, no_wake = asyncio.run(fail_without_wake())
        self.assertEqual(failed.status_code, 409, failed.text)
        self.assertEqual(stale_failed.status_code, 409, stale_failed.text)
        self.assertTrue(no_wake)
        self.assertEqual(self.project()["revision"], MAX_SAFE_INTEGER)
        self.assertEqual(len(self.client.get(f"/api/projects/{self.pid}/nodes").json()), nodes_before)
        self.assertEqual(len(self.journal()), count)


if __name__ == "__main__":
    unittest.main()
