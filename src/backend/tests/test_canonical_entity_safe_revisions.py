"""Behavioral security contract for exact JS-safe canonical entity revisions."""
import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine

from agent_port.schemas import Batch, CreateBlock, CreateBranch, CreateEdge, CreateNode, UpdateNode
from api.revisions import TouchedEntities, check_entity_revision
from db.migrations import migrate_sqlite
from db.schema_contract import TRIGGERS, normalize_sql
from models.models import Base, Branch, ContentBlock, Edge, Node
from models.revisions import MAX_SAFE_REVISION as MAX
from models.schemas import (
    AgentArtifactReview, BranchMergeRequest, BranchOut, ContentBlockCreate,
    ContentBlockOut, ContentBlockUpdate, EdgeOut, EdgeUpdate,
    EntityRevisionRequest, NodeBrief, NodeCreate, NodeEntityRevisionRequest,
    NodeMoveRequest, NodeOut, NodeUpdate, ProjectRevisionRequest, ProjectUpdate,
    EdgeCreate, BranchCreate,
)
from tests.generated_schema_fixtures import PROJECT, generate, logical_snapshot

UID="11111111-1111-4111-8111-111111111111"
UID2="22222222-2222-4222-8222-222222222222"
NOW=datetime(2026,1,1,tzinfo=timezone.utc)

# Every canonical entity CAS field exposed by the GUI and Agent schemas. Each
# tuple is independently instantiated, so conditional model validators execute.
GUI_CAS = (
 (ProjectUpdate,{"expected_project_revision":1},"expected_project_revision"),
 (NodeCreate,{"expected_project_revision":1,"parent_id":UID,"expected_parent_revision":1,"title":"n"},"expected_project_revision"),
 (NodeCreate,{"expected_project_revision":1,"parent_id":UID,"expected_parent_revision":1,"title":"n"},"expected_parent_revision"),
 (NodeUpdate,{"expected_project_revision":1,"expected_revision":1},"expected_project_revision"),
 (NodeUpdate,{"expected_project_revision":1,"expected_revision":1},"expected_revision"),
 (EdgeCreate,{"expected_project_revision":1,"from_node_id":UID,"to_node_id":UID2},"expected_project_revision"),
 (EdgeUpdate,{"expected_project_revision":1,"expected_revision":1},"expected_project_revision"),
 (EdgeUpdate,{"expected_project_revision":1,"expected_revision":1},"expected_revision"),
 (ContentBlockCreate,{"expected_project_revision":1,"expected_node_revision":1},"expected_project_revision"),
 (ContentBlockCreate,{"expected_project_revision":1,"expected_node_revision":1},"expected_node_revision"),
 (ContentBlockUpdate,{"expected_project_revision":1,"expected_node_revision":1,"expected_revision":1},"expected_project_revision"),
 (ContentBlockUpdate,{"expected_project_revision":1,"expected_node_revision":1,"expected_revision":1},"expected_node_revision"),
 (ContentBlockUpdate,{"expected_project_revision":1,"expected_node_revision":1,"expected_revision":1},"expected_revision"),
 (NodeMoveRequest,{"new_parent_id":UID,"expected_project_revision":1,"expected_revision":1,"expected_new_parent_revision":1,"expected_old_parent_revision":1},"expected_project_revision"),
 (NodeMoveRequest,{"new_parent_id":UID,"expected_project_revision":1,"expected_revision":1,"expected_new_parent_revision":1,"expected_old_parent_revision":1},"expected_revision"),
 (NodeMoveRequest,{"new_parent_id":UID,"expected_project_revision":1,"expected_revision":1,"expected_new_parent_revision":1,"expected_old_parent_revision":1},"expected_new_parent_revision"),
 (NodeMoveRequest,{"new_parent_id":UID,"expected_project_revision":1,"expected_revision":1,"expected_new_parent_revision":1,"expected_old_parent_revision":1},"expected_old_parent_revision"),
 (BranchCreate,{"expected_project_revision":1,"source_node_id":UID,"name":"b"},"expected_project_revision"),
 (ProjectRevisionRequest,{"expected_project_revision":1},"expected_project_revision"),
 (EntityRevisionRequest,{"expected_project_revision":1,"expected_revision":1},"expected_project_revision"),
 (EntityRevisionRequest,{"expected_project_revision":1,"expected_revision":1},"expected_revision"),
 (NodeEntityRevisionRequest,{"expected_project_revision":1,"expected_revision":1,"expected_node_revision":1},"expected_project_revision"),
 (NodeEntityRevisionRequest,{"expected_project_revision":1,"expected_revision":1,"expected_node_revision":1},"expected_revision"),
 (NodeEntityRevisionRequest,{"expected_project_revision":1,"expected_revision":1,"expected_node_revision":1},"expected_node_revision"),
 (BranchMergeRequest,{"expected_project_revision":1,"expected_revision":1,"target_node_id":UID,"expected_target_revision":1},"expected_project_revision"),
 (BranchMergeRequest,{"expected_project_revision":1,"expected_revision":1,"target_node_id":UID,"expected_target_revision":1},"expected_revision"),
 (BranchMergeRequest,{"expected_project_revision":1,"expected_revision":1,"target_node_id":UID,"expected_target_revision":1},"expected_target_revision"),
 (AgentArtifactReview,{"expected_project_revision":1,"expected_node_revision":1},"expected_project_revision"),
 (AgentArtifactReview,{"expected_project_revision":1,"expected_node_revision":1},"expected_node_revision"),
)
AGENT_CAS = (
 (CreateNode,{"op":"create_node","parent_id":UID,"expected_parent_revision":1,"title":"n"},"expected_parent_revision"),
 (UpdateNode,{"op":"update_node","node_id":UID,"expected_revision":1,"fields":{"title":"n"}},"expected_revision"),
 (CreateEdge,{"op":"create_edge","from_node_id":UID,"to_node_id":UID2,"expected_from_revision":1,"expected_to_revision":1},"expected_from_revision"),
 (CreateEdge,{"op":"create_edge","from_node_id":UID,"to_node_id":UID2,"expected_from_revision":1,"expected_to_revision":1},"expected_to_revision"),
 (CreateBlock,{"op":"create_content_block","node_id":UID,"expected_node_revision":1},"expected_node_revision"),
 (CreateBranch,{"op":"create_branch","source_node_id":UID,"expected_source_revision":1,"name":"b"},"expected_source_revision"),
 (Batch,{"expected_project_revision":1,"idempotency_key":"safe-key","operations":[{"op":"update_node","node_id":UID,"expected_revision":1,"fields":{"title":"n"}}]},"expected_project_revision"),
)

@pytest.mark.parametrize("model,payload,field", GUI_CAS+AGENT_CAS, ids=lambda x: getattr(x,"__name__",str(x)))
def test_every_gui_and_agent_entity_cas_field_is_exact_js_safe(model,payload,field):
    accepted=model.model_validate({**payload,field:MAX})
    assert getattr(accepted,field)==MAX
    for invalid in (0,MAX+1):
        with pytest.raises(ValidationError): model.model_validate({**payload,field:invalid})


def _response_payload(model, revision=1):
    common={"id":UID,"revision":revision}
    if model is NodeOut:return common|{"project_id":UID2,"title":"n","node_type":"idea","status":"active","maturity":"seed","created_at":NOW,"updated_at":NOW}
    if model is NodeBrief:return common|{"title":"n","node_type":"idea","status":"active","maturity":"seed"}
    if model is EdgeOut:return common|{"project_id":UID2,"from_node_id":UID,"to_node_id":UID2,"relation_type":"supports","is_mainline":False,"created_at":NOW}
    if model is ContentBlockOut:return common|{"node_id":UID,"block_type":"paragraph","content":{},"order_index":0,"created_at":NOW,"updated_at":NOW}
    return common|{"project_id":UID2,"name":"b","description":"","source_node_id":UID,"status":"active","created_at":NOW}

@pytest.mark.parametrize("model",(NodeOut,NodeBrief,EdgeOut,ContentBlockOut,BranchOut))
def test_entity_response_models_accept_max_and_reject_unsafe_db_values(model):
    assert model.model_validate(_response_payload(model,MAX)).revision==MAX
    for invalid in (0,MAX+1):
        with pytest.raises(ValidationError): model.model_validate(_response_payload(model,invalid))

@pytest.mark.parametrize("field",("authoritative_project_revision","authoritative_parent_revision"))
def test_node_authoritative_response_revisions_are_safe(field):
    payload=_response_payload(NodeOut,MAX)|{field:MAX}
    assert getattr(NodeOut.model_validate(payload),field)==MAX
    for invalid in (0,MAX+1):
        with pytest.raises(ValidationError):NodeOut.model_validate(payload|{field:invalid})


def _fresh(path:Path):
    async def run():
        engine=create_async_engine(f"sqlite+aiosqlite:///{path}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all);await migrate_sqlite(conn)
        await engine.dispose()
    asyncio.run(run())
    db=sqlite3.connect(path)
    db.execute("INSERT INTO projects(id,name,status,created_at,updated_at,revision) VALUES(?,?,?,?,?,1)",(UID2,"p","active",NOW.isoformat(),NOW.isoformat()))
    db.execute("INSERT INTO branches(id,project_id,name,description,status,created_at,revision) VALUES(?,?,?,?,?,?,1)",(UID,UID2,"b","","active",NOW.isoformat()))
    db.execute("INSERT INTO nodes(id,project_id,title,node_type,status,maturity,workflow_status,created_at,updated_at,revision) VALUES(?,?,?,?,?,?,?,?,?,1)",(UID,UID2,"n","idea","active","seed","draft",NOW.isoformat(),NOW.isoformat()))
    db.execute("INSERT INTO nodes(id,project_id,title,node_type,status,maturity,workflow_status,created_at,updated_at,revision) VALUES(?,?,?,?,?,?,?,?,?,1)",(UID2,UID2,"n2","idea","active","seed","draft",NOW.isoformat(),NOW.isoformat()))
    db.execute("INSERT INTO edges(id,project_id,from_node_id,to_node_id,relation_type,is_mainline,created_at,revision) VALUES('edge',?,?,?,?,?,?,1)",(UID2,UID,UID2,"supports",0,NOW.isoformat()))
    db.execute("INSERT INTO content_blocks(id,node_id,block_type,content,order_index,created_at,updated_at,revision) VALUES('block',?,'paragraph','{}',0,?,?,1)",(UID,NOW.isoformat(),NOW.isoformat()))
    db.commit();return db

ENTITY_SQL={
 "nodes":("node","id",UID,"INSERT INTO nodes(id,project_id,title,node_type,status,maturity,workflow_status,created_at,updated_at,revision) VALUES('bad',?,'bad','idea','active','seed','draft',?,?,?)",(UID2,NOW.isoformat(),NOW.isoformat())),
 "edges":("edge","id","edge","INSERT INTO edges(id,project_id,from_node_id,to_node_id,relation_type,is_mainline,created_at,revision) VALUES('bad',?,?,?,'supports',0,?,?)",(UID2,UID,UID2,NOW.isoformat())),
 "content_blocks":("content block","id","block","INSERT INTO content_blocks(id,node_id,block_type,content,order_index,created_at,updated_at,revision) VALUES('bad',?,'paragraph','{}',0,?,?,?)",(UID,NOW.isoformat(),NOW.isoformat())),
 "branches":("branch","id",UID,"INSERT INTO branches(id,project_id,name,description,status,created_at,revision) VALUES('bad',?,'bad','','active',?,?)",(UID2,NOW.isoformat())),
}

@pytest.mark.parametrize("table",ENTITY_SQL)
@pytest.mark.parametrize("operation",("insert","update"))
@pytest.mark.parametrize("value",(None,"bad",1.5,0,MAX+1),ids=("null","text","real","zero","above-max"))
def test_fresh_entity_triggers_reject_hostile_insert_and_update_without_mutation(tmp_path,table,operation,value):
    db=_fresh(tmp_path/f"{table}-{operation}-{str(value)}.db");message,pk,existing,insert_sql,args=ENTITY_SQL[table]
    try:
        before=db.execute(f"SELECT revision FROM {table} WHERE {pk}=?",(existing,)).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError,match=f"{message} revision outside safe integer range"):
            if operation=="insert":db.execute(insert_sql,args+(value,))
            else:db.execute(f"UPDATE {table} SET revision=? WHERE {pk}=?",(value,existing))
        db.rollback()
        assert db.execute(f"SELECT revision FROM {table} WHERE {pk}=?",(existing,)).fetchone()[0]==before
        assert db.execute(f"SELECT 1 FROM {table} WHERE {pk}='bad'").fetchone() is None
    finally:db.close()

@pytest.mark.parametrize("table",ENTITY_SQL)
def test_fresh_entity_orm_check_and_exact_max_trigger_acceptance(tmp_path,table):
    db=_fresh(tmp_path/f"{table}-max.db");_message,pk,existing,insert_sql,args=ENTITY_SQL[table]
    try:
        sql=db.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name=?",(table,)).fetchone()[0]
        check_name={"nodes":"ck_node_revision_safe","edges":"ck_edge_revision_safe","content_blocks":"ck_content_block_revision_safe","branches":"ck_branch_revision_safe"}[table]
        assert check_name in sql and "revision >= 1 AND revision <= 9007199254740991" in sql
        db.execute(insert_sql,args+(MAX,));db.execute(f"UPDATE {table} SET revision=? WHERE {pk}=?",(MAX,existing));db.commit()
        assert db.execute(f"SELECT revision FROM {table} WHERE {pk}=?",(existing,)).fetchone()[0]==MAX
        assert db.execute(f"SELECT revision FROM {table} WHERE {pk}='bad'").fetchone()[0]==MAX
    finally:db.close()


def test_real_v14_to_v15_preserves_all_entity_data_and_creates_exact_eight_triggers(tmp_path):
    path=generate(tmp_path/"v14.db","v14");db=sqlite3.connect(path)
    db.execute("INSERT INTO branches(id,project_id,name,description,status,created_at,revision) VALUES('branch',?,'b','','active',?,8)",(PROJECT,NOW.isoformat()));db.commit()
    before=tuple((t,tuple(db.execute(f"SELECT * FROM {t} ORDER BY rowid"))) for t in ENTITY_SQL);db.close()
    asyncio.run(_migrate(path));db=sqlite3.connect(path)
    try:
        assert db.execute("PRAGMA user_version").fetchone()[0]==15
        after=tuple((t,tuple(db.execute(f"SELECT * FROM {t} ORDER BY rowid"))) for t in ENTITY_SQL);assert after==before
        for table in ENTITY_SQL:
            for operation in ("insert","update"):
                name=f"trg_{table}_revision_safe_{operation}";row=db.execute("SELECT type,tbl_name,sql FROM sqlite_schema WHERE name=?",(name,)).fetchone()
                assert row[:2]==("trigger",table) and normalize_sql(row[2])==normalize_sql(TRIGGERS[name])
    finally:db.close()

async def _migrate(path):
    engine=create_async_engine(f"sqlite+aiosqlite:///{path}")
    try:
        async with engine.begin() as conn:await migrate_sqlite(conn)
    finally:await engine.dispose()

@pytest.mark.parametrize("table",ENTITY_SQL)
@pytest.mark.parametrize("value",("NULL","'bad'","1.5","0",str(MAX+1)),ids=("null","text","real","zero","above-max"))
def test_malformed_v14_entity_revision_fails_preflight_with_exact_snapshot_unchanged(tmp_path,table,value):
    path=generate(tmp_path/f"bad-{table}-{value}.db","v14");db=sqlite3.connect(path)
    pk,entity_id="id",{"nodes":"fixture-node-root","edges":"fixture-edge","content_blocks":"fixture-block","branches":"branch"}[table]
    if table=="branches":
        db.execute("INSERT INTO branches(id,project_id,name,description,status,created_at,revision) VALUES('branch',?,'b','','active',?,1)",(PROJECT,NOW.isoformat()));entity_id="branch"
    if value=="NULL":
        sql=db.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name=?",(table,)).fetchone()[0]
        sql=sql.replace("revision INTEGER NOT NULL DEFAULT 1","revision INTEGER DEFAULT 1")
        db.execute("PRAGMA writable_schema=ON");db.execute("UPDATE sqlite_schema SET sql=? WHERE type='table' AND name=?",(sql,table));db.execute("PRAGMA writable_schema=OFF")
        version=db.execute("PRAGMA schema_version").fetchone()[0];db.execute(f"PRAGMA schema_version={version+1}");db.commit();db.close();db=sqlite3.connect(path)
    cursor=db.execute(f"UPDATE {table} SET revision={value} WHERE {pk}=?",(entity_id,));assert cursor.rowcount==1;db.commit();db.close()
    before=logical_snapshot(path)
    with pytest.raises(RuntimeError,match="revision outside exact JSON integer range"):asyncio.run(_migrate(path))
    assert logical_snapshot(path)==before
    db=sqlite3.connect(path)
    try:
        assert db.execute("PRAGMA user_version").fetchone()[0]==14
        assert db.execute("SELECT 1 FROM sqlite_schema WHERE name=?",(f"trg_{table}_revision_safe_insert",)).fetchone() is None
    finally:db.close()


def test_touched_entities_preflights_all_unique_entities_before_mutation():
    first=Node(id=UID,revision=MAX-1);second=Edge(id=UID2,revision=MAX)
    touched=TouchedEntities();touched.add(first,second,first)
    with pytest.raises(HTTPException) as exc:touched.apply()
    assert exc.value.status_code==409 and exc.value.detail["code"]=="REVISION_EXHAUSTED"
    assert first.revision==MAX-1 and second.revision==MAX
    entities=[Node(id=UID,revision=MAX-1),Edge(id=UID2,revision=MAX-1),ContentBlock(id="b",revision=MAX-1),Branch(id="r",revision=MAX-1)]
    touched=TouchedEntities();touched.add(*entities);touched.apply();assert [e.revision for e in entities]==[MAX]*4


def test_exact_max_is_readable_and_serializable_but_entity_mutation_check_denies_it():
    node=Node(id=UID,project_id=UID2,title="n",node_type="idea",status="active",maturity="seed",workflow_status="draft",created_at=NOW,updated_at=NOW,revision=MAX)
    assert NodeOut.model_validate(node).model_dump(mode="json")["revision"]==MAX
    with pytest.raises(HTTPException) as exc:check_entity_revision(node,MAX,kind="node")
    assert exc.value.detail["code"]=="REVISION_EXHAUSTED" and node.revision==MAX
