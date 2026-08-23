"""Corrected-release canonical graph projection boundary regressions."""
import asyncio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, or_, select

from db.database import async_session, engine
from main import app
from models.models import ActionLog, Branch, ContentBlock, Edge, Node, Project

AUTHORITY_MODELS = (Project, Branch, Node, Edge, ActionLog)

async def authority_snapshot():
    """Exact logical state used to prove rejected/faulted deletes are atomic."""
    async with async_session() as db:
        result = []
        for model in AUTHORITY_MODELS:
            columns = tuple(model.__table__.columns)
            rows = (await db.execute(select(model).order_by(model.id))).scalars().all()
            result.append(tuple(tuple(getattr(row, column.name) for column in columns) for row in rows))
        return tuple(result)

async def execute_with_foreign_keys_disabled(*statements):
    """Build an imported/corrupt fixture without weakening the application connection."""
    async with engine.connect() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await connection.commit()
        try:
            for statement, parameters in statements:
                await connection.exec_driver_sql(statement, parameters)
            await connection.commit()
        finally:
            await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            await connection.commit()

def project_revision(client, project_id):
    return client.get(f"/api/projects/{project_id}").json()["revision"]

def node_revision(client, node_id):
    return client.get(f"/api/nodes/{node_id}").json()["revision"]

def create_node(client, project_id, title, parent_id=None, branch_id=None):
    payload = {"title": title, "expected_project_revision": project_revision(client, project_id)}
    if parent_id:
        payload.update(parent_id=parent_id, expected_parent_revision=node_revision(client, parent_id))
    if branch_id:
        payload["branch_id"] = branch_id
    response = client.post(f"/api/projects/{project_id}/nodes", json=payload)
    assert response.status_code == 201, response.text
    return response.json()

def delete_node(client, project_id, node):
    return client.request("DELETE", f"/api/nodes/{node['id']}", json={
        "expected_project_revision": project_revision(client, project_id),
        "expected_revision": node_revision(client, node["id"]),
    })

def create_block(client, project_id, node_id, block_type):
    response = client.post(f"/api/nodes/{node_id}/blocks", json={
        "expected_project_revision": project_revision(client, project_id),
        "expected_node_revision": node_revision(client, node_id),
        "block_type": block_type, "content": {"title": block_type}, "order_index": 0,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_create_then_inverse_delete_is_durable_and_root_delete_remains_forbidden():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "durable undo"}).json()
        child = create_node(client, project["id"], "temporary", project["root_node_id"])
        assert delete_node(client, project["id"], child).status_code == 204
        assert client.get(f"/api/nodes/{child['id']}").status_code == 404
        assert all(row["id"] != child["id"] for row in client.get(f"/api/projects/{project['id']}/nodes").json())
        root = client.get(f"/api/nodes/{project['root_node_id']}").json()
        assert delete_node(client, project["id"], root).status_code == 409
    # Reopen the app lifespan as a restart-equivalent readback against the same DB.
    with TestClient(app) as restarted:
        assert restarted.get(f"/api/nodes/{child['id']}").status_code == 404

def test_parent_delete_removes_entire_subtree_content_and_edges_without_orphans():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "subtree delete"}).json()
        parent = create_node(client, project["id"], "parent", project["root_node_id"])
        child = create_node(client, project["id"], "child", parent["id"])
        grandchild = create_node(client, project["id"], "grandchild", child["id"])
        create_block(client, project["id"], child["id"], "paragraph")
        assert delete_node(client, project["id"], parent).status_code == 204
        for node in (parent, child, grandchild):
            assert client.get(f"/api/nodes/{node['id']}").status_code == 404
        listed = {row["id"] for row in client.get(f"/api/projects/{project['id']}/nodes").json()}
        assert listed == {project["root_node_id"]}
        async def durable_counts():
            ids = {parent["id"], child["id"], grandchild["id"]}
            async with async_session() as db:
                return (
                    await db.scalar(select(func.count()).select_from(Node).where(Node.id.in_(ids))),
                    await db.scalar(select(func.count()).select_from(ContentBlock).where(ContentBlock.node_id.in_(ids))),
                    await db.scalar(select(func.count()).select_from(Edge).where(or_(Edge.from_node_id.in_(ids), Edge.to_node_id.in_(ids)))),
                )
        assert asyncio.run(durable_counts()) == (0, 0, 0)
    with TestClient(app) as restarted:
        tree = restarted.get(f"/api/nodes/{project['root_node_id']}/subtree").json()
        assert tree["children"] == []

def test_branch_only_node_is_excluded_from_main_list_but_visible_in_branch_views():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "branch projection"}).json()
        branch_response = client.post(f"/api/projects/{project['id']}/branches", json={
            "expected_project_revision": project_revision(client, project["id"]),
            "source_node_id": project["root_node_id"], "name": "scenario",
        })
        assert branch_response.status_code == 201, branch_response.text
        branch = branch_response.json()
        branch_tree = client.get(f"/api/branches/{branch['id']}/subtree").json()["tree"]
        branch_child = create_node(client, project["id"], "branch-only", branch_tree["id"], branch["id"])
        main_ids = {row["id"] for row in client.get(f"/api/projects/{project['id']}/nodes").json()}
        assert branch_child["id"] not in main_ids
        tree = client.get(f"/api/branches/{branch['id']}/subtree").json()["tree"]
        assert tree["children"][0]["id"] == branch_child["id"]
        comparison = client.get(f"/api/branches/{branch['id']}/compare")
        assert comparison.status_code == 200
        assert client.get(f"/api/branches/{branch['id']}/history").status_code == 200

def test_subtree_delete_rejects_cross_project_branch_root_and_cycles_without_changes():
    async def corrupt(case, project_a, project_b, parent, ordinary_b, branch_node):
        async with async_session() as db:
            if case == "cross-root": target = project_b["root_node_id"]
            elif case == "cross-node": target = ordinary_b["id"]
            elif case == "branch": target = branch_node["id"]
            elif case == "own-root": target = project_a["root_node_id"]
            else: target = parent["id"]
            source = parent["id"] if case != "cycle" else ordinary_b["id"]
            db.add(Edge(project_id=project_a["id"], from_node_id=source, to_node_id=target, relation_type="child_of"))
            await db.commit()

    for case in ("cross-root", "cross-node", "branch", "own-root", "cycle"):
        with TestClient(app) as client:
            a = client.post("/api/projects", json={"name": f"a-{case}"}).json()
            b = client.post("/api/projects", json={"name": f"b-{case}"}).json()
            parent = create_node(client, a["id"], "parent", a["root_node_id"])
            ordinary_b = (create_node(client, a["id"], "cycle-child", parent["id"])
                          if case == "cycle" else create_node(client, b["id"], "b-child", b["root_node_id"]))
            branch_response = client.post(f"/api/projects/{a['id']}/branches", json={
                "expected_project_revision": project_revision(client, a["id"]),
                "source_node_id": a["root_node_id"], "name": "branch",
            }).json()
            branch_node = client.get(f"/api/branches/{branch_response['id']}/subtree").json()["tree"]
            asyncio.run(corrupt(case, a, b, parent, ordinary_b, branch_node))
            before_a = client.get(f"/api/projects/{a['id']}/nodes").json()
            before_b = client.get(f"/api/projects/{b['id']}/nodes").json()
            response = delete_node(client, a["id"], parent)
            assert response.status_code == 409, (case, response.text)
            assert client.get(f"/api/projects/{a['id']}/nodes").json() == before_a
            assert client.get(f"/api/projects/{b['id']}/nodes").json() == before_b

def test_main_exports_and_agent_grants_exclude_branch_projection_but_branch_view_keeps_it():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "projection parity"}).json()
        branch = client.post(f"/api/projects/{project['id']}/branches", json={
            "expected_project_revision": project_revision(client, project["id"]),
            "source_node_id": project["root_node_id"], "name": "secret scenario",
        }).json()
        branch_root = client.get(f"/api/branches/{branch['id']}/subtree").json()["tree"]
        branch_child = create_node(client, project["id"], "BRANCH-ONLY-MARKER", branch_root["id"], branch["id"])
        assert "BRANCH-ONLY-MARKER" not in client.get(f"/api/projects/{project['id']}/export").text
        exported = client.get(f"/api/projects/{project['id']}/export-json").json()
        assert branch_child["id"] not in {row["id"] for row in exported["nodes"]}
        assert "BRANCH-ONLY-MARKER" not in client.get(f"/api/projects/{project['id']}/export-spec").text
        assert branch_child["id"] in str(client.get(f"/api/branches/{branch['id']}/subtree").json())
        from agent_port.service import allowed_nodes
        from types import SimpleNamespace
        async def scopes():
            async with async_session() as db:
                main = await allowed_nodes(db, SimpleNamespace(project_id=project["id"], node_scope_id=None, branch_root_id=None))
                scoped = await allowed_nodes(db, SimpleNamespace(project_id=project["id"], node_scope_id=None, branch_root_id=branch_root["id"]))
                return main, scoped
        main, scoped = asyncio.run(scopes())
        assert branch_child["id"] not in main
        assert {branch_root["id"], branch_child["id"]}.issubset(scoped)
        assert client.get(f"/api/branches/{branch['id']}/compare").status_code == 200
        assert client.get(f"/api/branches/{branch['id']}/history").status_code == 200

def test_delete_rejects_diamond_parallel_and_different_depth_repeated_targets_without_any_change():
    async def add_edges(project_id, pairs):
        async with async_session() as db:
            for source, target in pairs:
                db.add(Edge(project_id=project_id, from_node_id=source, to_node_id=target, relation_type="child_of"))
            await db.commit()

    async def snapshot(project_ids):
        async with async_session() as db:
            projects=(await db.execute(select(Project).where(Project.id.in_(project_ids)).order_by(Project.id))).scalars().all()
            nodes=(await db.execute(select(Node).where(Node.project_id.in_(project_ids)).order_by(Node.id))).scalars().all()
            edges=(await db.execute(select(Edge).where(Edge.project_id.in_(project_ids)).order_by(Edge.id))).scalars().all()
            return (
                [(p.id,p.revision,p.root_node_id,p.updated_at) for p in projects],
                [(n.id,n.project_id,n.branch_id,n.revision,n.title,n.updated_at) for n in nodes],
                [(e.id,e.project_id,e.from_node_id,e.to_node_id,e.relation_type,e.revision) for e in edges],
            )

    for case in ("diamond", "parallel", "different-depth", "external-parent"):
        with TestClient(app) as client:
            project=client.post("/api/projects",json={"name":case}).json()
            other=client.post("/api/projects",json={"name":f"other-{case}"}).json()
            parent=create_node(client,project["id"],"parent",project["root_node_id"])
            left=create_node(client,project["id"],"left",parent["id"])
            right=create_node(client,project["id"],"right",parent["id"])
            shared=create_node(client,project["id"],"shared",left["id"])
            if case=="diamond": pairs=[(right["id"],shared["id"])]
            elif case=="parallel": pairs=[(left["id"],shared["id"])]
            elif case=="external-parent":
                outside=create_node(client,project["id"],"outside",project["root_node_id"])
                pairs=[(outside["id"],shared["id"])]
            else:
                mid=create_node(client,project["id"],"mid",right["id"])
                pairs=[(mid["id"],shared["id"])]
            asyncio.run(add_edges(project["id"],pairs))
            before=asyncio.run(snapshot([project["id"],other["id"]]))
            response=delete_node(client,project["id"],parent)
            assert response.status_code==409,(case,response.text)
            assert asyncio.run(snapshot([project["id"],other["id"]]))==before

def test_foreign_project_noncontainment_edge_rejects_with_both_projects_unchanged():
    with TestClient(app) as client:
        a=client.post("/api/projects",json={"name":"incident-a"}).json()
        b=client.post("/api/projects",json={"name":"incident-b"}).json()
        victim=create_node(client,a["id"],"victim",a["root_node_id"])
        async def seed_and_snapshot(seed=False):
            async with async_session() as db:
                if seed:
                    db.add(Edge(project_id=b["id"],from_node_id=b["root_node_id"],to_node_id=victim["id"],relation_type="related_to"))
                    db.add(ActionLog(project_id=a["id"],node_id=victim["id"],actor_type="human",action_type="kept_on_reject",payload={"safe":True}))
                    await db.commit()
                projects=(await db.execute(select(Project).where(Project.id.in_([a["id"],b["id"]])).order_by(Project.id))).scalars().all()
                edges=(await db.execute(select(Edge).where(Edge.project_id.in_([a["id"],b["id"]])).order_by(Edge.id))).scalars().all()
                logs=(await db.execute(select(ActionLog).where(ActionLog.project_id.in_([a["id"],b["id"]])).order_by(ActionLog.id))).scalars().all()
                return ([(p.id,p.revision,p.updated_at) for p in projects],[(e.id,e.project_id,e.from_node_id,e.to_node_id,e.relation_type) for e in edges],[(r.id,r.project_id,r.node_id,r.action_type,r.payload) for r in logs])
        before=asyncio.run(seed_and_snapshot(True))
        response=delete_node(client,a["id"],victim)
        assert response.status_code==409,response.text
        assert asyncio.run(seed_and_snapshot())==before
        assert client.get(f"/api/nodes/{victim['id']}").status_code==200


def test_active_branch_root_delete_rejects_without_revision_edge_or_log_changes():
    with TestClient(app) as client:
        project=client.post("/api/projects",json={"name":"branch authority"}).json()
        branch=client.post(f"/api/projects/{project['id']}/branches",json={"expected_project_revision":project_revision(client,project["id"]),"source_node_id":project["root_node_id"],"name":"active"}).json()
        root=client.get(f"/api/branches/{branch['id']}/subtree").json()["tree"]
        async def snapshot():
            async with async_session() as db:
                p=await db.get(Project,project["id"])
                edges=(await db.execute(select(Edge).where(Edge.project_id==project["id"]))).scalars().all()
                logs=(await db.execute(select(ActionLog).where(ActionLog.project_id==project["id"]))).scalars().all()
                return p.revision,[(e.id,e.from_node_id,e.to_node_id,e.relation_type) for e in edges],[(r.id,r.node_id,r.action_type) for r in logs]
        before=asyncio.run(snapshot());response=delete_node(client,project["id"],root)
        assert response.status_code==409,response.text
        assert asyncio.run(snapshot())==before
        assert client.get(f"/api/nodes/{root['id']}").status_code==200


def test_subtree_delete_removes_bound_logs_and_malformed_rollback_preserves_them():
    with TestClient(app) as client:
        project=client.post("/api/projects",json={"name":"log custody"}).json()
        parent=create_node(client,project["id"],"parent",project["root_node_id"])
        child=create_node(client,project["id"],"child",parent["id"])
        async def seed_log(node_id,kind):
            async with async_session() as db:
                db.add(ActionLog(project_id=project["id"],node_id=node_id,actor_type="human",action_type=kind,payload={"kind":kind}));await db.commit()
        async def counts():
            async with async_session() as db:
                p=await db.get(Project,project["id"])
                return p.revision,await db.scalar(select(func.count()).select_from(Edge).where(Edge.project_id==project["id"])),await db.scalar(select(func.count()).select_from(ActionLog).where(ActionLog.project_id==project["id"])),await db.scalar(select(func.count()).select_from(ActionLog).where(ActionLog.node_id.in_([parent["id"],child["id"]])))
        asyncio.run(seed_log(child["id"],"delete-with-child"));assert delete_node(client,project["id"],parent).status_code==204
        after=asyncio.run(counts());assert after[3]==0
        victim=create_node(client,project["id"],"rollback-victim",project["root_node_id"]);other=client.post("/api/projects",json={"name":"foreign rollback"}).json()
        asyncio.run(seed_log(victim["id"],"must-survive-reject"))
        async def corrupt():
            async with async_session() as db:
                db.add(ActionLog(project_id=other["id"],node_id=victim["id"],actor_type="human",action_type="foreign-bound",payload={"foreign":True}));await db.commit()
        async def full_snapshot():
            async with async_session() as db:
                projects=(await db.execute(select(Project).where(Project.id.in_([project["id"],other["id"]])).order_by(Project.id))).scalars().all()
                edges=(await db.execute(select(Edge).where(Edge.project_id.in_([project["id"],other["id"]])).order_by(Edge.id))).scalars().all()
                logs=(await db.execute(select(ActionLog).where(ActionLog.project_id.in_([project["id"],other["id"]])).order_by(ActionLog.id))).scalars().all()
                return ([(p.id,p.revision,p.updated_at) for p in projects],[(e.id,e.project_id,e.from_node_id,e.to_node_id,e.relation_type) for e in edges],[(r.id,r.project_id,r.node_id,r.action_type,r.payload) for r in logs])
        asyncio.run(corrupt());before=asyncio.run(full_snapshot())
        assert delete_node(client,project["id"],victim).status_code==409
        assert asyncio.run(full_snapshot())==before


def test_successful_delete_preserves_unrelated_edges_and_logs_exactly():
    with TestClient(app) as client:
        project=client.post("/api/projects",json={"name":"exact delete"}).json();other=client.post("/api/projects",json={"name":"foreign exact"}).json()
        victim=create_node(client,project["id"],"victim",project["root_node_id"])
        survivor=create_node(client,project["id"],"survivor",project["root_node_id"])
        async def seed_and_read(seed=False):
            async with async_session() as db:
                if seed:
                    db.add_all([
                        Edge(project_id=project["id"],from_node_id=project["root_node_id"],to_node_id=survivor["id"],relation_type="related_to"),
                        ActionLog(project_id=project["id"],node_id=victim["id"],actor_type="human",action_type="remove",payload={}),
                        ActionLog(project_id=project["id"],node_id=survivor["id"],actor_type="human",action_type="keep-node",payload={}),
                        ActionLog(project_id=project["id"],node_id=None,actor_type="human",action_type="keep-null",payload={}),
                        ActionLog(project_id=other["id"],node_id=other["root_node_id"],actor_type="human",action_type="keep-foreign",payload={}),
                    ]);await db.commit()
                edges=(await db.execute(select(Edge).where(Edge.project_id.in_([project["id"],other["id"]])).order_by(Edge.id))).scalars().all()
                logs=(await db.execute(select(ActionLog).where(ActionLog.project_id.in_([project["id"],other["id"]])).order_by(ActionLog.id))).scalars().all()
                return [(e.id,e.project_id,e.from_node_id,e.to_node_id,e.relation_type) for e in edges],[(r.id,r.project_id,r.node_id,r.action_type,r.payload) for r in logs]
        before_edges,before_logs=asyncio.run(seed_and_read(True));assert delete_node(client,project["id"],victim).status_code==204
        after_edges,after_logs=asyncio.run(seed_and_read())
        expected_edges=[row for row in before_edges if victim["id"] not in (row[2],row[3])]
        expected_logs=[row for row in before_logs if not (row[1]==project["id"] and row[2]==victim["id"])]
        assert after_edges==expected_edges;assert after_logs==expected_logs


@pytest.mark.parametrize("case",[
    "absent_branch","wrong_project_branch","empty_branch_attachment","missing_source",
    "foreign_project_source","wrong_branch_source","edge_project_mismatch_inbound",
    "edge_project_mismatch_outbound","pure_cycle","multiple_disconnected_components",
])
def test_malformed_branch_authority_matrix_is_zero_mutation(case):
    """Every imported authority corruption is a 409 with an exact DB rollback."""
    with TestClient(app) as client:
        project=client.post("/api/projects",json={"name":f"branch-{case}"}).json()
        other=client.post("/api/projects",json={"name":f"other-{case}"}).json()
        branch=client.post(f"/api/projects/{project['id']}/branches",json={
            "expected_project_revision":project_revision(client,project["id"]),
            "source_node_id":project["root_node_id"],"name":"authority",
        }).json()
        root=client.get(f"/api/branches/{branch['id']}/subtree").json()["tree"]
        child=create_node(client,project["id"],"branch-child",root["id"],branch["id"])
        target=child
        second_root=None
        if case=="wrong_branch_source":
            second=client.post(f"/api/projects/{project['id']}/branches",json={
                "expected_project_revision":project_revision(client,project["id"]),
                "source_node_id":project["root_node_id"],"name":"second",
            }).json()
            second_root=client.get(f"/api/branches/{second['id']}/subtree").json()["tree"]

        async def seed():
            nonlocal target
            edge_id=None
            async with async_session() as db:
                edge=(await db.execute(select(Edge).where(
                    Edge.from_node_id==root["id"],Edge.to_node_id==child["id"],
                    Edge.relation_type=="child_of",
                ))).scalars().one()
                db.add(ActionLog(project_id=project["id"],node_id=child["id"],actor_type="human",action_type=f"reject-{case}",payload={"case":case}))
                if case=="wrong_project_branch":
                    branch_row=await db.get(Branch,branch["id"]);branch_row.project_id=other["id"]
                elif case=="empty_branch_attachment":
                    empty=Branch(project_id=project["id"],name="initially-empty",source_node_id=project["root_node_id"])
                    db.add(empty);await db.flush()
                    victim=Node(project_id=project["id"],branch_id=empty.id,title="later corrupt attachment")
                    db.add(victim);await db.flush();target={"id":str(victim.id)}
                elif case=="foreign_project_source":
                    edge.from_node_id=other["root_node_id"]
                elif case=="wrong_branch_source":
                    edge.from_node_id=second_root["id"]
                elif case=="edge_project_mismatch_inbound":
                    edge.project_id=other["id"]
                elif case=="edge_project_mismatch_outbound":
                    leaf=Node(project_id=project["id"],branch_id=branch["id"],title="leaf")
                    db.add(leaf);await db.flush()
                    db.add(Edge(project_id=other["id"],from_node_id=child["id"],to_node_id=leaf.id,relation_type="child_of"))
                elif case=="pure_cycle":
                    edge.from_node_id=child["id"];edge.to_node_id=root["id"]
                    db.add(Edge(project_id=project["id"],from_node_id=root["id"],to_node_id=child["id"],relation_type="child_of"))
                elif case=="multiple_disconnected_components":
                    nodes=[Node(project_id=project["id"],branch_id=branch["id"],title=f"component-{i}") for i in range(4)]
                    db.add_all(nodes);await db.flush()
                    db.add_all([
                        Edge(project_id=project["id"],from_node_id=nodes[0].id,to_node_id=nodes[1].id,relation_type="child_of"),
                        Edge(project_id=project["id"],from_node_id=nodes[1].id,to_node_id=nodes[0].id,relation_type="child_of"),
                        Edge(project_id=project["id"],from_node_id=nodes[2].id,to_node_id=nodes[3].id,relation_type="child_of"),
                        Edge(project_id=project["id"],from_node_id=nodes[3].id,to_node_id=nodes[2].id,relation_type="child_of"),
                    ])
                edge_id=str(edge.id)
                await db.commit()
            if case=="absent_branch":
                await execute_with_foreign_keys_disabled(("DELETE FROM branches WHERE id=?",(branch["id"],)))
            elif case=="missing_source":
                await execute_with_foreign_keys_disabled(("UPDATE edges SET from_node_id=? WHERE id=?",("00000000-0000-0000-0000-000000000099",edge_id)))

        asyncio.run(seed())
        before=asyncio.run(authority_snapshot())
        response=delete_node(client,project["id"],target)
        assert response.status_code==409,(case,response.text)
        assert asyncio.run(authority_snapshot())==before


def test_large_legal_subtree_delete_is_exact_and_preserves_unrelated_authority():
    with TestClient(app) as client:
        project=client.post("/api/projects",json={"name":"large exact delete"}).json()
        foreign=client.post("/api/projects",json={"name":"large foreign"}).json()
        parent=create_node(client,project["id"],"wide parent",project["root_node_id"])
        survivor=create_node(client,project["id"],"survivor",project["root_node_id"])
        async def seed_and_snapshot(seed=False):
            async with async_session() as db:
                if seed:
                    children=[Node(project_id=project["id"],title=f"legal-{i}") for i in range(501)]
                    db.add_all(children);await db.flush()
                    db.add_all([Edge(project_id=project["id"],from_node_id=parent["id"],to_node_id=n.id,relation_type="child_of") for n in children])
                    db.add_all([ActionLog(project_id=project["id"],node_id=n.id,actor_type="human",action_type="bound",payload={"i":i}) for i,n in enumerate(children)])
                    db.add_all([
                        ActionLog(project_id=project["id"],node_id=parent["id"],actor_type="human",action_type="bound-parent",payload={}),
                        ActionLog(project_id=project["id"],node_id=survivor["id"],actor_type="human",action_type="keep-node",payload={}),
                        ActionLog(project_id=project["id"],node_id=None,actor_type="human",action_type="keep-null",payload={}),
                        ActionLog(project_id=foreign["id"],node_id=foreign["root_node_id"],actor_type="human",action_type="keep-foreign",payload={}),
                        Edge(project_id=project["id"],from_node_id=project["root_node_id"],to_node_id=survivor["id"],relation_type="related_to"),
                    ])
                    await db.commit();deleted={parent["id"],*(str(n.id) for n in children)}
                else: deleted=set()
                snapshot=await authority_snapshot()
                return deleted,snapshot
        deleted,before=asyncio.run(seed_and_snapshot(True))
        assert delete_node(client,project["id"],parent).status_code==204
        _,after=asyncio.run(seed_and_snapshot())
        projects_before,branches_before,nodes_before,edges_before,logs_before=before
        projects_after,branches_after,nodes_after,edges_after,logs_after=after
        expected_projects=[]
        for row in projects_before:
            mutable=list(row)
            if row[0]==project["id"]:
                revision_index=[c.name for c in Project.__table__.columns].index("revision")
                updated_index=[c.name for c in Project.__table__.columns].index("updated_at")
                mutable[revision_index]=row[revision_index]+1
                mutable[updated_index]=projects_after[[r[0] for r in projects_after].index(row[0])][updated_index]
            expected_projects.append(tuple(mutable))
        assert projects_after==tuple(expected_projects)
        assert branches_after==branches_before
        assert nodes_after==tuple(row for row in nodes_before if row[0] not in deleted)
        edge_columns=[c.name for c in Edge.__table__.columns]
        source_i,target_i=edge_columns.index("from_node_id"),edge_columns.index("to_node_id")
        assert edges_after==tuple(row for row in edges_before if row[source_i] not in deleted and row[target_i] not in deleted)
        log_columns=[c.name for c in ActionLog.__table__.columns];project_i,node_i=log_columns.index("project_id"),log_columns.index("node_id")
        assert logs_after==tuple(row for row in logs_before if not (row[project_i]==project["id"] and row[node_i] in deleted))
        foreign_i=[r[0] for r in projects_before].index(foreign["id"])
        assert projects_after[foreign_i]==projects_before[foreign_i]


def test_branch_authority_executes_under_conservative_parameter_budget():
    from sqlalchemy import event
    from db.database import engine
    with TestClient(app) as client:
        project=client.post("/api/projects",json={"name":"parameter budget"}).json()
        branch=client.post(f"/api/projects/{project['id']}/branches",json={"expected_project_revision":project_revision(client,project["id"]),"source_node_id":project["root_node_id"],"name":"budget"}).json()
        root=client.get(f"/api/branches/{branch['id']}/subtree").json()["tree"]
        leaf=create_node(client,project["id"],"leaf",root["id"],branch["id"]);counts=[]
        def before(_conn,_cursor,_statement,parameters,_context,_many):
            counts.append(len(parameters) if hasattr(parameters,"__len__") else 0)
        event.listen(engine.sync_engine,"before_cursor_execute",before)
        try: assert delete_node(client,project["id"],leaf).status_code==204
        finally: event.remove(engine.sync_engine,"before_cursor_execute",before)
        assert counts and max(counts)<=900


def test_cross_chunk_repeated_target_rejects_and_late_delete_failure_rolls_back():
    from sqlalchemy import event
    from db.database import engine
    with TestClient(app,raise_server_exceptions=False) as client:
        project=client.post("/api/projects",json={"name":"cross chunk"}).json()
        parent=create_node(client,project["id"],"wide",project["root_node_id"])
        async def seed():
            async with async_session() as db:
                children=[Node(project_id=project["id"],title=f"child-{i}") for i in range(501)];db.add_all(children);await db.flush()
                db.add_all([Edge(project_id=project["id"],from_node_id=parent["id"],to_node_id=item.id,relation_type="child_of") for item in children])
                db.add_all([ActionLog(project_id=project["id"],node_id=item.id,actor_type="human",action_type="wide",payload={}) for item in children])
                await db.commit();return [str(item.id) for item in children]
        ids=asyncio.run(seed())
        async def add_repeat():
            async with async_session() as db:
                db.add(Edge(project_id=project["id"],from_node_id=ids[-1],to_node_id=ids[0],relation_type="child_of"));await db.commit()
        asyncio.run(add_repeat());assert delete_node(client,project["id"],parent).status_code==409
        async def snapshot(remove_repeat=False):
            async with async_session() as db:
                if remove_repeat:
                    edge=(await db.execute(select(Edge).where(Edge.from_node_id==ids[-1],Edge.to_node_id==ids[0]))).scalars().one();await db.delete(edge);await db.commit()
            return await authority_snapshot()
        before=asyncio.run(snapshot(True));deletes=0
        def fail_second_node_delete(_conn,_cursor,statement,_parameters,_context,_many):
            nonlocal deletes
            if statement.lstrip().upper().startswith("DELETE FROM NODES"):
                deletes+=1
                if deletes==2:raise RuntimeError("injected late node chunk failure")
        event.listen(engine.sync_engine,"before_cursor_execute",fail_second_node_delete)
        try: response=delete_node(client,project["id"],parent)
        finally: event.remove(engine.sync_engine,"before_cursor_execute",fail_second_node_delete)
        assert response.status_code==500 and deletes==2
        assert asyncio.run(snapshot())==before


def test_export_json_omits_ambiguous_null_node_logs_but_keeps_main_node_log():
    from models.models import ActionLog
    with TestClient(app) as client:
        project=client.post("/api/projects",json={"name":"log projection"}).json()
        async def seed():
            async with async_session() as db:
                for kind in ("branch_create","branch_archive","branch_merge","branch_history"):
                    db.add(ActionLog(project_id=project["id"],node_id=None,actor_type="human",action_type=kind,payload={"branch_id":"secret","secret":"BRANCH-ONLY-SECRET"}))
                db.add(ActionLog(project_id=project["id"],node_id=project["root_node_id"],actor_type="human",action_type="main_safe",payload={"kept":True}))
                await db.commit()
        asyncio.run(seed())
        logs=client.get(f"/api/projects/{project['id']}/export-json").json()["action_logs"]
        assert any(row["action_type"]=="main_safe" and row["payload"]=={"kept":True} for row in logs)
        assert all(row["node_id"] is not None for row in logs)
        assert "BRANCH-ONLY-SECRET" not in str(logs)
