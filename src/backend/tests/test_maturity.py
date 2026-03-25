"""Tests for maturity auto-advance behavior."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.models import ContentBlock, Edge, Node, Project
from services.node_service import auto_advance_maturity
from tests.factories import NodeFactory, ProjectFactory


class TestAutoAdvanceMaturity:
    async def test_auto_advance_maturity_transitions(self, client):
        project_resp = await client.post(
            "/api/projects",
            json=ProjectFactory.create(description="This summary is long enough to count."),
        )
        project = project_resp.json()
        root_id = project["root_node_id"]

        child_one_resp = await client.post(
            f"/api/projects/{project['id']}/nodes",
            json=NodeFactory.create(parent_id=root_id),
        )
        assert child_one_resp.status_code == 201

        root_resp = await client.get(f"/api/nodes/{root_id}")
        assert root_resp.json()["maturity"] == "rough"

        first_block_resp = await client.post(
            f"/api/nodes/{root_id}/blocks",
            json={"block_type": "notes", "content": {"body": "one"}},
        )
        assert first_block_resp.status_code == 201

        root_resp = await client.get(f"/api/nodes/{root_id}")
        assert root_resp.json()["maturity"] == "developing"

        child_two_resp = await client.post(
            f"/api/projects/{project['id']}/nodes",
            json=NodeFactory.create(parent_id=root_id),
        )
        assert child_two_resp.status_code == 201

        second_block_resp = await client.post(
            f"/api/nodes/{root_id}/blocks",
            json={"block_type": "notes", "content": {"body": "two"}},
        )
        assert second_block_resp.status_code == 201

        third_block_resp = await client.post(
            f"/api/nodes/{root_id}/blocks",
            json={"block_type": "notes", "content": {"body": "three"}},
        )
        assert third_block_resp.status_code == 201

        root_resp = await client.get(f"/api/nodes/{root_id}")
        assert root_resp.json()["maturity"] == "stable"

    async def test_auto_advance_maturity_keeps_concurrent_finalized_state(self, db_session, engine, monkeypatch):
        project_id = str(uuid.uuid4())
        root_id = str(uuid.uuid4())
        child_one_id = str(uuid.uuid4())
        child_two_id = str(uuid.uuid4())

        project = Project(
            id=project_id,
            name="Project",
            description="This summary is long enough to count.",
            root_node_id=root_id,
        )
        root = Node(
            id=root_id,
            project_id=project_id,
            title="Root",
            summary="This summary is long enough to count.",
            maturity="seed",
            node_type="concept",
        )
        child_one = Node(id=child_one_id, project_id=project_id, title="Child 1", node_type="idea")
        child_two = Node(id=child_two_id, project_id=project_id, title="Child 2", node_type="idea")
        db_session.add_all([
            project,
            root,
            child_one,
            child_two,
            Edge(project_id=project_id, from_node_id=root_id, to_node_id=child_one_id, relation_type="child_of"),
            Edge(project_id=project_id, from_node_id=root_id, to_node_id=child_two_id, relation_type="child_of"),
            ContentBlock(node_id=root_id, block_type="notes", content={"body": "one"}, order_index=0),
            ContentBlock(node_id=root_id, block_type="notes", content={"body": "two"}, order_index=1),
            ContentBlock(node_id=root_id, block_type="notes", content={"body": "three"}, order_index=2),
        ])
        await db_session.commit()

        original_execute = db_session.execute
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        execute_count = {"value": 0}

        async def execute_with_concurrent_finalize(*args, **kwargs):
            result = await original_execute(*args, **kwargs)
            execute_count["value"] += 1
            if execute_count["value"] == 2:
                async with session_factory() as other_session:
                    competing_root = await other_session.get(Node, root_id)
                    competing_root.maturity = "finalized"
                    await other_session.commit()
            return result

        monkeypatch.setattr(db_session, "execute", execute_with_concurrent_finalize)

        await auto_advance_maturity(db_session, root_id)
        await db_session.commit()

        refreshed_root = await db_session.get(Node, root_id)
        assert refreshed_root is not None
        assert refreshed_root.maturity == "finalized"
