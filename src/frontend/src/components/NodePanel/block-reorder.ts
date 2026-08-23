export type OrderedBlock = { id: string; order_index: number };

export type CoherentOwner<T extends OrderedBlock> = {
  project: unknown;
  node: unknown;
  blocks: T[];
};

/** One reorder PATCH followed by an all-or-nothing owner revision readback. */
export async function reorderBlockAuthoritatively<T extends OrderedBlock>(
  blocks: T[],
  index: number,
  direction: -1 | 1,
  update: (blockId: string, orderIndex: number) => Promise<unknown>,
  reloadOwner: () => Promise<CoherentOwner<T>>,
  publish: (owner: CoherentOwner<T>) => void,
  invalidate: () => void,
): Promise<{ moved: false; blocks: T[] } | { moved: true; blocks: T[] }> {
  const nextIndex = index + direction;
  if (nextIndex < 0 || nextIndex >= blocks.length) return { moved: false, blocks };
  await update(blocks[index].id, nextIndex);
  try {
    const owner = await reloadOwner();
    publish(owner);
    return { moved: true, blocks: owner.blocks };
  } catch (error) {
    invalidate();
    throw new Error("CONTENT_REORDER_SAVED_REFRESH_FAILED", { cause: error });
  }
}
