import re
"""Pydantic schemas for API request/response"""
import uuid
from datetime import datetime
from typing import Optional, Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from models.content_blocks import ContentBlockType


# === Project ===

class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    goal: str = ""
    settings: dict = {}


class ProjectUpdate(BaseModel):
    expected_project_revision: int
    name: Optional[str] = None
    description: Optional[str] = None
    goal: Optional[str] = None
    status: Optional[str] = None
    settings: Optional[dict] = None


class ProjectOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    goal: Optional[str] = None
    root_node_id: Optional[str]
    status: str
    settings: Optional[dict] = None
    created_at: datetime
    updated_at: datetime
    revision: int = 1

    model_config = {"from_attributes": True}


# === Node ===

class NodeCreate(BaseModel):
    expected_project_revision: int
    expected_parent_revision: Optional[int] = None
    title: str
    summary: str = ""
    node_type: str = "idea"
    parent_id: Optional[str] = None  # 自動建 child_of edge
    branch_id: Optional[str] = None  # 由目前方案線建立的節點
    description: str = ""
    tags: list[str] = []

    @model_validator(mode="after")
    def parent_cas_is_mandatory(self):
        if self.parent_id is not None and self.expected_parent_revision is None:
            raise ValueError("expected_parent_revision is required when parent_id is provided")
        if self.parent_id is None and self.expected_parent_revision is not None:
            raise ValueError("expected_parent_revision requires parent_id")
        return self


class NodeUpdate(BaseModel):
    expected_project_revision: int
    expected_revision: int
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
    workflow_status: Optional[str] = None
    file_paths: Optional[list[str]] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None


class NodeOut(BaseModel):
    id: str
    project_id: str
    title: str
    summary: Optional[str] = None
    node_type: str
    status: str
    maturity: str
    priority: Optional[int] = None
    confidence: Optional[float] = None
    description: Optional[str] = None
    rules_text: Optional[str] = None
    constraints_text: Optional[str] = None
    examples_text: Optional[str] = None
    questions_text: Optional[str] = None
    decision_notes: Optional[str] = None
    tags: Optional[list[str]] = None
    workflow_status: str = "draft"
    file_paths: Optional[list[str]] = None
    created_by: Optional[str] = None
    last_edited_by: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    branch_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    revision: int = 1
    authoritative_project_revision: Optional[int] = None
    authoritative_parent_id: Optional[str] = None
    authoritative_parent_revision: Optional[int] = None

    model_config = {"from_attributes": True}


class NodeBrief(BaseModel):
    """輕量版，用於樹狀列表"""
    id: str
    revision: int = 1
    title: str
    node_type: str
    status: str
    maturity: str
    summary: Optional[str] = None

    model_config = {"from_attributes": True}


# === Edge ===

class EdgeCreate(BaseModel):
    expected_project_revision: int
    from_node_id: str
    to_node_id: str
    relation_type: str = "child_of"
    weight: float = 1.0
    note: str = ""
    is_mainline: bool = False


class EdgeUpdate(BaseModel):
    expected_project_revision: int
    expected_revision: int
    weight: Optional[float] = None
    note: Optional[str] = None


class EdgeOut(BaseModel):
    id: str
    project_id: str
    from_node_id: str
    to_node_id: str
    relation_type: str
    weight: Optional[float] = None
    note: Optional[str] = None
    is_mainline: bool
    created_at: datetime
    revision: int = 1

    model_config = {"from_attributes": True}


# === Content Block ===

class ContentBlockCreate(BaseModel):
    expected_project_revision: int
    expected_node_revision: int
    block_type: ContentBlockType = ContentBlockType.paragraph
    content: Any = {}
    order_index: Optional[int] = None


class ContentBlockUpdate(BaseModel):
    expected_project_revision: int
    expected_node_revision: int
    expected_revision: int
    block_type: Optional[ContentBlockType] = None
    content: Optional[Any] = None
    order_index: Optional[int] = None


class ContentBlockOut(BaseModel):
    id: str
    node_id: str
    block_type: str
    content: Any
    order_index: int
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    revision: int = 1

    model_config = {"from_attributes": True}


# === Governance ===

class NodeMoveRequest(BaseModel):
    new_parent_id: str
    expected_project_revision: int
    expected_revision: int
    expected_new_parent_revision: int
    expected_old_parent_revision: Optional[int] = None


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

from models.provider_authority import MAX_PROVIDER_REVISION

APP_SECRET_ENV_PREFIX = "GROWTHMAP_LLM_KEY_"
APP_SECRET_ENV_PATTERN = re.compile(r"^GROWTHMAP_LLM_KEY_[A-Z0-9_]{1,96}$")
MAX_PROVIDER_CREDENTIAL_CHARS = 16384
MAX_PROVIDER_CREDENTIAL_BYTES = 32768


def validate_provider_credential(value: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value or len(value) > MAX_PROVIDER_CREDENTIAL_CHARS or len(value.encode("utf-8")) > MAX_PROVIDER_CREDENTIAL_BYTES:
        raise ValueError("INVALID_PROVIDER_CREDENTIAL")
    return value


def validate_app_secret_env_key(value: str) -> str:
    if not APP_SECRET_ENV_PATTERN.fullmatch(value):
        raise ValueError(
            "secret_env_key is outside the GrowthMap namespace; rebind the profile to "
            f"{APP_SECRET_ENV_PREFIX}[A-Z0-9_]{{1,96}}"
        )
    return value


class ProviderConfigCreate(BaseModel):
    name: str
    provider_type: str = "openai_compatible"
    endpoint: str = ""
    secret_env_key: str = "GROWTHMAP_LLM_KEY_DEFAULT"
    model_name: str = ""
    capabilities: list[str] = []
    cost_level: str = "low"
    enabled: bool = True

    @field_validator("secret_env_key")
    @classmethod
    def secret_key_is_app_owned(cls, value: str) -> str:
        return validate_app_secret_env_key(value)


class ProviderConfigUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    name: Optional[str] = None
    provider_type: Optional[str] = None
    endpoint: Optional[str] = None
    secret_env_key: Optional[str] = None
    model_name: Optional[str] = None
    capabilities: Optional[list[str]] = None
    cost_level: Optional[str] = None
    enabled: Optional[bool] = None

    @field_validator("secret_env_key")
    @classmethod
    def secret_key_is_app_owned(cls, value: Optional[str]) -> Optional[str]:
        return validate_app_secret_env_key(value) if value is not None else None


class ProviderModelUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    model_name: str

    @field_validator("model_name")
    @classmethod
    def valid_model_name(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 128:
            raise ValueError("model_name must contain 1 to 128 characters")
        return value


class ProviderSecretRecovery(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    revision: int = Field(ge=1, le=MAX_PROVIDER_REVISION)
    operation: Literal["set", "delete"]
    operation_id: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{48}$")
    api_key: Optional[str] = None

    @model_validator(mode="after")
    def desired_state_is_explicit(self):
        if self.operation == "set":
            validate_provider_credential(self.api_key)
        if self.operation == "delete" and self.api_key is not None:
            raise ValueError("api_key must be omitted for delete recovery")
        return self


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
    revision: int = Field(ge=1, le=MAX_PROVIDER_REVISION)
    secret_change_pending: bool
    secret_change_operation_id: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{48}$")
    credential_status: Literal["ready", "unavailable", "recovery_required"]
    is_default: bool
    selection_revision: int = Field(ge=1, le=MAX_PROVIDER_REVISION)

    @model_validator(mode="before")
    @classmethod
    def derive_credential_status(cls, value):
        if not isinstance(value, dict):
            value={name:getattr(value,name) for name in cls.model_fields if name not in {"credential_status","is_default","selection_revision"}}
        if "credential_status" not in value:
            value=value | {"credential_status": "recovery_required" if value.get("secret_change_pending") else "unavailable"}
        return value


    model_config = {"from_attributes": True}


class BranchCreate(BaseModel):
    expected_project_revision: int
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
    revision: int = 1

    model_config = {"from_attributes": True}


class ProjectRevisionRequest(BaseModel):
    expected_project_revision: int


class EntityRevisionRequest(ProjectRevisionRequest):
    expected_revision: int


class NodeEntityRevisionRequest(EntityRevisionRequest):
    expected_node_revision: int


class BranchMergeRequest(EntityRevisionRequest):
    target_node_id: str
    expected_target_revision: int


# === Agent Session ===

class AgentArtifactCreate(BaseModel):
    target_node_id: str
    artifact_type: str  # create_child / update_node / create_block
    payload: dict


class AgentArtifactReview(BaseModel):
    review_note: str = ""
    expected_project_revision: Optional[int] = None
    expected_node_revision: Optional[int] = None


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
