import type { Edge, Node } from "@xyflow/react";
import type { GNode, Maturity } from "@/lib/types";

const NODE_W = 220;
const NODE_GAP = 40;
const LEVEL_H = 150;

export type LayoutDiagnostics = {
  nodeCount: number;
  widthComputations: number;
  durationMs: number;
};

export type LayoutOptions = {
  highlightedIds?: string[];
  heatmapMode?: boolean;
  focusNodeId?: string | null;
  extraEdges?: { id: string; from: string; to: string; relation: string }[];
  graphMode?: boolean;
  relationFilter?: Set<string>;
  graphVisibleIds?: Set<string> | null;
  now?: () => number;
  report?: (diagnostics: LayoutDiagnostics) => void;
};

const relationStyles: Record<string, Partial<Edge["style"]>> = {
  depends_on: { stroke: "#f97316", strokeWidth: 2 },
  contradicts: { stroke: "#ef4444", strokeWidth: 2 },
  references: { stroke: "#6b7280", strokeWidth: 1.5 },
  supports: { stroke: "#22c55e", strokeWidth: 1.5 },
};

const relationDash: Record<string, string | undefined> = {
  depends_on: "6,3",
  contradicts: "5,3",
  references: "3,3",
  supports: undefined,
};

function getHeatColor(updatedAt: string | undefined): string {
  if (!updatedAt) return "#a78bfa";
  const days = (Date.now() - new Date(updatedAt).getTime()) / 86_400_000;
  if (days < 1) return "#22c55e";
  if (days < 3) return "#eab308";
  if (days < 7) return "#f97316";
  return "#ef4444";
}

function findInTree(root: GNode, id: string): GNode | null {
  if (root.id === id) return root;
  for (const child of root.children || []) {
    const found = findInTree(child, id);
    if (found) return found;
  }
  return null;
}

function collectAncestors(root: GNode, targetId: string): Set<string> {
  const ids = new Set<string>();
  const walk = (node: GNode, path: string[]): boolean => {
    if (node.id === targetId) {
      path.forEach((id) => ids.add(id));
      return true;
    }
    return (node.children || []).some((child) => walk(child, [...path, node.id]));
  };
  walk(root, []);
  return ids;
}

// This deliberately preserves the old MindMap implementation: maxDepth=3
// includes children visited at depths 0, 1, 2, and 3 (four tree edges).
function collectDescendants(node: GNode, maxDepth: number, ids: Set<string>, depth = 0): void {
  if (depth > maxDepth) return;
  for (const child of node.children || []) {
    ids.add(child.id);
    collectDescendants(child, maxDepth, ids, depth + 1);
  }
}

function collectSiblings(root: GNode, targetId: string, ids: Set<string>): void {
  const walk = (node: GNode): boolean => {
    const children = node.children || [];
    if (children.some((child) => child.id === targetId)) {
      children.forEach((child) => { if (child.id !== targetId) ids.add(child.id); });
      return true;
    }
    return children.some(walk);
  };
  walk(root);
}

/** A post-order width cache: each tree node is measured exactly once per layout. */
export function createSubtreeWidthCache(root: GNode): { widths: Map<string, number>; computations: number } {
  const widths = new Map<string, number>();
  let computations = 0;
  const visit = (node: GNode): number => {
    const children = node.children || [];
    const width = children.length === 0
      ? NODE_W
      : children.reduce((sum, child) => sum + visit(child), 0) + (children.length - 1) * NODE_GAP;
    widths.set(node.id, width);
    computations++;
    return width;
  };
  visit(root);
  return { widths, computations };
}

/** Structural layout only; selection decoration is intentionally applied separately. */
export function layoutTreeToFlow(root: GNode, options: LayoutOptions = {}): { nodes: Node[]; edges: Edge[]; diagnostics: LayoutDiagnostics } {
  const now = options.now || performance.now.bind(performance);
  const started = now();
  const highlightedIds = options.highlightedIds || [];
  const heatmapMode = options.heatmapMode || false;
  const { widths, computations } = createSubtreeWidthCache(root);
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  let visibleSet: Set<string> | null = null;
  if (options.focusNodeId) {
    visibleSet = new Set([options.focusNodeId]);
    collectAncestors(root, options.focusNodeId).forEach((id) => visibleSet!.add(id));
    const focused = findInTree(root, options.focusNodeId);
    if (focused) collectDescendants(focused, 3, visibleSet);
    collectSiblings(root, options.focusNodeId, visibleSet);
  }

  const place = (node: GNode, x: number, y: number): void => {
    const children = node.children || [];
    const totalWidth = children.reduce((sum, child) => sum + (widths.get(child.id) || NODE_W), 0) + (children.length - 1) * NODE_GAP;
    let childCursor = x + NODE_W / 2 - totalWidth / 2;

    if (!visibleSet || visibleSet.has(node.id)) {
      nodes.push({ id: node.id, type: "growth", position: { x, y }, data: {
        label: node.title, nodeType: node.node_type, maturity: node.maturity as Maturity,
        summary: node.summary, isSelected: false, childCount: children.length,
        isMainline: Boolean(node.is_mainline), isHighlighted: highlightedIds.includes(node.id),
        heatColor: heatmapMode ? getHeatColor(node.updated_at) : undefined,
        isBranch: Boolean(node.branch_id), updatedAt: node.updated_at,
      } });
    }

    for (const child of children) {
      const childWidth = widths.get(child.id) || NODE_W;
      const childX = childCursor + childWidth / 2 - NODE_W / 2;
      if (!visibleSet || (visibleSet.has(node.id) && visibleSet.has(child.id))) {
        edges.push({ id: `${node.id}-${child.id}`, source: node.id, target: child.id,
          style: child.is_mainline ? { stroke: "#60a5fa", strokeWidth: 2.5 } : { stroke: "#333", strokeWidth: 1.5 }, animated: false });
      }
      place(child, childX, y + LEVEL_H);
      childCursor += childWidth + NODE_GAP;
    }
  };
  place(root, 400, 0);

  if (options.graphMode && options.graphVisibleIds) {
    const shown = options.graphVisibleIds;
    for (let index = nodes.length - 1; index >= 0; index--) if (!shown.has(nodes[index].id)) nodes.splice(index, 1);
    for (let index = edges.length - 1; index >= 0; index--) if (!shown.has(edges[index].source) || !shown.has(edges[index].target)) edges.splice(index, 1);
  }

  if (options.graphMode) {
    const depthById = new Map<string, number>();
    const recordDepth = (node: GNode, depth: number): void => { depthById.set(node.id, depth); (node.children || []).forEach((child) => recordDepth(child, depth + 1)); };
    recordDepth(root, 0);
    const layers = new Map<number, Node[]>();
    nodes.forEach((node) => { const depth = depthById.get(node.id) || 0; layers.set(depth, [...(layers.get(depth) || []), node]); });
    [...layers.entries()].sort(([a], [b]) => a - b).forEach(([depth, layer]) => layer.sort((a, b) => a.id.localeCompare(b.id)).forEach((node, index) => { node.position = { x: 300 + index * 280, y: depth * 180 }; }));
  }

  if (options.extraEdges) {
    const nodeIds = new Set(nodes.map((node) => node.id));
    for (const edge of options.extraEdges) {
      if (!nodeIds.has(edge.from) || !nodeIds.has(edge.to) || (options.relationFilter?.size && !options.relationFilter.has(edge.relation))) continue;
      const dash = relationDash[edge.relation];
      edges.push({ id: `rel-${edge.id}`, source: edge.from, target: edge.to,
        style: { ...(relationStyles[edge.relation] || { stroke: "#888", strokeWidth: 1 }), ...(dash ? { strokeDasharray: dash } : {}) } as React.CSSProperties,
        label: edge.relation, labelStyle: { fontSize: 10, fill: "#666" } });
    }
  }

  const diagnostics = { nodeCount: widths.size, widthComputations: computations, durationMs: now() - started };
  options.report?.(diagnostics);
  return { nodes, edges, diagnostics };
}

export function decorateSelection(nodes: Node[], selectedId: string | null): Node[] {
  return nodes.map((node) => {
    const isSelected = node.id === selectedId;
    return Boolean((node.data as Record<string, unknown>).isSelected) === isSelected ? node : { ...node, data: { ...node.data, isSelected } };
  });
}

/** The MindMap effect's complete ReactFlow state update, kept DOM-free for regression coverage. */
export function syncFlowState(
  setNodes: (nodes: Node[]) => void,
  setEdges: (edges: Edge[]) => void,
  nodes: Node[],
  edges: Edge[],
): void {
  setNodes(nodes);
  setEdges(edges);
}
