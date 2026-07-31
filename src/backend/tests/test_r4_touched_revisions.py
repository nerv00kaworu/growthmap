import os, tempfile
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/r4.db"
os.environ["APP_ENV"] = "test"
from fastapi.testclient import TestClient
from main import app


def test_create_child_requires_parent_cas_and_invalidates_jian_stale_revision():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "r4"}).json()
        root = client.get(f"/api/nodes/{project['root_node_id']}").json()
        missing = client.post(f"/api/projects/{project['id']}/nodes", json={
            "expected_project_revision": project["revision"], "title": "child", "parent_id": root["id"]
        })
        assert missing.status_code == 422
        assert client.get(f"/api/projects/{project['id']}").json()["revision"] == project["revision"]

        created = client.post(f"/api/projects/{project['id']}/nodes", json={
            "expected_project_revision": project["revision"], "expected_parent_revision": root["revision"],
            "title": "child", "parent_id": root["id"]
        })
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["authoritative_project_revision"] == project["revision"] + 1
        assert body["authoritative_parent_revision"] == root["revision"] + 1
        current_project = client.get(f"/api/projects/{project['id']}").json()
        current_root = client.get(f"/api/nodes/{root['id']}").json()
        assert current_root["maturity"] == "rough"
        assert current_root["revision"] == root["revision"] + 1
        stale = client.patch(f"/api/nodes/{root['id']}", json={
            "expected_project_revision": current_project["revision"], "expected_revision": root["revision"],
            "description": "Jian stale entity must be rejected"
        })
        assert stale.status_code == 409, stale.text


def test_stale_parent_rejected_before_project_claim_or_write():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "stale-parent"}).json()
        root = client.get(f"/api/nodes/{project['root_node_id']}").json()
        winner = client.patch(f"/api/nodes/{root['id']}", json={
            "expected_project_revision": project["revision"], "expected_revision": root["revision"], "summary": "winner"
        })
        assert winner.status_code == 200
        p2 = client.get(f"/api/projects/{project['id']}").json()
        stale = client.post(f"/api/projects/{project['id']}/nodes", json={
            "expected_project_revision": p2["revision"], "expected_parent_revision": root["revision"],
            "title": "must not exist", "parent_id": root["id"]
        })
        assert stale.status_code == 409
        assert client.get(f"/api/projects/{project['id']}").json()["revision"] == p2["revision"]
        assert all(n["title"] != "must not exist" for n in client.get(f"/api/projects/{project['id']}/nodes").json())


def _create_child(client, project, parent, title):
    return client.post(f"/api/projects/{project['id']}/nodes", json={
        "expected_project_revision": project["revision"], "expected_parent_revision": parent["revision"],
        "title": title, "parent_id": parent["id"],
    }).json()


def test_mainline_promotion_bumps_only_promoted_and_actually_demoted_sibling():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "mainline"}).json()
        root = client.get(f"/api/nodes/{project['root_node_id']}").json()
        first = _create_child(client, project, root, "first")
        project = client.get(f"/api/projects/{project['id']}").json(); root = client.get(f"/api/nodes/{root['id']}").json()
        second = _create_child(client, project, root, "second")
        project = client.get(f"/api/projects/{project['id']}").json()
        edges = client.get(f"/api/projects/{project['id']}/edges?relation_type=child_of").json()
        by_child = {e["to_node_id"]: e for e in edges}
        before_first, before_second = by_child[first["id"]], by_child[second["id"]]
        promoted = client.post(f"/api/edges/{before_second['id']}/promote-mainline", json={
            "expected_project_revision": project["revision"], "expected_revision": before_second["revision"],
            "expected_sibling_revisions": {before_first["id"]: before_first["revision"]},
        })
        assert promoted.status_code == 200, promoted.text
        project2 = client.get(f"/api/projects/{project['id']}").json()
        edges2 = {e["to_node_id"]: e for e in client.get(f"/api/projects/{project['id']}/edges?relation_type=child_of").json()}
        assert project2["revision"] == project["revision"] + 1
        assert edges2[first["id"]]["revision"] == before_first["revision"] + 1
        assert edges2[first["id"]]["is_mainline"] is False
        assert edges2[second["id"]]["revision"] == before_second["revision"] + 1
        # Re-promoting the already-mainline edge mutates no sibling, but the
        # explicitly addressed edge remains the canonical promoted entity.
        again = client.post(f"/api/edges/{before_second['id']}/promote-mainline", json={
            "expected_project_revision": project2["revision"], "expected_revision": edges2[second["id"]]["revision"],
            "expected_sibling_revisions": {},
        })
        assert again.status_code == 200
        edges3 = {e["to_node_id"]: e for e in client.get(f"/api/projects/{project['id']}/edges?relation_type=child_of").json()}
        assert edges3[first["id"]]["revision"] == edges2[first["id"]]["revision"]
        assert edges3[second["id"]]["revision"] == edges2[second["id"]]["revision"] + 1


def test_reparent_bumps_moved_old_and_new_parent_once_and_new_edge_starts_one():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "reparent"}).json()
        root = client.get(f"/api/nodes/{project['root_node_id']}").json()
        old_parent = _create_child(client, project, root, "old")
        project = client.get(f"/api/projects/{project['id']}").json(); root = client.get(f"/api/nodes/{root['id']}").json()
        new_parent = _create_child(client, project, root, "new")
        project = client.get(f"/api/projects/{project['id']}").json(); old_parent = client.get(f"/api/nodes/{old_parent['id']}").json()
        moved = _create_child(client, project, old_parent, "moved")
        project = client.get(f"/api/projects/{project['id']}").json()
        old_parent = client.get(f"/api/nodes/{old_parent['id']}").json(); new_parent = client.get(f"/api/nodes/{new_parent['id']}").json()
        moved = client.get(f"/api/nodes/{moved['id']}").json()
        response = client.post(f"/api/nodes/{moved['id']}/reparent", json={
            "new_parent_id": new_parent["id"], "expected_project_revision": project["revision"],
            "expected_revision": moved["revision"], "expected_old_parent_revision": old_parent["revision"],
            "expected_new_parent_revision": new_parent["revision"],
        })
        assert response.status_code == 200, response.text
        assert response.json()["node_revision"] == moved["revision"] + 1
        assert response.json()["old_parent_revision"] == old_parent["revision"] + 1
        assert response.json()["new_parent_revision"] == new_parent["revision"] + 1
        current = client.get(f"/api/projects/{project['id']}").json()
        assert current["revision"] == project["revision"] + 1
        edge = next(e for e in client.get(f"/api/projects/{project['id']}/edges?relation_type=child_of").json() if e["to_node_id"] == moved["id"])
        assert edge["from_node_id"] == new_parent["id"] and edge["revision"] == 1


def test_content_block_owner_bumps_even_when_maturity_does_not_change():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "blocks"}).json()
        root = client.get(f"/api/nodes/{project['root_node_id']}").json()
        created = client.post(f"/api/nodes/{root['id']}/blocks", json={
            "expected_project_revision": project["revision"], "expected_node_revision": root["revision"],
            "block_type": "paragraph", "content": {"body": "one"},
        })
        assert created.status_code == 201, created.text
        root2 = client.get(f"/api/nodes/{root['id']}").json()
        project2 = client.get(f"/api/projects/{project['id']}").json()
        assert root2["maturity"] == root["maturity"]
        assert root2["revision"] == root["revision"] + 1
        assert project2["revision"] == project["revision"] + 1
        assert created.json()["revision"] == 1
