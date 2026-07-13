"""Pydantic schemas for API request/response"""
import uuid
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field


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
    node_type: str = "idea"
    parent_id: Optional[str] = None  # 自動建 child_of edge
    branch_id: Optional[str] = None  # 由目前方案線建立的節點
    description: str = ""
    tags: list[str] = []


class NodeUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    node_type: Optional[str] = None
    status: Optional[str] = None
    maturity: Optional[str] = None
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
    node_type: str
    status: str
    maturity: str
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
    branch_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NodeBrief(BaseModel):
    """輕量版，用於樹狀列表"""
    id: str
    title: str
    node_type: str
    status: str
    maturity: str
    summary: str

    model_config = {"from_attributes": True}


# === Edge ===

class EdgeCreate(BaseModel):
    from_node_id: str
    to_node_id: str
    relation_type: str = "child_of"
    weight: float = 1.0
    note: str = ""
    is_mainline: bool = False


class EdgeUpdate(BaseModel):
    weight: Optional[float] = None
    note: Optional[str] = None


class EdgeOut(BaseModel):
    id: str
    project_id: str
    from_node_id: str
    to_node_id: str
    relation_type: str
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


# === Governance ===

class NodeMoveRequest(BaseModel):
    new_parent_id: str


class AncestorNode(BaseModel):
    id: str
    title: str
    node_type: str
    maturity: str
    is_mainline: bool

    model_config = {"from_attributes": True}


class MainlinePathOut(BaseModel):
    path: list[AncestorNode]


class BranchInfo(BaseModel):
    node_id: str
    title: str
    mainline_child_id: Optional[str]
    branch_child_ids: list[str]
    total_children: int


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


# === Branch ===

class ProviderConfigCreate(BaseModel):
    name: str
    provider_type: str = "openai_compatible"
    endpoint: str = ""
    secret_env_key: str = "LLM_API_KEY"
    model_name: str = ""
    capabilities: list[str] = []
    cost_level: str = "low"
    enabled: bool = True


class ProviderConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[str] = None
    endpoint: Optional[str] = None
    secret_env_key: Optional[str] = None
    model_name: Optional[str] = None
    capabilities: Optional[list[str]] = None
    cost_level: Optional[str] = None
    enabled: Optional[bool] = None


class ProviderConfigOut(BaseModel):
    id: str
    name: str
    provider_type: str
    endpoint: str
    auth_type: str
    secret_env_key: str
    model_name: str
    capabilities: list[str]
    cost_level: str
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BranchCreate(BaseModel):
    source_node_id: str
    name: str
    description: str = ""


class BranchOut(BaseModel):
    id: str
    project_id: str
    name: str
    description: str
    source_node_id: Optional[str]
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# === Agent Session ===

class AgentArtifactCreate(BaseModel):
    target_node_id: str
    artifact_type: str  # create_child / update_node / create_block
    payload: dict


class AgentArtifactReview(BaseModel):
    review_note: str = ""


class AgentArtifactOut(BaseModel):
    id: str
    session_id: str
    project_id: str
    target_node_id: str
    artifact_type: str
    payload: dict
    status: str
    review_note: str
    created_at: datetime
    reviewed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class AgentSessionCreate(BaseModel):
    project_id: str
    assigned_node_id: Optional[str] = None
    assigned_branch_root_id: Optional[str] = None
    provider_id: Optional[str] = None
    objective: str
    mode: str = "one_shot"  # one_shot / collab / background
    handoff_context: dict = {}


class AgentSessionUpdate(BaseModel):
    status: Optional[str] = None  # idle / active / waiting_review / completed / cancelled
    result_summary: Optional[str] = None
    handoff_context: Optional[dict] = None


class AgentSessionOut(BaseModel):
    id: str
    project_id: str
    assigned_node_id: Optional[str]
    assigned_branch_root_id: Optional[str]
    provider_id: Optional[str]
    objective: str
    mode: str
    status: str
    handoff_context: dict
    result_summary: str
    last_heartbeat_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
