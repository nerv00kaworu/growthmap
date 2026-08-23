"""Shared transaction-local canonical ContentBlock ordering primitives."""
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import ContentBlock


async def ordered_blocks(db: AsyncSession, node_id: str) -> list[ContentBlock]:
    return list((await db.execute(
        select(ContentBlock).where(ContentBlock.node_id == node_id)
        .order_by(ContentBlock.order_index, ContentBlock.created_at, ContentBlock.id)
    )).scalars().all())


def set_block_order(block: ContentBlock, index: int) -> None:
    """Narrow write seam for rollback fault injection."""
    block.order_index = index


def rewrite_dense(blocks: Iterable[ContentBlock], *, existing_ids: set[str] | None = None) -> list[ContentBlock]:
    """Rewrite dense order and return existing rows whose final order changed."""
    rows = list(blocks)
    existing = existing_ids if existing_ids is not None else {str(row.id) for row in rows}
    original = {str(row.id): row.order_index for row in rows if str(row.id) in existing}
    for index, block in enumerate(rows):
        if block.order_index != index:
            set_block_order(block, index)
    return [row for row in rows if str(row.id) in original and original[str(row.id)] != row.order_index]


async def insert_blocks(
    db: AsyncSession,
    node_id: str,
    insertions: Iterable[tuple[ContentBlock, int | None]],
) -> list[ContentBlock]:
    """Canonicalize legacy rows then apply requested inserts sequentially."""
    rows = await ordered_blocks(db, node_id)
    existing_ids = {str(row.id) for row in rows}
    original = {str(row.id): row.order_index for row in rows}
    # Canonical legacy order is the starting sequence; caller/execution order then
    # deterministically applies each insertion to the evolving list.
    for block, requested in insertions:
        target = len(rows) if requested is None else max(0, min(requested, len(rows)))
        rows.insert(target, block)
    for index, block in enumerate(rows):
        if block.order_index != index:
            set_block_order(block, index)
    return [row for row in rows if str(row.id) in existing_ids and original[str(row.id)] != row.order_index]
