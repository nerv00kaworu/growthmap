import re
"""Pydantic schemas for API request/response"""
import uuid
from datetime import datetime
from typing import Annotated, Literal, Optional, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    description: str
    goal: str
    root_node_id: Optional[str]
    status: str
    settings: dict
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

    @field_validator("title")
    @classmethod
    def normalize_nonblank_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title cannot be blank")
        return value

    @model_validator(mode="after")
    def parent_cas_is_mandatory(self):
        if self.parent_id is not None and self.expected_parent_revision is None:
            raise ValueError("expected_parent_revision is required when parent_id is provided")
        if self.parent_id is None and self.expected_parent_revision is not None:
            raise ValueError("expected_parent_revision requires parent_id")
        return self


class NodeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def reject_null_and_empty(cls, value):
        if isinstance(value, dict):
            changes = {key: item for key, item in value.items()
                       if key not in {"expected_project_revision", "expected_revision"}}
            if not changes: raise ValueError("update_node fields cannot be empty")
            nulls = sorted(key for key, item in changes.items() if item is None)
            if nulls: raise ValueError(f"explicit null is not allowed: {', '.join(nulls)}")
        return value

    expected_project_revision: Annotated[int, Field(ge=1)]
    expected_revision: Annotated[int, Field(ge=1)]
    title: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    summary: Annotated[str, Field(max_length=500)] | None = None
    node_type: Literal["idea","concept","task","question","decision","risk","resource","note","module","spec"] | None = None
    status: Literal["active","paused","archived","completed"] | None = None
    maturity: Literal["seed","rough","developing","stable","finalized"] | None = None
    priority: Annotated[int, Field(ge=-100, le=100)] | None = None
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    description: Annotated[str, Field(max_length=16_384)] | None = None
    rules_text: Annotated[str, Field(max_length=16_384)] | None = None
    constraints_text: Annotated[str, Field(max_length=16_384)] | None = None
    examples_text: Annotated[str, Field(max_length=16_384)] | None = None
    questions_text: Annotated[str, Field(max_length=16_384)] | None = None
    decision_notes: Annotated[str, Field(max_length=16_384)] | None = None
    tags: Annotated[list[Annotated[str, Field(max_length=100)]], Field(max_length=50)] | None = None
    workflow_status: Literal["draft","review","approved","archived"] | None = None
    file_paths: Annotated[list[Annotated[str, Field(max_length=1024)]], Field(max_length=100)] | None = None
    position_x: float | None = None
    position_y: float | None = None


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
    decision_notes: str = ""
    tags: list[str] = []
    workflow_status: str = "draft"
    file_paths: list[str] = []
    created_by: str
    last_edited_by: str
    position_x: float
    position_y: float
    branch_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    revision: int = 1
    authoritative_project_revision: Optional[int] = None
    authoritative_parent_id: Optional[str] = None
    authoritative_parent_revision: Optional[int] = None

    @field_validator(
        "summary", "description", "rules_text", "constraints_text", "examples_text",
        "questions_text", "decision_notes", "created_by", "last_edited_by",
        mode="before",
    )
    @classmethod
    def default_legacy_null_text(cls, value):
        return "" if value is None else value

    @field_validator("tags", "file_paths", mode="before")
    @classmethod
    def default_legacy_null_lists(cls, value):
        return [] if value is None else value

    @field_validator("priority", mode="before")
    @classmethod
    def default_legacy_null_priority(cls, value):
        return 0 if value is None else value

    @field_validator("confidence", mode="before")
    @classmethod
    def default_legacy_null_confidence(cls, value):
        return 0.5 if value is None else value

    @field_validator("position_x", "position_y", mode="before")
    @classmethod
    def default_legacy_null_position(cls, value):
        return 0.0 if value is None else value

    model_config = {"from_attributes": True}


class NodeBrief(BaseModel):
    """輕量版，用於樹狀列表"""
    id: str
    revision: int = 1
    title: str
    node_type: str
    status: str
    maturity: str
    summary: str

    model_config = {"from_attributes": True}


# === Edge ===

class EdgeCreate(BaseModel):
    expected_project_revision: int
    expected_from_revision: int
    expected_to_revision: int
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
    weight: float = 1.0
    note: str = ""
    is_mainline: bool
    created_at: datetime
    revision: int = 1
    authoritative_project_revision: Optional[int] = None
    authoritative_from_revision: Optional[int] = None
    authoritative_to_revision: Optional[int] = None
    touched_edge_revisions: dict[str, int] = Field(default_factory=dict)

    @field_validator("weight", mode="before")
    @classmethod
    def default_legacy_null_weight(cls, value):
        """舊資料可能保存 NULL；API 一律以預設權重輸出。"""
        return 1.0 if value is None else value

    @field_validator("note", mode="before")
    @classmethod
    def default_legacy_null_note(cls, value):
        """舊資料可能保存 NULL；API 一律輸出空字串。"""
        return "" if value is None else value

    model_config = {"from_attributes": True}


# === Content Block ===

class ContentBlockCreate(BaseModel):
    expected_project_revision: int
    expected_node_revision: int
    block_type: str = Field(default="paragraph", min_length=1, max_length=30)
    content: dict[str, Any] = Field(default_factory=dict, max_length=100)
    order_index: int = Field(default=0, ge=0, le=100000)

    @field_validator("content")
    @classmethod
    def validate_content_bounds(cls, value):
        if any(not isinstance(key, str) or len(key) > 100 for key in value):
            raise ValueError("content keys must be strings of at most 100 characters")
        return value


class ContentBlockUpdate(BaseModel):
    expected_project_revision: int
    expected_node_revision: int
    expected_revision: int
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
    revision: int = 1
    authoritative_project_revision: Optional[int] = None
    authoritative_node_revision: Optional[int] = None
    authoritative_block_revision: Optional[int] = None

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

APP_SECRET_ENV_PREFIX = "GROWTHMAP_LLM_KEY_"
APP_SECRET_ENV_PATTERN = re.compile(r"^GROWTHMAP_LLM_KEY_[A-Z0-9_]{1,96}$")


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
