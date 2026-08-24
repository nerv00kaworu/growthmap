export type OrderedBlock = { id: string; node_id: string; order_index: number };
export type OwnerToken = { projectId: string; nodeId: string; generation: number };
export type CoherentOwner<T extends OrderedBlock> = {
  project: { id: string };
  node: { id: string; project_id: string };
  blocks: T[];
};
export type OwnerGate = { current: (token: OwnerToken) => boolean };

function matchesOwner<T extends OrderedBlock>(owner: CoherentOwner<T>, token: OwnerToken): boolean {
  return owner.project.id === token.projectId
    && owner.node.id === token.nodeId
    && owner.node.project_id === token.projectId
    && owner.blocks.every(block => block.node_id === token.nodeId);
}

/** One reorder PATCH followed by owner-validated, supersession-safe readback. */
export async function reorderBlockAuthoritatively<T extends OrderedBlock>(
  blocks: readonly T[], index: number, direction: -1 | 1, token: OwnerToken, gate: OwnerGate,
  update: (blockId: string, orderIndex: number) => Promise<unknown>,
  reloadOwner: () => Promise<CoherentOwner<T>>,
  publish: (owner: CoherentOwner<T>) => void,
  invalidate: (token: OwnerToken) => void,
): Promise<{ moved: false } | { moved: true } | { moved: false; superseded: true }> {
  const nextIndex = index + direction;
  if (nextIndex < 0 || nextIndex >= blocks.length) return { moved: false };
  await update(blocks[index].id, nextIndex);
  try {
    const owner = await reloadOwner();
    if (!gate.current(token)) {
      invalidate(token);
      return { moved: false, superseded: true };
    }
    if (!matchesOwner(owner, token)) throw new Error("OWNER_MISMATCH");
    publish(owner);
    return { moved: true };
  } catch (error) {
    if (!gate.current(token)) {
      invalidate(token);
      return { moved: false, superseded: true };
    }
    invalidate(token);
    throw new Error("CONTENT_REORDER_SAVED_REFRESH_FAILED", { cause: error });
  }
}
