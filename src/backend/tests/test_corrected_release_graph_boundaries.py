"""Corrected-release canonical graph projection boundary regressions."""
import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import func, or_, select

from db.database import async_session
from main import app
from models.models import ContentBlock, Edge, Node, Project

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
