"""GrowthMap SQLAlchemy Models"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean, DateTime,
    ForeignKey, CheckConstraint, Index, JSON
)
# Use String for IDs (UUID as text) for SQLite compatibility
# Use JSON instead of JSON/ARRAY for SQLite
from sqlalchemy.orm import relationship
from db.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(Text, nullable=False)
    description = Column(Text, default="")
    goal = Column(Text, default="")
    root_node_id = Column(String(36), nullable=True)
    status = Column(String(20), nullable=False, default="active")
    settings = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    revision = Column(Integer, nullable=False, default=1, server_default="1")

    nodes = relationship("Node", back_populates="project", cascade="all, delete-orphan")
    edges = relationship("Edge", back_populates="project", cascade="all, delete-orphan")


class Node(Base):
    __tablename__ = "nodes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=False)
    summary = Column(Text, default="")
    node_type = Column(String(20), nullable=False, default="idea")
    status = Column(String(20), nullable=False, default="active")
    maturity = Column(String(20), nullable=False, default="seed")
    priority = Column(Integer, default=0)
    confidence = Column(Float, default=0.5)
    # 內化欄位
    description = Column(Text, default="")
    rules_text = Column(Text, default="")
    constraints_text = Column(Text, default="")
    examples_text = Column(Text, default="")
    questions_text = Column(Text, default="")
    decision_notes = Column(Text, default="")
    tags = Column(JSON, default=[])
    workflow_status = Column(String(20), nullable=False, default="draft", server_default="draft")
    file_paths = Column(JSON, default=[], server_default="[]")
    # 分支
    branch_id = Column(String(36), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    # 追蹤
    created_by = Column(Text, default="human")
    last_edited_by = Column(Text, default="human")
    position_x = Column(Float, default=0)
    position_y = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    revision = Column(Integer, nullable=False, default=1, server_default="1")

    project = relationship("Project", back_populates="nodes")
    content_blocks = relationship("ContentBlock", back_populates="node", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_nodes_project", "project_id"),
        Index("idx_nodes_type", "node_type"),
        Index("idx_nodes_status", "status"),
    )


class Edge(Base):
    __tablename__ = "edges"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    from_node_id = Column(String(36), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    to_node_id = Column(String(36), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    relation_type = Column(String(30), nullable=False, default="child_of")
    # Python 與 DB 雙層預設：API、匯入與直接 SQL 新增都得到可序列化值。
    # 暫不把 nullable 改為 False，讓舊資料庫可平滑載入；讀取端另有歷史 NULL 容錯。
    weight = Column(Float, default=1.0, server_default="1.0")
    note = Column(Text, default="", server_default="")
    is_mainline = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    revision = Column(Integer, nullable=False, default=1, server_default="1")

    project = relationship("Project", back_populates="edges")

    __table_args__ = (
        Index("idx_edges_project", "project_id"),
        Index("idx_edges_from", "from_node_id"),
        Index("idx_edges_to", "to_node_id"),
    )


class ContentBlock(Base):
    __tablename__ = "content_blocks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    node_id = Column(String(36), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    block_type = Column(String(30), nullable=False, default="paragraph")
    content = Column(JSON, nullable=False, default={})
    order_index = Column(Integer, nullable=False, default=0)
    created_by = Column(Text, default="human")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    revision = Column(Integer, nullable=False, default=1, server_default="1")

    node = relationship("Node", back_populates="content_blocks")

    __table_args__ = (
        Index("idx_content_blocks_node", "node_id"),
    )


class Suggestion(Base):
    __tablename__ = "suggestions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    target_node_id = Column(String(36), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    action_type = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    payload = Column(JSON, nullable=False, default={})
    provider_id = Column(Text, default="")
    provider_model = Column(Text, default="")
    cost_estimate = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_suggestions_node", "target_node_id"),
        Index("idx_suggestions_status", "status"),
    )


class ActionLog(Base):
    __tablename__ = "action_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(String(36), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True)
    actor_type = Column(String(20), nullable=False)
    actor_id = Column(Text, default="")
    action_type = Column(Text, nullable=False)
    payload = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("idx_action_logs_project", "project_id"),
        Index("idx_action_logs_node", "node_id"),
    )


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(Text, nullable=False)
    provider_type = Column(String(30), nullable=False)
    endpoint = Column(Text, default="")
    auth_type = Column(String(20), default="env")
    secret_env_key = Column(String(128), default="", server_default="")
    model_name = Column(Text, default="")
    capabilities = Column(JSON, default=[])
    cost_level = Column(String(10), default="low")
    enabled = Column(Boolean, default=True)
    settings = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Branch(Base):
    __tablename__ = "branches"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    source_node_id = Column(String(36), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), default="active")  # active, merged, archived
    created_at = Column(DateTime(timezone=True), default=utcnow)
    revision = Column(Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (
        Index("idx_branches_project", "project_id"),
    )


class AgentArtifact(Base):
    __tablename__ = "agent_artifacts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    target_node_id = Column(String(36), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    artifact_type = Column(String(30), nullable=False)  # create_child / update_node / create_block
    payload = Column(JSON, nullable=False, default={})
    status = Column(String(20), nullable=False, default="pending")  # pending / applied / rejected
    review_note = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_agent_artifacts_session", "session_id"),
        Index("idx_agent_artifacts_status", "status"),
    )


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    assigned_node_id = Column(String(36), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True)
    assigned_branch_root_id = Column(String(36), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True)
    provider_id = Column(String(36), ForeignKey("provider_configs.id"), nullable=True)
    objective = Column(Text, default="")
    mode = Column(String(20), nullable=False, default="one_shot")
    status = Column(String(20), nullable=False, default="idle")
    handoff_context = Column(JSON, default={})
    result_summary = Column(Text, default="")
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class AgentGrant(Base):
    __tablename__ = "agent_grants"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_prefix = Column(String(20), nullable=False, unique=True, index=True)
    token_salt = Column(String(64), nullable=False)
    token_hash = Column(String(128), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    permission = Column(String(10), nullable=False)
    node_scope_id = Column(String(36), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=True)
    branch_root_id = Column(String(36), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=True)
    label = Column(String(120), nullable=False)
    agent_identity = Column(String(120), nullable=False)
    status = Column(String(12), nullable=False, default="active")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

class AgentReceipt(Base):
    __tablename__ = "agent_receipts"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    grant_id = Column(String(36), ForeignKey("agent_grants.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key = Column(String(80), nullable=False)
    request_digest = Column(String(64), nullable=False)
    action_type = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False)
    response = Column(JSON, nullable=False, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("ux_agent_receipt_idempotency", "grant_id", "idempotency_key", unique=True),)

class AgentProposal(Base):
    __tablename__ = "agent_proposals"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    grant_id = Column(String(36), ForeignKey("agent_grants.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    target_node_id = Column(String(36), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(200), nullable=False)
    rationale = Column(Text, default="")
    operations = Column(JSON, nullable=False)
    expected_project_revision = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    review_note = Column(Text, default="")
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

class AgentEvent(Base):
    __tablename__ = "agent_events"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    grant_id = Column(String(36), ForeignKey("agent_grants.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    target_node_id = Column(String(36), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(30), nullable=False)
    message = Column(Text, nullable=False)
    payload = Column(JSON, nullable=False, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)

class AgentReadback(Base):
    __tablename__ = "agent_readbacks"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    grant_id = Column(String(36), ForeignKey("agent_grants.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    target_node_id = Column(String(36), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True)
    commit_refs = Column(JSON, nullable=False, default=[])
    files = Column(JSON, nullable=False, default=[])
    tests = Column(JSON, nullable=False, default=[])
    decisions = Column(JSON, nullable=False, default=[])
    risks = Column(JSON, nullable=False, default=[])
    todos = Column(JSON, nullable=False, default=[])
    evidence = Column(JSON, nullable=False, default=[])
    summary = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)
