"""Product-owned canonical content-block vocabulary.

All persisted/create-block and AI deepen paths accept these lossless historical
values.  The frontend mirrors this enum at the TypeScript language boundary.
"""
from enum import StrEnum

class ContentBlockType(StrEnum):
    paragraph = "paragraph"
    bullet_list = "bullet_list"
    rule_set = "rule_set"
    example = "example"
    risk_note = "risk_note"
    decision_log = "decision_log"
    todo = "todo"
    prompt_context = "prompt_context"
    code = "code"
    quote = "quote"
    table = "table"
    text = "text"
    markdown = "markdown"
    note = "note"
    question = "question"
    task = "task"
    decision = "decision"
    risk = "risk"
    resource = "resource"
    definition = "definition"
    rules = "rules"
    spec = "spec"

CONTENT_BLOCK_TYPES = tuple(item.value for item in ContentBlockType)
CONTENT_BLOCK_TYPES_PROMPT = ", ".join(CONTENT_BLOCK_TYPES)
