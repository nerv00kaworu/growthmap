"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Node,
  type Edge,
  type Connection,
  BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { GrowthNode } from "./GrowthNode";
import type { GNode, Maturity } from "@/lib/types";
import { MATURITY_COLORS } from "@/lib/types";
import { useStore } from "@/stores/useStore";

const nodeTypes = { growth: GrowthNode };

function getHeatColor(updatedAt: string | undefined): string {
  if (!updatedAt) return "#a78bfa"; // never updated → purple
  const diff = (Date.now() - new Date(updatedAt).getTime()) / (1000 * 60 * 60 * 24);
  if (diff < 1) return "#22c55e";   // < 1 day: green
  if (diff < 3) return "#eab308";   // 1-3 days: yellow
  if (diff < 7) return "#f97316";   // 3-7 days: orange
  return "#ef4444";                  // > 7 days: red
}

// Collect all descendant IDs up to `maxDepth` levels
function collectDescendants(node: GNode, maxDepth: number): Set<string> {
  const ids = new Set<string>();
  function walk(n: GNode, d: number) {
    if (d > maxDepth) return;
    for (const c of n.children || []) {
      ids.add(c.id);
      walk(c, d + 1);
    }
  }
  walk(node, 0);
  return ids;
}

function collectAncestors(root: GNode, targetId: string): Set<string> {
  const ids = new Set<string>();
  function walk(n: GNode, path: string[]): boolean {
    if (n.id === targetId) {
      path.forEach((id) => ids.add(id));
      return true;
    }
    for (const c of n.children || []) {
      if (walk(c, [...path, n.id])) return true;
    }
    return false;
  }
  walk(root, []);
  return ids;
}

function getSiblings(root: GNode, targetId: string): Set<string> {
  const ids = new Set<string>();
  function walk(n: GNode) {
    const children = n.children || [];
    if (children.some((c) => c.id === targetId)) {
      children.forEach((c) => { if (c.id !== targetId) ids.add(c.id); });
      return;
    }
    for (const c of children) walk(c);
  }
  walk(root);
  return ids;
}

const RELATION_EDGE_STYLES: Record<string, Partial<Edge["style"]> & { animated?: boolean; strokeDasharray?: string }> = {
  depends_on: { stroke: "#f97316", strokeWidth: 2 },
  contradicts: { stroke: "#ef4444", strokeWidth: 2 },
  references: { stroke: "#6b7280", strokeWidth: 1.5 },
  supports: { stroke: "#22c55e", strokeWidth: 1.5 },
};

const RELATION_DASH: Record<string, string | undefined> = {
  depends_on: "6,3",
  contradicts: "5,3",
  references: "3,3",
  supports: undefined,
};

function treeToFlow(
  root: GNode,
  selectedId: string | null,
  highlightedIds: string[],
  heatmapMode: boolean,
  focusNodeId: string | null,
  extraEdges?: { from: string; to: string; relation: string }[]
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  const NODE_W = 220;
  const NODE_GAP = 40;
  const LEVEL_H = 150;

  // Build visible set for focus mode
  let visibleSet: Set<string> | null = null;
  if (focusNodeId) {
    visibleSet = new Set<string>();
    visibleSet.add(focusNodeId);
    // ancestors
    collectAncestors(root, focusNodeId).forEach((id) => visibleSet!.add(id));
    // descendants (3 levels)
    const focusNode = findInTree(root, focusNodeId);
    if (focusNode) collectDescendants(focusNode, 3).forEach((id) => visibleSet!.add(id));
    // siblings
    getSiblings(root, focusNodeId).forEach((id) => visibleSet!.add(id));
  }

  function calcWidth(node: GNode): number {
    const children = node.children || [];
    if (children.length === 0) return NODE_W;
    const childrenWidth = children.reduce((sum, c) => sum + calcWidth(c), 0);
    return childrenWidth + (children.length - 1) * NODE_GAP;
  }

  function place(node: GNode, x: number, y: number) {
    if (visibleSet && !visibleSet.has(node.id)) {
      // Still recurse children to place them if visible
      const children = node.children || [];
      const totalWidth = children.reduce((sum, c) => sum + calcWidth(c), 0) + (children.length - 1) * NODE_GAP;
      let cx = x + NODE_W / 2 - totalWidth / 2;
      for (const child of children) {
        const cw = calcWidth(child);
        const childX = cx + cw / 2 - NODE_W / 2;
        place(child, childX, y + LEVEL_H);
        cx += cw + NODE_GAP;
      }
      return;
    }

    const isHighlighted = highlightedIds.includes(node.id);
    const heatColor = heatmapMode ? getHeatColor(node.updated_at) : undefined;

    nodes.push({
      id: node.id,
      type: "growth",
      position: { x, y },
      data: {
        label: node.title,
        nodeType: node.node_type,
        maturity: node.maturity as Maturity,
        summary: node.summary,
        isSelected: node.id === selectedId,
        childCount: node.children?.length || 0,
        isMainline: Boolean(node.is_mainline),
        isHighlighted,
        heatColor,
        isBranch: Boolean(node.branch_id),
        updatedAt: node.updated_at,
      },
    });

    const children = node.children || [];
    if (children.length === 0) return;

    const totalWidth = children.reduce((sum, c) => sum + calcWidth(c), 0) + (children.length - 1) * NODE_GAP;
    let cx = x + NODE_W / 2 - totalWidth / 2;

    for (const child of children) {
      const cw = calcWidth(child);
      const childX = cx + cw / 2 - NODE_W / 2;

      const childVisible = !visibleSet || (visibleSet.has(node.id) && visibleSet.has(child.id));
      if (childVisible) {
        edges.push({
          id: `${node.id}-${child.id}`,
          source: node.id,
          target: child.id,
          style: child.is_mainline ? { stroke: "#60a5fa", strokeWidth: 2.5 } : { stroke: "#333", strokeWidth: 1.5 },
          animated: false,
        });
      }

      place(child, childX, y + LEVEL_H);
      cx += cw + NODE_GAP;
    }
  }

  place(root, 400, 0);

  // Add non-child_of relation edges
  if (extraEdges) {
    const nodeSet = new Set(nodes.map((n) => n.id));
    for (const e of extraEdges) {
      if (!nodeSet.has(e.from) || !nodeSet.has(e.to)) continue;
      const style = RELATION_EDGE_STYLES[e.relation] || { stroke: "#888", strokeWidth: 1 };
      const dash = RELATION_DASH[e.relation];
      edges.push({
        id: `rel-${e.from}-${e.to}-${e.relation}`,
        source: e.from,
        target: e.to,
        style: {
          ...style,
          ...(dash ? { strokeDasharray: dash } : {}),
        } as React.CSSProperties,
        label: e.relation,
        labelStyle: { fontSize: 10, fill: "#666" },
      });
    }
  }

  return { nodes, edges };
}

function findInTree(root: GNode, id: string): GNode | null {
  if (root.id === id) return root;
  for (const c of root.children || []) {
    const f = findInTree(c, id);
    if (f) return f;
  }
  return null;
}

function FitViewTrigger({ trigger }: { trigger: number }) {
  const { fitView } = useReactFlow();
  const prev = useRef(trigger);
  useEffect(() => {
    if (prev.current !== trigger) {
      prev.current = trigger;
      setTimeout(() => fitView({ duration: 400, padding: 0.15 }), 100);
    }
  }, [trigger, fitView]);
  return null;
}

export function MindMap() {
  const rootNode = useStore((s) => s.rootNode);
  const selectedNodeId = useStore((s) => s.selectedNodeId);
  const selectNode = useStore((s) => s.selectNode);
  const reparentNode = useStore((s) => s.reparentNode);
  const highlightedNodeIds = useStore((s) => s.highlightedNodeIds);

  const [heatmapMode, setHeatmapMode] = useState(false);
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null);
  const fitViewTrigger = useRef(0);
  const [fitTrigger, setFitTrigger] = useState(0);
  const prevProjectId = useRef<string | null>(null);

  // Trigger fit when project changes
  useEffect(() => {
    const projectId = rootNode?.project_id || null;
    if (projectId !== prevProjectId.current) {
      prevProjectId.current = projectId;
      fitViewTrigger.current++;
      setFitTrigger(fitViewTrigger.current);
    }
  }, [rootNode?.project_id]);

  const { flowNodes, flowEdges } = useMemo(() => {
    if (!rootNode) return { flowNodes: [], flowEdges: [] };
    const { nodes, edges } = treeToFlow(rootNode, selectedNodeId, highlightedNodeIds, heatmapMode, focusNodeId);
    return { flowNodes: nodes, flowEdges: edges };
  }, [rootNode, selectedNodeId, highlightedNodeIds, heatmapMode, focusNodeId]);

  const [nodes, setNodes, onNodesChange] = useNodesState(flowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(flowEdges);

  useEffect(() => {
    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [flowNodes, flowEdges, setNodes, setEdges]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      selectNode(node.id);
    },
    [selectNode]
  );

  const onNodeDoubleClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setFocusNodeId((prev) => (prev === node.id ? null : node.id));
    },
    []
  );

  const onPaneClick = useCallback(() => {
    selectNode(null);
  }, [selectNode]);

  const onConnect = useCallback(
    (connection: Connection) => {
      if (connection.source && connection.target) {
        reparentNode(connection.source, connection.target);
      }
    },
    [reparentNode]
  );

  const maturityColorForNode = useCallback((n: Node) => {
    const d = n.data as Record<string, unknown>;
    if (d?.heatColor) return d.heatColor as string;
    if (d?.isSelected) return "#3b82f6";
    if (d?.isHighlighted) return "#f59e0b";
    const maturity = d?.maturity as Maturity | undefined;
    if (maturity) return MATURITY_COLORS[maturity] || "#333";
    return "#333";
  }, []);

  if (!rootNode) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        選擇或建立一個專案
      </div>
    );
  }

  return (
    <div className="relative w-full h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onNodeDoubleClick={onNodeDoubleClick}
        onPaneClick={onPaneClick}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.2}
        maxZoom={2}
        defaultViewport={{ x: 0, y: 0, zoom: 0.8 }}
      >
        <FitViewTrigger trigger={fitTrigger} />
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#222" />
        <Controls />
        <MiniMap
          nodeColor={maturityColorForNode}
          maskColor="rgba(0,0,0,0.7)"
        />
      </ReactFlow>

      {/* Overlay controls */}
      <div className="absolute top-3 right-3 flex flex-col gap-1.5 z-10">
        <button
          type="button"
          onClick={() => setHeatmapMode((v) => !v)}
          className={`px-2.5 py-1.5 rounded-lg text-xs border transition-colors ${
            heatmapMode
              ? "bg-orange-600 border-orange-500 text-white"
              : "bg-gray-900/80 border-gray-700 text-gray-400 hover:text-gray-200"
          }`}
          title="熱力圖：以顏色顯示節點最後更新時間"
        >
          🌡️ 熱力圖
        </button>

        {focusNodeId && (
          <button
            type="button"
            onClick={() => setFocusNodeId(null)}
            className="px-2.5 py-1.5 rounded-lg text-xs border bg-blue-900/80 border-blue-600 text-blue-200 hover:bg-blue-800/80 transition-colors"
          >
            ✕ 退出聚焦
          </button>
        )}
      </div>

      {/* Heatmap legend */}
      {heatmapMode && (
        <div className="absolute bottom-20 left-3 bg-gray-900/90 border border-gray-700 rounded-xl px-3 py-2 text-xs text-gray-400 space-y-1 z-10">
          <div className="text-gray-300 font-medium mb-1.5">最後更新</div>
          {[
            { color: "#22c55e", label: "< 1 天" },
            { color: "#eab308", label: "1-3 天" },
            { color: "#f97316", label: "3-7 天" },
            { color: "#ef4444", label: "> 7 天" },
            { color: "#a78bfa", label: "從未更新" },
          ].map((item) => (
            <div key={item.label} className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full shrink-0" style={{ background: item.color }} />
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      )}

      {focusNodeId && (
        <div className="absolute top-3 left-3 bg-blue-950/80 border border-blue-700 rounded-lg px-3 py-1.5 text-xs text-blue-200 z-10">
          🔍 聚焦模式：雙擊節點退出
        </div>
      )}
    </div>
  );
}
