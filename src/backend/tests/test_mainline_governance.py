"""Tests for mainline/branch governance endpoints."""

import pytest


class TestMoveNode:
    async def test_move_node_to_new_parent(self, client):
        """Move a child node from one parent to another."""
        proj = (await client.post("/api/projects", json={"name": "Move Test", "description": "d", "goal": "g"})).json()
        root_id = proj["root_node_id"]

        child_a = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "Child A", "summary": "A", "parent_id": root_id},
        )).json()
        child_b = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "Child B", "summary": "B", "parent_id": root_id},
        )).json()

        # Move child_b under child_a
        resp = await client.post(
            f"/api/nodes/{child_b['id']}/move",
            json={"new_parent_id": child_a["id"]},
        )
        assert resp.status_code == 200

        # Verify child_b is now under child_a
        children_of_a = (await client.get(f"/api/nodes/{child_a['id']}/children")).json()
        assert any(c["id"] == child_b["id"] for c in children_of_a)

        # Verify child_b is no longer under root
        children_of_root = (await client.get(f"/api/nodes/{root_id}/children")).json()
        assert not any(c["id"] == child_b["id"] for c in children_of_root)

    async def test_cannot_move_root_node(self, client):
        proj = (await client.post("/api/projects", json={"name": "Root Move", "description": "d", "goal": "g"})).json()
        child = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "Child", "summary": "c", "parent_id": proj["root_node_id"]},
        )).json()

        resp = await client.post(
            f"/api/nodes/{proj['root_node_id']}/move",
            json={"new_parent_id": child["id"]},
        )
        assert resp.status_code == 400

    async def test_cannot_move_under_descendant(self, client):
        """Cycle detection: parent cannot move under its own child."""
        proj = (await client.post("/api/projects", json={"name": "Cycle", "description": "d", "goal": "g"})).json()
        root_id = proj["root_node_id"]

        child = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "Child", "summary": "c", "parent_id": root_id},
        )).json()
        grandchild = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "Grandchild", "summary": "gc", "parent_id": child["id"]},
        )).json()

        # Try to move child under its own grandchild
        resp = await client.post(
            f"/api/nodes/{child['id']}/move",
            json={"new_parent_id": grandchild["id"]},
        )
        assert resp.status_code == 400
        assert "descendant" in resp.json()["detail"].lower()

    async def test_cannot_move_to_different_project(self, client):
        proj_a = (await client.post("/api/projects", json={"name": "A", "description": "d", "goal": "g"})).json()
        proj_b = (await client.post("/api/projects", json={"name": "B", "description": "d", "goal": "g"})).json()
        child = (await client.post(
            f"/api/projects/{proj_a['id']}/nodes",
            json={"title": "Child", "summary": "c", "parent_id": proj_a["root_node_id"]},
        )).json()

        resp = await client.post(
            f"/api/nodes/{child['id']}/move",
            json={"new_parent_id": proj_b["root_node_id"]},
        )
        assert resp.status_code == 400


class TestGetAncestors:
    async def test_returns_ancestors_root_first(self, client):
        proj = (await client.post("/api/projects", json={"name": "Ancestors", "description": "d", "goal": "g"})).json()
        root_id = proj["root_node_id"]

        child = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "Child", "summary": "c", "parent_id": root_id},
        )).json()
        grandchild = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "Grandchild", "summary": "gc", "parent_id": child["id"]},
        )).json()

        resp = await client.get(f"/api/nodes/{grandchild['id']}/ancestors")
        assert resp.status_code == 200
        ancestors = resp.json()
        assert len(ancestors) == 2
        assert ancestors[0]["id"] == root_id  # root first
        assert ancestors[1]["id"] == child["id"]

    async def test_root_has_no_ancestors(self, client):
        proj = (await client.post("/api/projects", json={"name": "Root Anc", "description": "d", "goal": "g"})).json()
        resp = await client.get(f"/api/nodes/{proj['root_node_id']}/ancestors")
        assert resp.status_code == 200
        assert resp.json() == []


class TestMainlinePath:
    async def test_returns_mainline_from_root_to_leaf(self, client):
        proj = (await client.post("/api/projects", json={"name": "Mainline", "description": "d", "goal": "g"})).json()
        root_id = proj["root_node_id"]

        child = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "Mainline Child", "summary": "mc", "parent_id": root_id},
        )).json()
        grandchild = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "Mainline GC", "summary": "mgc", "parent_id": child["id"]},
        )).json()

        resp = await client.get(f"/api/projects/{proj['id']}/mainline-path")
        assert resp.status_code == 200
        path = resp.json()["path"]
        assert len(path) == 3
        assert path[0]["id"] == root_id
        assert path[1]["id"] == child["id"]
        assert path[2]["id"] == grandchild["id"]

    async def test_mainline_path_follows_promoted_edge(self, client):
        """When a non-first child is promoted to mainline, path should follow it."""
        proj = (await client.post("/api/projects", json={"name": "Promote", "description": "d", "goal": "g"})).json()
        root_id = proj["root_node_id"]

        child_a = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "Child A", "summary": "a", "parent_id": root_id},
        )).json()
        child_b = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "Child B", "summary": "b", "parent_id": root_id},
        )).json()

        # Promote child_b
        await client.post(f"/api/nodes/{root_id}/promote-child/{child_b['id']}")

        resp = await client.get(f"/api/projects/{proj['id']}/mainline-path")
        path = resp.json()["path"]
        assert len(path) == 2
        assert path[0]["id"] == root_id
        assert path[1]["id"] == child_b["id"]


class TestBranchRoots:
    async def test_finds_branch_points(self, client):
        proj = (await client.post("/api/projects", json={"name": "Branch", "description": "d", "goal": "g"})).json()
        root_id = proj["root_node_id"]

        child_a = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "A", "summary": "a", "parent_id": root_id},
        )).json()
        child_b = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "B", "summary": "b", "parent_id": root_id},
        )).json()

        resp = await client.get(f"/api/projects/{proj['id']}/branch-roots")
        assert resp.status_code == 200
        branches = resp.json()
        assert len(branches) == 1
        assert branches[0]["node_id"] == root_id
        assert branches[0]["total_children"] == 2
        assert branches[0]["mainline_child_id"] == child_a["id"]  # first child is mainline
        assert child_b["id"] in branches[0]["branch_child_ids"]

    async def test_no_branches_with_single_child(self, client):
        proj = (await client.post("/api/projects", json={"name": "Linear", "description": "d", "goal": "g"})).json()
        (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "Only Child", "summary": "oc", "parent_id": proj["root_node_id"]},
        )).json()

        resp = await client.get(f"/api/projects/{proj['id']}/branch-roots")
        assert resp.status_code == 200
        assert resp.json() == []


class TestMoveNodeMainlineInvariant:
    async def test_moved_node_becomes_mainline_if_first_child(self, client):
        """When a node is moved to a parent with no children, it should become mainline."""
        proj = (await client.post("/api/projects", json={"name": "ML Invariant", "description": "d", "goal": "g"})).json()
        root_id = proj["root_node_id"]

        child_a = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "A", "summary": "a", "parent_id": root_id},
        )).json()
        child_b = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "B", "summary": "b", "parent_id": root_id},
        )).json()
        standalone = (await client.post(
            f"/api/projects/{proj['id']}/nodes",
            json={"title": "Standalone", "summary": "s", "parent_id": child_a["id"]},
        )).json()

        # Move standalone under child_b (which has no children yet)
        resp = await client.post(
            f"/api/nodes/{standalone['id']}/move",
            json={"new_parent_id": child_b["id"]},
        )
        assert resp.status_code == 200
        assert resp.json()["is_mainline"] is True

        # Verify via branch-roots: child_b now has 1 child (no branching), root still has 2
        branches = (await client.get(f"/api/projects/{proj['id']}/branch-roots")).json()
        assert len(branches) == 1
        assert branches[0]["node_id"] == root_id
