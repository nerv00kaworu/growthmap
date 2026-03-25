"""Test data factories for GrowthMap backend tests.

Usage:
    project_data = ProjectFactory()
    node_data = NodeFactory(project_id=some_project_id)
    edge_data = EdgeFactory(project_id=pid, from_node_id=a, to_node_id=b)

Each factory returns a dict suitable for direct model construction
or API request body.
"""
import uuid
from datetime import datetime, timezone


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProjectFactory:
    """Generate project creation dicts."""

    _counter = 0

    @classmethod
    def create(cls, **overrides) -> dict:
        cls._counter += 1
        defaults = {
            "name": f"Test Project {cls._counter}",
            "description": f"Auto-generated test project #{cls._counter}",
            "goal": "testing",
        }
        defaults.update(overrides)
        return defaults

    @classmethod
    def reset(cls):
        cls._counter = 0


class NodeFactory:
    """Generate node creation dicts."""

    _counter = 0

    @classmethod
    def create(cls, *, project_id: str | None = None, parent_id: str | None = None, **overrides) -> dict:
        cls._counter += 1
        defaults: dict = {
            "title": f"Test Node {cls._counter}",
            "summary": f"Summary for node #{cls._counter}",
            "node_type": "idea",
        }
        if parent_id is not None:
            defaults["parent_id"] = parent_id
        defaults.update(overrides)
        return defaults

    @classmethod
    def reset(cls):
        cls._counter = 0


class EdgeFactory:
    """Generate edge creation dicts."""

    _counter = 0

    @classmethod
    def create(cls, *, from_node_id: str, to_node_id: str, **overrides) -> dict:
        cls._counter += 1
        defaults = {
            "from_node_id": from_node_id,
            "to_node_id": to_node_id,
            "relation_type": "child_of",
        }
        defaults.update(overrides)
        return defaults

    @classmethod
    def reset(cls):
        cls._counter = 0
