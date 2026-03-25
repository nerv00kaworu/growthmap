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
    # 追蹤
    created_by = Column(Text, default="human")
    last_edited_by = Column(Text, default="human")
    position_x = Column(Float, default=0)
    position_y = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

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
    is_mainline = Column(Boolean, nullable=False, default=False)
    weight = Column(Float, default=1.0)
    note = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)

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
    auth_type = Column(String(20), default="none")
    model_name = Column(Text, default="")
    capabilities = Column(JSON, default=[])
    cost_level = Column(String(10), default="low")
    enabled = Column(Boolean, default=True)
    settings = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
