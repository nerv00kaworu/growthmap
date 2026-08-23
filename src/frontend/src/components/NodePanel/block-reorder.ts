export type OrderedBlock = { id: string; order_index: number };

/** One authoritative reorder PATCH followed by coherent server readback. */
export async function reorderBlockAuthoritatively<T extends OrderedBlock>(
  blocks: T[],
  index: number,
  direction: -1 | 1,
  update: (blockId: string, orderIndex: number) => Promise<unknown>,
  reload: () => Promise<T[]>,
): Promise<T[]> {
  const nextIndex = index + direction;
  if (nextIndex < 0 || nextIndex >= blocks.length) return blocks;
  await update(blocks[index].id, nextIndex);
  return reload();
}
