"""API route integration tests for suggestion management."""

import pytest


class TestCreateSuggestionRoute:
    async def test_create_suggestion_returns_201(self, client):
        # Create a project first
        resp = await client.post(
            "/api/projects", json={"name": "PR Test", "description": "d", "goal": "g"}
        )
        assert resp.status_code == 201
        project = resp.json()

        # Create a suggestion targeting the root node
        resp = await client.post(
            "/api/suggestions",
            json={
                "project_id": project["id"],
                "target_node_id": project["root_node_id"],
                "action_type": "add_child",
                "payload": {"title": "Suggested child"},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert data["action_type"] == "add_child"
        assert data["payload"] == {"title": "Suggested child"}

    async def test_create_suggestion_invalid_project_returns_404(self, client):
        resp = await client.post(
            "/api/suggestions",
            json={
                "project_id": "nonexistent",
                "target_node_id": "nonexistent",
                "action_type": "add_child",
            },
        )
        assert resp.status_code == 404


class TestListSuggestionsRoute:
    async def test_list_requires_project_id(self, client):
        resp = await client.get("/api/suggestions")
        assert resp.status_code == 422  # Missing required query param

    async def test_list_returns_suggestions(self, client):
        # Setup
        proj_resp = await client.post(
            "/api/projects", json={"name": "List Test", "description": "d", "goal": "g"}
        )
        project = proj_resp.json()

        await client.post(
            "/api/suggestions",
            json={
                "project_id": project["id"],
                "target_node_id": project["root_node_id"],
                "action_type": "add_child",
            },
        )
        await client.post(
            "/api/suggestions",
            json={
                "project_id": project["id"],
                "target_node_id": project["root_node_id"],
                "action_type": "edit_content",
            },
        )

        resp = await client.get(f"/api/suggestions?project_id={project['id']}")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_list_filters_by_status(self, client):
        proj_resp = await client.post(
            "/api/projects", json={"name": "Filter Test", "description": "d", "goal": "g"}
        )
        project = proj_resp.json()

        s_resp = await client.post(
            "/api/suggestions",
            json={
                "project_id": project["id"],
                "target_node_id": project["root_node_id"],
                "action_type": "add_child",
            },
        )
        suggestion = s_resp.json()

        # Approve one suggestion
        await client.patch(
            f"/api/suggestions/{suggestion['id']}",
            json={"status": "approved", "reviewed_by": "tester"},
        )

        # Create another (stays pending)
        await client.post(
            "/api/suggestions",
            json={
                "project_id": project["id"],
                "target_node_id": project["root_node_id"],
                "action_type": "edit_content",
            },
        )

        pending = await client.get(
            f"/api/suggestions?project_id={project['id']}&status=pending"
        )
        assert len(pending.json()) == 1

        approved = await client.get(
            f"/api/suggestions?project_id={project['id']}&status=approved"
        )
        assert len(approved.json()) == 1


class TestReviewSuggestionRoute:
    async def test_review_approves_suggestion(self, client):
        proj_resp = await client.post(
            "/api/projects", json={"name": "Review Test", "description": "d", "goal": "g"}
        )
        project = proj_resp.json()
        s_resp = await client.post(
            "/api/suggestions",
            json={
                "project_id": project["id"],
                "target_node_id": project["root_node_id"],
                "action_type": "add_child",
            },
        )
        suggestion = s_resp.json()

        resp = await client.patch(
            f"/api/suggestions/{suggestion['id']}",
            json={"status": "approved", "reviewed_by": "admin"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        assert resp.json()["reviewed_by"] == "admin"
        assert resp.json()["reviewed_at"] is not None

    async def test_review_non_pending_returns_422(self, client):
        proj_resp = await client.post(
            "/api/projects", json={"name": "Double Review", "description": "d", "goal": "g"}
        )
        project = proj_resp.json()
        s_resp = await client.post(
            "/api/suggestions",
            json={
                "project_id": project["id"],
                "target_node_id": project["root_node_id"],
                "action_type": "add_child",
            },
        )
        suggestion = s_resp.json()

        # First review
        await client.patch(
            f"/api/suggestions/{suggestion['id']}",
            json={"status": "rejected"},
        )

        # Second review should fail
        resp = await client.patch(
            f"/api/suggestions/{suggestion['id']}",
            json={"status": "approved"},
        )
        assert resp.status_code == 422


class TestBatchReviewRoute:
    async def test_batch_review_approves_multiple(self, client):
        proj_resp = await client.post(
            "/api/projects", json={"name": "Batch Test", "description": "d", "goal": "g"}
        )
        project = proj_resp.json()

        ids = []
        for _ in range(3):
            s_resp = await client.post(
                "/api/suggestions",
                json={
                    "project_id": project["id"],
                    "target_node_id": project["root_node_id"],
                    "action_type": "add_child",
                },
            )
            ids.append(s_resp.json()["id"])

        resp = await client.post(
            "/api/suggestions/batch-review",
            json={"suggestion_ids": ids, "status": "approved", "reviewed_by": "batch"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 3
        assert all(s["status"] == "approved" for s in resp.json())


class TestDeleteSuggestionRoute:
    async def test_delete_returns_204(self, client):
        proj_resp = await client.post(
            "/api/projects", json={"name": "Delete Test", "description": "d", "goal": "g"}
        )
        project = proj_resp.json()
        s_resp = await client.post(
            "/api/suggestions",
            json={
                "project_id": project["id"],
                "target_node_id": project["root_node_id"],
                "action_type": "add_child",
            },
        )
        suggestion = s_resp.json()

        resp = await client.delete(f"/api/suggestions/{suggestion['id']}")
        assert resp.status_code == 204

        # Verify gone
        resp = await client.get(f"/api/suggestions/{suggestion['id']}")
        assert resp.status_code == 404

    async def test_delete_nonexistent_returns_404(self, client):
        resp = await client.delete("/api/suggestions/nonexistent-id")
        assert resp.status_code == 404
