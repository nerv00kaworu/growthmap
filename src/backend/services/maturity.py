"""Canonical node maturity evaluation and side effects."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from models.models import ActionLog, ContentBlock, Edge, Node
from services.revisions import TouchedEntities

MATURITY_ORDER = ["seed", "rough", "developing", "stable", "finalized"]

async def auto_advance_maturity(node_id: str, db: AsyncSession, *, touched: TouchedEntities | None = None):
    node = await db.get(Node, node_id)
    if not node or node.maturity == "finalized":
        return
    block_count, child_count = (await db.execute(select(
        select(func.count()).select_from(ContentBlock).where(ContentBlock.node_id == node_id).scalar_subquery(),
        select(func.count()).select_from(Edge).where(Edge.from_node_id == node_id, Edge.relation_type == "child_of").scalar_subquery(),
    ))).one()
    has_summary = bool(node.summary and len(node.summary.strip()) > 10)
    current = node.maturity
    new_maturity = current
    if current == "seed" and (has_summary or (child_count or 0) >= 1): new_maturity = "rough"
    if current in ("seed", "rough") and (block_count or 0) >= 1 and (child_count or 0) >= 1: new_maturity = "developing"
    if current in ("seed", "rough", "developing") and (block_count or 0) >= 3 and has_summary and (child_count or 0) >= 2: new_maturity = "stable"
    if new_maturity != current:
        node.maturity = new_maturity
        if touched is not None: touched.add(node)
        db.add(ActionLog(project_id=node.project_id, node_id=node.id, actor_type="system",
                         action_type="maturity_advance", payload={"from": current, "to": new_maturity}))
