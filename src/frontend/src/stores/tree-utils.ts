import type { GNode } from "@/lib/types";

export interface UndoEntry {
  rootNode: GNode;
  description: string;
  projectId: string;
  branchId: string | null;
  projectGeneration: number;
  branchGeneration: number;
}

export const MAX_UNDO = 10;

/** Find a node without mutating the tree. */
export function findNode(node: GNode, id: string): GNode | null {
  if (node.id === id) return node;
  for (const child of node.children || []) {
    const found = findNode(child, id);
    if (found) return found;
  }
  return null;
}

/** Return a new tree with a child appended to its parent. */
export function insertChild(root: GNode, parentId: string, child: GNode): GNode {
  if (root.id === parentId) {
    return { ...root, children: [...(root.children || []), child] };
  }
  return {
    ...root,
    children: (root.children || []).map((node) => insertChild(node, parentId, child)),
  };
}

/** Return a new tree without a node and its descendants. */
export function removeNode(root: GNode, nodeId: string): GNode {
  return {
    ...root,
    children: (root.children || [])
      .filter((child) => child.id !== nodeId)
      .map((child) => removeNode(child, nodeId)),
  };
}

/** Return a new tree with a partial update applied to one node. */
export function patchNode(root: GNode, nodeId: string, patch: Partial<GNode>): GNode {
  if (root.id === nodeId) return { ...root, ...patch };
  return {
    ...root,
    children: (root.children || []).map((node) => patchNode(node, nodeId, patch)),
  };
}

/** Mark exactly one child edge as the active mainline for a parent. */
export function markMainlineChild(root: GNode, parentId: string, childId: string): GNode {
  if (root.id === parentId) {
    return {
      ...root,
      children: (root.children || []).map((child) => ({
        ...child,
        is_mainline: child.id === childId,
      })),
    };
  }
  return {
    ...root,
    children: (root.children || []).map((node) => markMainlineChild(node, parentId, childId)),
  };
}

/** Return IDs whose titles contain the case-insensitive query. */
export function searchNodes(node: GNode, query: string): string[] {
  const results = node.title.toLowerCase().includes(query.toLowerCase()) ? [node.id] : [];
  for (const child of node.children || []) results.push(...searchNodes(child, query));
  return results;
}

export function pushUndo(stack: UndoEntry[], rootNode: GNode, description: string, owner: Omit<UndoEntry, "rootNode" | "description">): UndoEntry[] {
  return [{ rootNode, description, ...owner }, ...stack].slice(0, MAX_UNDO);
}
