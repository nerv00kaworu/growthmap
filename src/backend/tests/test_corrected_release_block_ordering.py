"""Batch 2 corrected-release canonical content-block ordering regressions."""
import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select

from api import routes
from db.database import async_session
from main import app
from models.models import ContentBlock


def project(client, name="blocks"):
    return client.post("/api/projects", json={"name": name}).json()


def revisions(client, project_id, node_id):
    return (client.get(f"/api/projects/{project_id}").json()["revision"],
            client.get(f"/api/nodes/{node_id}").json()["revision"])


def blocks(client, node_id):
    return client.get(f"/api/nodes/{node_id}/blocks").json()


def create(client, project_id, node_id, title, order_index=None):
    project_revision, node_revision = revisions(client, project_id, node_id)
    payload = {"expected_project_revision": project_revision, "expected_node_revision": node_revision,
               "block_type": "note", "content": {"title": title}}
    if order_index is not None:
        payload["order_index"] = order_index
    response = client.post(f"/api/nodes/{node_id}/blocks", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def patch(client, project_id, node_id, block, order_index):
    project_revision, node_revision = revisions(client, project_id, node_id)
    return client.patch(f"/api/blocks/{block['id']}", json={
        "expected_project_revision": project_revision, "expected_node_revision": node_revision,
        "expected_revision": block["revision"], "order_index": order_index,
    })


def delete(client, project_id, node_id, block):
    project_revision, node_revision = revisions(client, project_id, node_id)
    return client.request("DELETE", f"/api/blocks/{block['id']}", json={
        "expected_project_revision": project_revision, "expected_node_revision": node_revision,
        "expected_revision": block["revision"],
    })


def assert_dense(rows):
    assert [row["order_index"] for row in rows] == list(range(len(rows)))


def test_create_empty_middle_end_and_delete_first_middle_last_are_dense():
    with TestClient(app) as client:
        p = project(client)
        node = p["root_node_id"]
        first = create(client, p["id"], node, "first")
        assert first["order_index"] == 0
        create(client, p["id"], node, "end")
        middle = create(client, p["id"], node, "middle", 1)
        assert [row["content"]["title"] for row in blocks(client, node)] == ["first", "middle", "end"]
        create(client, p["id"], node, "normalized end", 999)
        assert_dense(blocks(client, node))
        for index in (0, 1, -1):
            rows = blocks(client, node)
            victim = rows[index]
            assert delete(client, p["id"], node, victim).status_code == 204
            assert_dense(blocks(client, node))


def test_atomic_moves_all_directions_bounds_noop_and_exact_sibling_revisions():
    with TestClient(app) as client:
        p = project(client)
        node = p["root_node_id"]
        for title in "abcd":
            create(client, p["id"], node, title)
        before = {row["id"]: row["revision"] for row in blocks(client, node)}
        moving = blocks(client, node)[3]
        response = patch(client, p["id"], node, moving, 1)
        assert response.status_code == 200, response.text
        rows = blocks(client, node)
        assert [row["content"]["title"] for row in rows] == ["a", "d", "b", "c"]
        changed = {row["content"]["title"]: row["revision"] - before[row["id"]] for row in rows}
        assert changed == {"a": 0, "d": 1, "b": 1, "c": 1}
        for wanted in (99, 0, 2):
            moving = next(row for row in blocks(client, node) if row["content"]["title"] == "d")
            assert patch(client, p["id"], node, moving, wanted).status_code == 200
            assert_dense(blocks(client, node))
        moving = next(row for row in blocks(client, node) if row["content"]["title"] == "d")
        before = {row["id"]: row["revision"] for row in blocks(client, node)}
        assert patch(client, p["id"], node, moving, moving["order_index"]).status_code == 200
        after = {row["id"]: row["revision"] for row in blocks(client, node)}
        assert after[moving["id"]] == before[moving["id"]] + 1
        assert all(after[key] == value for key, value in before.items() if key != moving["id"])


def test_legacy_duplicate_sparse_order_canonicalizes_stably_and_isolated():
    with TestClient(app) as client:
        p1, p2 = project(client, "one"), project(client, "two")
        n1, n2 = p1["root_node_id"], p2["root_node_id"]
        made = [create(client, p1["id"], n1, title) for title in "abcd"]
        other = create(client, p2["id"], n2, "other", 7)

        async def damage():
            async with async_session() as db:
                rows = list((await db.execute(select(ContentBlock).where(ContentBlock.node_id == n1)
                                               .order_by(ContentBlock.created_at, ContentBlock.id))).scalars())
                for row, bad in zip(rows, (8, 0, 0, 99)):
                    row.order_index = bad
                await db.commit()
        asyncio.run(damage())

        create(client, p1["id"], n1, "insert", 2)
        rows = blocks(client, n1)
        assert_dense(rows)
        assert [row["content"]["title"] for row in rows] == ["b", "c", "insert", "a", "d"]
        isolated = blocks(client, n2)
        assert len(isolated) == 1 and isolated[0]["id"] == other["id"] and isolated[0]["order_index"] == 0


def test_stale_project_or_node_cas_has_zero_mutation():
    with TestClient(app) as client:
        p = project(client)
        node = p["root_node_id"]
        target = create(client, p["id"], node, "target")
        create(client, p["id"], node, "sibling")
        before = blocks(client, node)
        current_project, current_node = revisions(client, p["id"], node)
        stale_project = client.patch(f"/api/blocks/{target['id']}", json={
            "expected_project_revision": current_project - 1, "expected_node_revision": current_node,
            "expected_revision": target["revision"], "order_index": 1,
        })
        assert stale_project.status_code == 409
        assert blocks(client, node) == before
        stale_node = client.patch(f"/api/blocks/{target['id']}", json={
            "expected_project_revision": current_project, "expected_node_revision": current_node - 1,
            "expected_revision": target["revision"], "order_index": 1,
        })
        assert stale_node.status_code == 409
        assert blocks(client, node) == before


def test_injected_mid_shift_failure_rolls_back_all_revisions_and_order(monkeypatch):
    with TestClient(app, raise_server_exceptions=False) as client:
        p = project(client)
        node = p["root_node_id"]
        for title in "abcd":
            create(client, p["id"], node, title)
        before_rows = blocks(client, node)
        before_project, before_node = revisions(client, p["id"], node)
        moving = before_rows[-1]
        real = routes._set_block_order
        calls = 0
        def fail_second(block, index):
            nonlocal calls
            calls += 1
            real(block, index)
            if calls == 2:
                raise RuntimeError("injected shift failure")
        monkeypatch.setattr(routes, "_set_block_order", fail_second)
        response = patch(client, p["id"], node, moving, 0)
        assert response.status_code == 500
        assert blocks(client, node) == before_rows
        assert revisions(client, p["id"], node) == (before_project, before_node)
