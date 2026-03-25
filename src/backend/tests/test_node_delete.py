"""Tests for node deletion behavior."""
from sqlalchemy import select

from models.models import Edge, Node
from tests.factories import NodeFactory, ProjectFactory


class TestDeleteNode:
    async def test_delete_node_removes_incident_edges(self, client, db_session):
        project_resp = await client.post(
            "/api/projects",
            json=ProjectFactory.create(description="Project description long enough"),
        )
        project = project_resp.json()

        child_resp = await client.post(
            f"/api/projects/{project['id']}/nodes",
            json=NodeFactory.create(parent_id=project["root_node_id"]),
        )
        child = child_resp.json()

        grandchild_resp = await client.post(
            f"/api/projects/{project['id']}/nodes",
            json=NodeFactory.create(parent_id=child["id"]),
        )
        grandchild = grandchild_resp.json()

        edge_rows = await db_session.execute(
            select(Edge).where(
                (Edge.from_node_id == child["id"]) | (Edge.to_node_id == child["id"])
            )
        )
        assert len(edge_rows.scalars().all()) == 2

        resp = await client.delete(f"/api/nodes/{child['id']}")

        assert resp.status_code == 204

        deleted_node = await db_session.get(Node, child["id"])
        assert deleted_node is None

        surviving_node = await db_session.get(Node, grandchild["id"])
        assert surviving_node is not None

        remaining_edges = await db_session.execute(
            select(Edge).where(
                (Edge.from_node_id == child["id"]) | (Edge.to_node_id == child["id"])
            )
        )
        assert remaining_edges.scalars().all() == []

        subtree_resp = await client.get(f"/api/nodes/{project['root_node_id']}/subtree")
        subtree = subtree_resp.json()
        assert subtree["children"] == []

    async def test_cannot_delete_root_node(self, client, db_session):
        project_resp = await client.post(
            "/api/projects",
            json=ProjectFactory.create(),
        )
        project = project_resp.json()

        resp = await client.delete(f"/api/nodes/{project['root_node_id']}")

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Cannot delete the project root node"
        assert await db_session.get(Node, project["root_node_id"]) is not None
