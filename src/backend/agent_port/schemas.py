"""Strict, bounded Agent Port v1 wire schemas."""
from typing import Annotated, Any, Literal, Union
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator
from models.revisions import MAX_SAFE_REVISION

Id = Annotated[str, Field(min_length=36, max_length=36, pattern=r"^[0-9a-fA-F-]{36}$")]
Short = Annotated[str, Field(max_length=500)]
Text = Annotated[str, Field(max_length=16_384)]
Key = Annotated[str, Field(min_length=8,max_length=80,pattern=r"^[A-Za-z0-9._:-]+$")]

class Strict(BaseModel):
    model_config=ConfigDict(extra="forbid", strict=True)

class NodeFields(Strict):
    title: Annotated[str,Field(min_length=1,max_length=500)]|None=None
    summary: Short|None=None; description: Text|None=None; rules_text: Text|None=None
    constraints_text: Text|None=None; examples_text: Text|None=None; questions_text: Text|None=None
    decision_notes: Text|None=None
    tags: Annotated[list[Annotated[str,Field(max_length=100)]],Field(max_length=50)]|None=None
    status: Literal["active","archived","completed"]|None=None
    maturity: Literal["seed","sprout","growing","mature"]|None=None
    priority: Annotated[int,Field(ge=-100,le=100)]|None=None
    confidence: Annotated[float,Field(ge=0,le=1)]|None=None
    workflow_status: Literal["draft","review","approved","archived"]|None=None
    file_paths: Annotated[list[Annotated[str,Field(max_length=1024)]],Field(max_length=100)]|None=None

class CreateNode(Strict):
    op: Literal["create_node"]
    id: Id|None=None; parent_id: Id|None=None
    expected_parent_revision: Annotated[int,Field(ge=1,le=MAX_SAFE_REVISION)]|None=None
    branch_id: Id|None=None
    @model_validator(mode="after")
    def parent_cas(self):
        if bool(self.parent_id) != bool(self.expected_parent_revision):
            raise ValueError("parent_id and expected_parent_revision must be supplied together")
        return self
    title: Annotated[str,Field(min_length=1,max_length=500)]
    summary: Short=""; node_type: Literal["idea","concept","task","question","decision","risk","resource","note","module","spec"]="idea"
class UpdateNode(Strict):
    op: Literal["update_node"]; node_id: Id; expected_revision: Annotated[int,Field(ge=1,le=MAX_SAFE_REVISION)]; fields: NodeFields
class CreateEdge(Strict):
    op: Literal["create_edge"]; id: Id|None=None; from_node_id: Id; to_node_id: Id
    expected_from_revision: Annotated[int,Field(ge=1,le=MAX_SAFE_REVISION)]
    expected_to_revision: Annotated[int,Field(ge=1,le=MAX_SAFE_REVISION)]
    relation_type: Literal["child_of","extends","depends_on","supports","alternative_to","refines","references","conflicts_with"]="child_of"
    weight: Annotated[float,Field(ge=-1000,le=1000)]=1.0; note: Short=""
class CreateBlock(Strict):
    op: Literal["create_content_block"]; id: Id|None=None; node_id: Id
    expected_node_revision: Annotated[int,Field(ge=1,le=MAX_SAFE_REVISION)]
    block_type: Literal["paragraph","bullet_list","rule_set","example","risk_note","decision_log","todo","prompt_context","code","quote","table","text","markdown","note","question","task","decision","risk","resource","definition","rules","spec"]="paragraph"
    content: dict[Annotated[str,Field(max_length=100)],Annotated[str,Field(max_length=16384)]]=Field(default_factory=dict,max_length=100)
    order_index: Annotated[int,Field(ge=0,le=100000)]=0
class CreateBranch(Strict):
    op: Literal["create_branch"]; id: Id|None=None; source_node_id: Id
    expected_source_revision: Annotated[int,Field(ge=1,le=MAX_SAFE_REVISION)]
    name: Annotated[str,Field(min_length=1,max_length=255)]; description: Annotated[str,Field(max_length=4000)]=""

Operation=Annotated[Union[CreateNode,UpdateNode,CreateEdge,CreateBlock,CreateBranch],Field(discriminator="op")]
OperationList=Annotated[list[Operation],Field(min_length=1,max_length=50)]

class ProjectTarget(Strict):
    project_id: Id|None=None

class Batch(ProjectTarget):
    expected_project_revision: Annotated[int,Field(ge=1,le=MAX_SAFE_REVISION)]; idempotency_key: Key; operations: OperationList
class ProposalIn(Batch):
    target_node_id: Id|None=None; title: Annotated[str,Field(min_length=1,max_length=200)]; rationale: Annotated[str,Field(max_length=4000)]=""
class EventIn(ProjectTarget):
    idempotency_key: Key; target_node_id: Id|None=None
    event_type: Literal["started","progress","blocked","completed","failed"]
    message: Annotated[str,Field(min_length=1,max_length=4000)]
    payload: dict[Annotated[str,Field(max_length=100)],Annotated[str,Field(max_length=4000)]]=Field(default_factory=dict,max_length=100)
class Record(Strict):
    name: Annotated[str,Field(min_length=1,max_length=200)]; status: Annotated[str,Field(max_length=100)]=""; detail: Annotated[str,Field(max_length=4000)]=""
class ReadbackIn(ProjectTarget):
    idempotency_key: Key; target_node_id: Id|None=None; summary: Annotated[str,Field(max_length=8000)]=""
    commit_refs: Annotated[list[Annotated[str,Field(max_length=200)]],Field(max_length=100)]=[]
    files: Annotated[list[Annotated[str,Field(max_length=1024)]],Field(max_length=500)]=[]
    tests: Annotated[list[Record],Field(max_length=200)]=[]
    decisions: Annotated[list[Annotated[str,Field(max_length=2000)]],Field(max_length=200)]=[]
    risks: Annotated[list[Annotated[str,Field(max_length=2000)]],Field(max_length=200)]=[]
    todos: Annotated[list[Annotated[str,Field(max_length=2000)]],Field(max_length=200)]=[]
    evidence: Annotated[list[Record],Field(max_length=200)]=[]
class ReviewIn(Strict):
    review_note: Annotated[str,Field(max_length=2000)]=""
