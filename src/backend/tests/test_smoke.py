"""Smoke tests to verify the test infrastructure works correctly."""
import pytest
from tests.factories import ProjectFactory, NodeFactory, EdgeFactory


class TestFixturesWork:
    """Verify that DB fixtures and TestClient are functional."""

    async def test_api_root(self, client):
        """GET /api should return the API info."""
        resp = await client.get("/api")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "GrowthMap"
        assert data["status"] == "running"

    async def test_create_project(self, client):
        """POST /api/projects should create a project and return it."""
        payload = ProjectFactory.create()
        resp = await client.post("/api/projects", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == payload["name"]
        assert "id" in data
        assert data["root_node_id"] is not None  # auto-created root node

    async def test_create_node_under_root(self, client):
        """Create a project, then add a child node under the root."""
        # Create project
        project_resp = await client.post("/api/projects", json=ProjectFactory.create())
        project = project_resp.json()
        project_id = project["id"]
        root_id = project["root_node_id"]

        # Create child node
        node_data = NodeFactory.create(parent_id=root_id)
        resp = await client.post(f"/api/projects/{project_id}/nodes", json=node_data)
        assert resp.status_code == 201
        node = resp.json()
        assert node["title"] == node_data["title"]
        assert node["project_id"] == project_id

    async def test_db_session_isolation(self, client):
        """Each test gets a fresh DB — no data leaks between tests."""
        resp = await client.get("/api/projects")
        assert resp.status_code == 200
        projects = resp.json()
        # Should be empty because each test gets a fresh in-memory DB
        assert len(projects) == 0

    async def test_subtree_endpoint(self, client):
        """Verify subtree returns nested structure."""
        project_resp = await client.post("/api/projects", json=ProjectFactory.create())
        project = project_resp.json()
        root_id = project["root_node_id"]

        # Create a child
        child_data = NodeFactory.create(parent_id=root_id)
        child_resp = await client.post(f"/api/projects/{project['id']}/nodes", json=child_data)
        child = child_resp.json()

        # Get subtree
        resp = await client.get(f"/api/nodes/{root_id}/subtree")
        assert resp.status_code == 200
        tree = resp.json()
        assert tree["id"] == root_id
        assert len(tree["children"]) == 1
        assert tree["children"][0]["id"] == child["id"]


class TestFactories:
    """Verify test data factories produce valid data."""

    def test_project_factory_increments(self):
        ProjectFactory.reset()
        p1 = ProjectFactory.create()
        p2 = ProjectFactory.create()
        assert p1["name"] != p2["name"]
        assert "name" in p1
        assert "description" in p1

    def test_node_factory_with_parent(self):
        NodeFactory.reset()
        n = NodeFactory.create(parent_id="some-parent-id")
        assert n["parent_id"] == "some-parent-id"

    def test_node_factory_without_parent(self):
        NodeFactory.reset()
        n = NodeFactory.create()
        assert "parent_id" not in n

    def test_edge_factory(self):
        EdgeFactory.reset()
        e = EdgeFactory.create(from_node_id="a", to_node_id="b")
        assert e["from_node_id"] == "a"
        assert e["to_node_id"] == "b"
        assert e["relation_type"] == "child_of"

    def test_factory_overrides(self):
        p = ProjectFactory.create(name="Custom Name", goal="custom goal")
        assert p["name"] == "Custom Name"
        assert p["goal"] == "custom goal"
