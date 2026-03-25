"""Enum values for backend schema validation."""

from enum import StrEnum


class NodeType(StrEnum):
    IDEA = "idea"
    CONCEPT = "concept"
    TASK = "task"
    QUESTION = "question"
    DECISION = "decision"
    RISK = "risk"
    RESOURCE = "resource"
    NOTE = "note"
    MODULE = "module"


class Maturity(StrEnum):
    SEED = "seed"
    ROUGH = "rough"
    DEVELOPING = "developing"
    STABLE = "stable"
    FINALIZED = "finalized"


class NodeStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class RelationType(StrEnum):
    CHILD_OF = "child_of"
    RELATED_TO = "related_to"
    DEPENDS_ON = "depends_on"
    CONTRADICTS = "contradicts"
