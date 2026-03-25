"""Service-layer tests for suggestion management."""

import pytest

from models.schemas import NodeCreate, ProjectCreate, SuggestionCreate, SuggestionUpdate
from services.exceptions import NotFoundError, ValidationError
from services.project_service import create_project
from services.node_service import create_node
from services.suggestion_service import (
    batch_review,
    create_suggestion,
    delete_suggestion,
    get_suggestion,
    list_suggestions,
    review_suggestion,
)


@pytest.fixture
async def project_with_node(db_session):
    """Create a project with a root node and a child node."""
    project = await create_project(
        db_session,
        ProjectCreate(name="Test Project", description="Description", goal="Goal"),
    )
    child = await create_node(
        db_session,
        project.id,
        NodeCreate(title="Child Node", summary="Child summary", parent_id=project.root_node_id),
    )
    return project, child


class TestCreateSuggestion:
    async def test_creates_suggestion_with_valid_data(self, db_session, project_with_node):
        project, child = project_with_node
        data = SuggestionCreate(
            project_id=project.id,
            target_node_id=child.id,
            action_type="add_child",
            payload={"title": "New child"},
        )

        suggestion = await create_suggestion(db_session, data)

        assert suggestion.id is not None
        assert suggestion.project_id == project.id
        assert suggestion.target_node_id == child.id
        assert suggestion.action_type == "add_child"
        assert suggestion.status == "pending"
        assert suggestion.payload == {"title": "New child"}

    async def test_rejects_nonexistent_project(self, db_session, project_with_node):
        _, child = project_with_node
        data = SuggestionCreate(
            project_id="nonexistent-project-id",
            target_node_id=child.id,
            action_type="add_child",
        )

        with pytest.raises(NotFoundError, match="Project not found"):
            await create_suggestion(db_session, data)

    async def test_rejects_nonexistent_node(self, db_session, project_with_node):
        project, _ = project_with_node
        data = SuggestionCreate(
            project_id=project.id,
            target_node_id="nonexistent-node-id",
            action_type="edit_content",
        )

        with pytest.raises(NotFoundError, match="Target node not found"):
            await create_suggestion(db_session, data)

    async def test_rejects_cross_project_node(self, db_session, project_with_node):
        project, _ = project_with_node
        other_project = await create_project(
            db_session,
            ProjectCreate(name="Other Project", description="Desc", goal="Goal"),
        )
        data = SuggestionCreate(
            project_id=project.id,
            target_node_id=other_project.root_node_id,
            action_type="add_child",
        )

        with pytest.raises(ValidationError, match="does not belong"):
            await create_suggestion(db_session, data)


class TestListSuggestions:
    async def test_lists_by_project(self, db_session, project_with_node):
        project, child = project_with_node
        for i in range(3):
            await create_suggestion(
                db_session,
                SuggestionCreate(
                    project_id=project.id,
                    target_node_id=child.id,
                    action_type="add_child",
                    payload={"index": i},
                ),
            )

        results = await list_suggestions(db_session, project.id)
        assert len(results) == 3

    async def test_filters_by_status(self, db_session, project_with_node):
        project, child = project_with_node
        s1 = await create_suggestion(
            db_session,
            SuggestionCreate(
                project_id=project.id, target_node_id=child.id, action_type="add_child"
            ),
        )
        await review_suggestion(
            db_session, s1.id, SuggestionUpdate(status="approved", reviewed_by="tester")
        )
        await create_suggestion(
            db_session,
            SuggestionCreate(
                project_id=project.id, target_node_id=child.id, action_type="edit_content"
            ),
        )

        pending = await list_suggestions(db_session, project.id, status="pending")
        assert len(pending) == 1

        approved = await list_suggestions(db_session, project.id, status="approved")
        assert len(approved) == 1


class TestReviewSuggestion:
    async def test_approves_pending_suggestion(self, db_session, project_with_node):
        project, child = project_with_node
        suggestion = await create_suggestion(
            db_session,
            SuggestionCreate(
                project_id=project.id, target_node_id=child.id, action_type="add_child"
            ),
        )

        reviewed = await review_suggestion(
            db_session, suggestion.id, SuggestionUpdate(status="approved", reviewed_by="reviewer")
        )

        assert reviewed.status == "approved"
        assert reviewed.reviewed_by == "reviewer"
        assert reviewed.reviewed_at is not None

    async def test_rejects_review_of_non_pending(self, db_session, project_with_node):
        project, child = project_with_node
        suggestion = await create_suggestion(
            db_session,
            SuggestionCreate(
                project_id=project.id, target_node_id=child.id, action_type="add_child"
            ),
        )
        await review_suggestion(
            db_session, suggestion.id, SuggestionUpdate(status="approved")
        )

        with pytest.raises(ValidationError, match="only pending"):
            await review_suggestion(
                db_session, suggestion.id, SuggestionUpdate(status="rejected")
            )

    async def test_rejects_invalid_review_status(self, db_session, project_with_node):
        project, child = project_with_node
        suggestion = await create_suggestion(
            db_session,
            SuggestionCreate(
                project_id=project.id, target_node_id=child.id, action_type="add_child"
            ),
        )

        with pytest.raises(ValidationError, match="Invalid review status"):
            await review_suggestion(
                db_session, suggestion.id, SuggestionUpdate(status="applied")
            )


class TestBatchReview:
    async def test_batch_approves_multiple(self, db_session, project_with_node):
        project, child = project_with_node
        ids = []
        for _ in range(3):
            s = await create_suggestion(
                db_session,
                SuggestionCreate(
                    project_id=project.id, target_node_id=child.id, action_type="add_child"
                ),
            )
            ids.append(s.id)

        results = await batch_review(db_session, ids, "approved", reviewed_by="batch-user")

        assert len(results) == 3
        assert all(s.status == "approved" for s in results)
        assert all(s.reviewed_by == "batch-user" for s in results)

    async def test_batch_fails_on_non_pending(self, db_session, project_with_node):
        project, child = project_with_node
        s1 = await create_suggestion(
            db_session,
            SuggestionCreate(
                project_id=project.id, target_node_id=child.id, action_type="add_child"
            ),
        )
        await review_suggestion(db_session, s1.id, SuggestionUpdate(status="approved"))
        s2 = await create_suggestion(
            db_session,
            SuggestionCreate(
                project_id=project.id, target_node_id=child.id, action_type="add_child"
            ),
        )

        with pytest.raises(ValidationError, match="only pending"):
            await batch_review(db_session, [s1.id, s2.id], "rejected")


class TestDeleteSuggestion:
    async def test_deletes_existing(self, db_session, project_with_node):
        project, child = project_with_node
        suggestion = await create_suggestion(
            db_session,
            SuggestionCreate(
                project_id=project.id, target_node_id=child.id, action_type="add_child"
            ),
        )

        await delete_suggestion(db_session, suggestion.id)

        with pytest.raises(NotFoundError):
            await get_suggestion(db_session, suggestion.id)

    async def test_raises_on_nonexistent(self, db_session):
        with pytest.raises(NotFoundError, match="Suggestion not found"):
            await delete_suggestion(db_session, "nonexistent-id")
