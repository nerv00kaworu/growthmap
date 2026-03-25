"""Pydantic schemas for API request/response"""
import uuid
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field

from models.enums import Maturity, NodeStatus, NodeType, RelationType


# === Project ===

class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    goal: str = ""
    settings: dict = {}


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    goal: Optional[str] = None
    status: Optional[str] = None
    settings: Optional[dict] = None


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    goal: str
    root_node_id: Optional[str]
    status: str
    settings: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# === Node ===

class NodeCreate(BaseModel):
    title: str
    summary: str = ""
    node_type: NodeType = NodeType.IDEA
    parent_id: Optional[str] = None  # 自動建 child_of edge
    description: str = ""
    tags: list[str] = []


class NodeUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    node_type: Optional[NodeType] = None
    status: Optional[NodeStatus] = None
    maturity: Optional[Maturity] = None
    priority: Optional[int] = None
    confidence: Optional[float] = None
    description: Optional[str] = None
    rules_text: Optional[str] = None
    constraints_text: Optional[str] = None
    examples_text: Optional[str] = None
    questions_text: Optional[str] = None
    decision_notes: Optional[str] = None
    tags: Optional[list[str]] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None


class NodeOut(BaseModel):
    id: str
    project_id: str
    title: str
    summary: str
    node_type: NodeType
    status: NodeStatus
    maturity: Maturity
    priority: int
    confidence: float
    description: str
    rules_text: str
    constraints_text: str
    examples_text: str
    questions_text: str
    decision_notes: str
    tags: list[str]
    created_by: str
    last_edited_by: str
    position_x: float
    position_y: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NodeBrief(BaseModel):
    """輕量版，用於樹狀列表"""
    id: str
    title: str
    node_type: NodeType
    status: NodeStatus
    maturity: Maturity
    summary: str

    model_config = {"from_attributes": True}


# === Edge ===

class EdgeCreate(BaseModel):
    from_node_id: str
    to_node_id: str
    relation_type: RelationType = RelationType.CHILD_OF
    weight: float = 1.0
    note: str = ""
    is_mainline: bool = False


class EdgeOut(BaseModel):
    id: str
    project_id: str
    from_node_id: str
    to_node_id: str
    relation_type: RelationType
    weight: float
    note: str
    is_mainline: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# === Content Block ===

class ContentBlockCreate(BaseModel):
    block_type: str = "paragraph"
    content: Any = {}
    order_index: int = 0


class ContentBlockUpdate(BaseModel):
    block_type: Optional[str] = None
    content: Optional[Any] = None
    order_index: Optional[int] = None


class ContentBlockOut(BaseModel):
    id: str
    node_id: str
    block_type: str
    content: Any
    order_index: int
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# === Suggestion ===

class SuggestionOut(BaseModel):
    id: str
    project_id: str
    target_node_id: str
    action_type: str
    status: str
    payload: Any
    provider_id: str
    provider_model: str
    cost_estimate: float
    created_at: datetime
    reviewed_at: Optional[datetime]
    reviewed_by: Optional[str]

    model_config = {"from_attributes": True}


class NodeMoveRequest(BaseModel):
    new_parent_id: str


class MainlinePathOut(BaseModel):
    nodes: list[NodeBrief]


class BranchInfo(BaseModel):
    node: NodeBrief
    parent_id: str
    incoming_edge_id: str
    child_count: int


# === Provider Config ===

class ProviderConfigCreate(BaseModel):
    name: str
    provider_type: str
    endpoint: str = ""
    auth_type: str = "none"
    model_name: str = ""
    capabilities: list[str] = Field(default_factory=list)
    cost_level: str = "low"
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class ProviderConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[str] = None
    endpoint: Optional[str] = None
    auth_type: Optional[str] = None
    model_name: Optional[str] = None
    capabilities: Optional[list[str]] = None
    cost_level: Optional[str] = None
    enabled: Optional[bool] = None
    settings: Optional[dict[str, Any]] = None


class ProviderConfigOut(BaseModel):
    id: str
    name: str
    provider_type: str
    endpoint: str
    auth_type: str
    model_name: str
    capabilities: list[str]
    cost_level: str
    enabled: bool
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# === AI Actions ===

class ExpandRequest(BaseModel):
    desired_count: int = 5
    mode: str = "divergent"  # divergent / convergent
    constraints: list[str] = []
    user_instructions: str = ""
    provider_id: Optional[str] = None


class DeepenRequest(BaseModel):
    fields: list[str] = ["description", "rules", "examples"]
    maturity_target: Optional[str] = None
    user_instructions: str = ""
    provider_id: Optional[str] = None


class DetectGapsRequest(BaseModel):
    scope: str = "immediate"  # immediate / branch / project
    user_instructions: str = ""
    provider_id: Optional[str] = None


# === Agent Session ===

class AssignAgentRequest(BaseModel):
    objective: str
    provider_id: Optional[str] = None
    mode: str = "one_shot"  # one_shot / collab / background
    scope: str = "node"  # node / branch
