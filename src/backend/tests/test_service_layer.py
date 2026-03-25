"""Direct service-layer tests for backend business logic."""

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from models.models import ActionLog, Edge, Node
from models.schemas import EdgeCreate, NodeCreate, ProjectCreate
from services.edge_service import create_edge, promote_mainline
from services.exceptions import ValidationError as ServiceValidationError
from services.node_service import create_node, delete_node
from services.project_service import create_project


class TestProjectService:
    async def test_create_project_creates_root_node_and_action_log(self, db_session):
        payload = ProjectCreate(name="Service Project", description="Project description", goal="Ship it")

        project = await create_project(db_session, payload)

        assert project.root_node_id is not None
        root_node = await db_session.get(Node, project.root_node_id)
        assert root_node is not None
        assert root_node.title == payload.name
        assert root_node.node_type == "concept"

        result = await db_session.execute(
            select(ActionLog).where(ActionLog.project_id == project.id, ActionLog.action_type == "create_project")
        )
        log = result.scalar_one()
        assert log.payload == {"name": payload.name}


class TestNodeService:
    async def test_create_node_with_parent_creates_mainline_edge_and_advances_parent(self, db_session):
        project = await create_project(
            db_session,
            ProjectCreate(name="Parent Project", description="A sufficiently long project description", goal="Goal"),
        )

        node = await create_node(
            db_session,
            project.id,
            NodeCreate(title="Child", summary="Child summary", parent_id=project.root_node_id),
        )

        edge_result = await db_session.execute(select(Edge).where(Edge.to_node_id == node.id))
        edge = edge_result.scalar_one()
        assert edge.from_node_id == project.root_node_id
        assert edge.is_mainline is True

        root = await db_session.get(Node, project.root_node_id)
        assert root is not None
        assert root.maturity == "rough"

    async def test_delete_node_removes_incident_edges(self, db_session):
        project = await create_project(
            db_session,
            ProjectCreate(name="Delete Project", description="A sufficiently long project description", goal="Goal"),
        )
        child = await create_node(
            db_session,
            project.id,
            NodeCreate(title="Child", summary="Child summary", parent_id=project.root_node_id),
        )
        grandchild = await create_node(
            db_session,
            project.id,
            NodeCreate(title="Grandchild", summary="Grandchild summary", parent_id=child.id),
        )

        await delete_node(db_session, child.id)

        assert await db_session.get(Node, child.id) is None
        assert await db_session.get(Node, grandchild.id) is not None
        remaining_edges = await db_session.execute(
            select(Edge).where((Edge.from_node_id == child.id) | (Edge.to_node_id == child.id))
        )
        assert remaining_edges.scalars().all() == []

    async def test_delete_root_node_raises_validation_error(self, db_session):
        project = await create_project(
            db_session,
            ProjectCreate(name="Root Project", description="Description", goal="Goal"),
        )

        with pytest.raises(ServiceValidationError, match="Cannot delete the project root node"):
            await delete_node(db_session, project.root_node_id)


class TestEdgeService:
    async def test_create_edge_rejects_cross_project_nodes(self, db_session):
        project_one = await create_project(
            db_session,
            ProjectCreate(name="Project One", description="Description one", goal="Goal"),
        )
        project_two = await create_project(
            db_session,
            ProjectCreate(name="Project Two", description="Description two", goal="Goal"),
        )

        with pytest.raises(ServiceValidationError, match="Nodes must be in same project"):
            await create_edge(
                db_session,
                EdgeCreate(from_node_id=project_one.root_node_id, to_node_id=project_two.root_node_id),
            )

    async def test_promote_mainline_demotes_sibling_edges(self, db_session):
        project = await create_project(
            db_session,
            ProjectCreate(name="Promote Project", description="Long enough description", goal="Goal"),
        )
        child_one = await create_node(
            db_session,
            project.id,
            NodeCreate(title="Child One", summary="Child one summary", parent_id=project.root_node_id),
        )
        child_two = await create_node(
            db_session,
            project.id,
            NodeCreate(title="Child Two", summary="Child two summary", parent_id=project.root_node_id),
        )
        child_three = await create_node(
            db_session,
            project.id,
            NodeCreate(title="Child Three", summary="Child three summary"),
        )

        second_edge = await create_edge(
            db_session,
            EdgeCreate(
                from_node_id=project.root_node_id,
                to_node_id=child_three.id,
                relation_type="child_of",
                is_mainline=True,
            ),
        )

        promoted = await promote_mainline(db_session, second_edge.id)

        assert promoted.is_mainline is True
        sibling_edges = await db_session.execute(
            select(Edge).where(Edge.from_node_id == project.root_node_id, Edge.relation_type == "child_of")
        )
        edges = {edge.to_node_id: edge.is_mainline for edge in sibling_edges.scalars().all()}
        assert edges[child_one.id] is False
        assert edges[child_two.id] is False
        assert edges[child_three.id] is True


class TestSchemaEnumValidation:
    def test_node_create_rejects_invalid_node_type(self):
        with pytest.raises(PydanticValidationError):
            NodeCreate(title="Bad Node", node_type="invalid-type")
