"use client";
import { useI18n } from "@/i18n/provider";
import { msg } from "@/i18n/ui";

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
import type { Edge as GraphEdge, GNode, Maturity } from "@/lib/types";
import { api } from "@/lib/api";
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
  extraEdges?: { id: string; from: string; to: string; relation: string }[],
  graphMode = false,
  relationFilter: Set<string> = new Set(),
  graphVisibleIds: Set<string> | null = null
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

  if (graphMode && graphVisibleIds) {
    const visible = new Set(graphVisibleIds);
    for (let index = nodes.length - 1; index >= 0; index--) {
      if (!visible.has(nodes[index].id)) nodes.splice(index, 1);
    }
    for (let index = edges.length - 1; index >= 0; index--) {
      if (!visible.has(edges[index].source) || !visible.has(edges[index].target)) edges.splice(index, 1);
    }
  }

  // Stable layered graph layout: keeps the tree backbone readable; graph links cross layers.
  if (graphMode) {
    const byDepth = new Map<number, Node[]>();
    const depthById = new Map<string, number>();
    const walkDepth = (node: GNode, depth: number) => { depthById.set(node.id, depth); (node.children || []).forEach((child) => walkDepth(child, depth + 1)); };
    walkDepth(root, 0);
    nodes.forEach((flowNode) => {
      const depth = depthById.get(flowNode.id) || 0;
      byDepth.set(depth, [...(byDepth.get(depth) || []), flowNode]);
    });
    Array.from(byDepth.entries()).sort(([a], [b]) => a - b).forEach(([depth, layer]) => {
      layer.sort((a, b) => a.id.localeCompare(b.id));
      layer.forEach((flowNode, index) => { flowNode.position = { x: 300 + index * 280, y: depth * 180 }; });
    });
  }

  // Add non-child_of relation edges
  if (extraEdges) {
    const nodeSet = new Set(nodes.map((n) => n.id));
    for (const e of extraEdges) {
      if (!nodeSet.has(e.from) || !nodeSet.has(e.to) || (relationFilter.size > 0 && !relationFilter.has(e.relation))) continue;
      const style = RELATION_EDGE_STYLES[e.relation] || { stroke: "#888", strokeWidth: 1 };
      const dash = RELATION_DASH[e.relation];
      edges.push({
        id: `rel-${e.id}`,
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
  const { locale } = useI18n();
  const u = useCallback((tw: string, cn: string, en: string) => msg(locale, {"zh-TW":tw,"zh-CN":cn,en}), [locale]);
  const rootNode = useStore((s) => s.rootNode);
  const selectedNodeId = useStore((s) => s.selectedNodeId);
  const selectNode = useStore((s) => s.selectNode);
  const reparentNode = useStore((s) => s.reparentNode);
  const highlightedNodeIds = useStore((s) => s.highlightedNodeIds);

  const [heatmapMode, setHeatmapMode] = useState(false);
  const [graphMode, setGraphMode] = useState(false);
  const [relations, setRelations] = useState<GraphEdge[]>([]);
  const [activeRelations, setActiveRelations] = useState<Set<string>>(new Set());
  const [newRelationType, setNewRelationType] = useState("depends_on");
  const [relationError, setRelationError] = useState("");
  const [nodeQuery, setNodeQuery] = useState("");
  const [hopDepth, setHopDepth] = useState<0 | 1 | 2>(0);
  const [graphDirection, setGraphDirection] = useState<"both" | "upstream" | "downstream">("both");
  const [minWeight, setMinWeight] = useState(0);
  const relationTypes = Array.from(new Set(relations.filter((edge) => edge.relation_type !== "child_of").map((edge) => edge.relation_type)));
  const nodeTitles = useMemo(() => {
    const titles = new Map<string, string>();
    const walk = (node: GNode) => { titles.set(node.id, node.title); (node.children || []).forEach(walk); };
    if (rootNode) walk(rootNode);
    return titles;
  }, [rootNode]);
  const saveRelation = async (edge: GraphEdge, changes: { weight?: number; note?: string }) => {
    try {
      const updated = await api.updateEdge(edge.id, changes);
      setRelations((rows) => rows.map((row) => row.id === edge.id ? updated : row));
    } catch (error: unknown) { setRelationError(u(`更新關係失敗：${(error as Error).message}`,`更新关系失败：${(error as Error).message}`,`Failed to update relationship: ${(error as Error).message}`)); }
  };
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null);
  const graphVisibleIds = useMemo(() => {
    if (!graphMode) return null;
    const allIds = new Set(nodeTitles.keys());
    const query = nodeQuery.trim().toLowerCase();
    let seedIds = new Set(query ? Array.from(nodeTitles.entries()).filter(([, title]) => title.toLowerCase().includes(query)).map(([id]) => id) : allIds);
    if (selectedNodeId && hopDepth > 0) seedIds = new Set([selectedNodeId]);
    if (hopDepth === 0) return seedIds;
    const visible = new Set(seedIds);
    let frontier = new Set(seedIds);
    for (let hop = 0; hop < hopDepth; hop++) {
      const next = new Set<string>();
      relations.filter((edge) => edge.relation_type !== "child_of" && edge.weight >= minWeight).forEach((edge) => {
        if ((graphDirection === "both" || graphDirection === "downstream") && frontier.has(edge.from_node_id)) { next.add(edge.to_node_id); }
        if ((graphDirection === "both" || graphDirection === "upstream") && frontier.has(edge.to_node_id)) { next.add(edge.from_node_id); }
      });
      next.forEach((id) => visible.add(id)); frontier = next;
    }
    return visible;
  }, [graphMode, nodeTitles, nodeQuery, selectedNodeId, hopDepth, relations, graphDirection, minWeight]);
  const fitViewTrigger = useRef(0);
  const [fitTrigger, setFitTrigger] = useState(0);
  const prevProjectId = useRef<string | null>(null);

  useEffect(() => {
    if (!rootNode) { setRelations([]); return; }
    api.listEdges(rootNode.project_id).then(setRelations).catch((error: unknown) => setRelationError((error as Error).message));
  }, [rootNode]);

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
    const { nodes, edges } = treeToFlow(rootNode, selectedNodeId, highlightedNodeIds, heatmapMode, focusNodeId, relations.filter((edge) => edge.relation_type !== "child_of" && edge.weight >= minWeight).map((edge) => ({ id: edge.id, from: edge.from_node_id, to: edge.to_node_id, relation: edge.relation_type })), graphMode, activeRelations, graphVisibleIds);
    return { flowNodes: nodes, flowEdges: edges };
  }, [rootNode, selectedNodeId, highlightedNodeIds, heatmapMode, focusNodeId, relations, graphMode, activeRelations, graphVisibleIds, minWeight]);

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
        if (!graphMode) {
          reparentNode(connection.source, connection.target);
          return;
        }
        api.createEdge({ from_node_id: connection.source, to_node_id: connection.target, relation_type: newRelationType })
          .then((edge) => setRelations((rows) => [...rows, edge as typeof rows[number]]))
          .catch((error: unknown) => setRelationError(u(`建立關係失敗：${(error as Error).message}`,`创建关系失败：${(error as Error).message}`,`Failed to create relationship: ${(error as Error).message}`)));
      }
    },
    [reparentNode, graphMode, newRelationType, u]
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
        {u('選擇或建立一個專案','选择或创建一个项目','Select or create a project')}
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
        <button type="button" onClick={() => setGraphMode((value) => !value)} className={`px-2.5 py-1.5 rounded-lg text-xs border transition-colors ${graphMode ? "bg-purple-700 border-purple-500 text-white" : "bg-gray-900/80 border-gray-700 text-gray-400 hover:text-gray-200"}`} title={u("圖譜模式僅建立非樹狀關係", "图谱模式仅创建非树状关系", "Graph mode creates non-tree relationships only")}>
          {graphMode ? u("◉ 圖譜模式", "◉ 图谱模式", "◉ Graph mode") : u("◎ 樹狀模式", "◎ 树状模式", "◎ Tree mode")}
        </button>
        {graphMode && <><select value={newRelationType} onChange={(event) => setNewRelationType(event.target.value)} className="rounded border border-purple-800 bg-gray-900/90 px-2 py-1 text-xs text-purple-100"><option value="depends_on">depends_on</option><option value="supports">supports</option><option value="contradicts">contradicts</option><option value="references">references</option><option value="blocks">blocks</option><option value="relates_to">relates_to</option></select><div className="rounded border border-gray-700 bg-gray-900/90 p-2 text-[11px] text-gray-400"><input value={nodeQuery} onChange={(event) => setNodeQuery(event.target.value)} placeholder={u("搜尋節點…", "搜索节点…", "Search nodes…")} className="mb-2 w-full rounded border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-100" /><div className="mb-1">{u('關係範圍','关系范围','Relationship scope')}</div><div className="flex gap-1"><select value={hopDepth} onChange={(event) => setHopDepth(Number(event.target.value) as 0 | 1 | 2)} className="min-w-0 flex-1 rounded border border-gray-700 bg-gray-800 px-1 py-1"><option value={0}>{u('全部','全部','All')}</option><option value={1}>{u('1 跳','1 跳','1 hop')}</option><option value={2}>{u('2 跳','2 跳','2 hops')}</option></select><select value={graphDirection} onChange={(event) => setGraphDirection(event.target.value as "both" | "upstream" | "downstream")} className="min-w-0 flex-1 rounded border border-gray-700 bg-gray-800 px-1 py-1"><option value="both">{u('雙向','双向','Both')}</option><option value="upstream">{u('上游','上游','Upstream')}</option><option value="downstream">{u('下游','下游','Downstream')}</option></select></div><label className="mt-2 block">{u('最低權重','最低权重','Minimum weight')} {minWeight.toFixed(2)}<input type="range" min="0" max="1" step="0.05" value={minWeight} onChange={(event) => setMinWeight(Number(event.target.value))} className="w-full accent-purple-500" /></label><div className="mb-1 mt-2">{u('顯示關係','显示关系','Relationships shown')}</div>{relationTypes.length === 0 ? <div className="text-gray-600">{u('尚無非樹狀關係','暂无非树状关系','No non-tree relationships')}</div> : relationTypes.map((relation) => <label key={relation} className="flex items-center gap-1"><input type="checkbox" checked={activeRelations.size === 0 || activeRelations.has(relation)} onChange={() => setActiveRelations((previous) => { const next = new Set(previous); if (previous.size === 0) relationTypes.forEach((type) => next.add(type)); if (next.has(relation)) next.delete(relation); else next.add(relation); return next; })} />{relation}</label>)}</div></>}
        <button
          type="button"
          onClick={() => setHeatmapMode((v) => !v)}
          className={`px-2.5 py-1.5 rounded-lg text-xs border transition-colors ${
            heatmapMode
              ? "bg-orange-600 border-orange-500 text-white"
              : "bg-gray-900/80 border-gray-700 text-gray-400 hover:text-gray-200"
          }`}
          title={u("熱力圖：以顏色顯示節點最後更新時間", "热力图：用颜色显示节点最后更新时间", "Heatmap: color nodes by last update time")}
        >
          {u('🌡️ 熱力圖','🌡️ 热力图','🌡️ Heatmap')}
        </button>

        {focusNodeId && (
          <button
            type="button"
            onClick={() => setFocusNodeId(null)}
            className="px-2.5 py-1.5 rounded-lg text-xs border bg-blue-900/80 border-blue-600 text-blue-200 hover:bg-blue-800/80 transition-colors"
          >
            {u('✕ 退出聚焦','✕ 退出聚焦','✕ Exit focus')}
          </button>
        )}
      </div>

      {relationError && <div className="absolute top-3 left-3 max-w-sm rounded border border-red-800 bg-red-950/90 px-3 py-2 text-xs text-red-200 z-10">{relationError}</div>}

      {graphMode && selectedNodeId && <div className="absolute bottom-3 left-3 max-h-[45vh] w-80 overflow-y-auto rounded-xl border border-purple-800/60 bg-gray-900/95 p-3 text-xs z-10"><div className="font-medium text-purple-100">{u('已選節點的關係','所选节点的关系','Selected node relationships')}</div><div className="mt-1 flex gap-2 text-[11px]"><span className="text-orange-300">{u('依賴／阻塞','依赖/阻塞','Dependencies / blocks')} {relations.filter((edge) => edge.to_node_id === selectedNodeId && ["depends_on", "blocks"].includes(edge.relation_type)).length}</span><span className="text-emerald-300">{u('支援','支持','Supports')} {relations.filter((edge) => edge.to_node_id === selectedNodeId && edge.relation_type === "supports").length}</span><span className="text-red-300">{u('反駁','反驳','Contradicts')} {relations.filter((edge) => edge.to_node_id === selectedNodeId && edge.relation_type === "contradicts").length}</span></div><div className="mt-2 space-y-2">{relations.filter((edge) => edge.relation_type !== "child_of" && (edge.from_node_id === selectedNodeId || edge.to_node_id === selectedNodeId)).length === 0 ? <div className="text-gray-500">{u('拖曳節點到另一節點建立關係。','将节点拖到另一节点上以创建关系。','Drag a node onto another node to create a relationship.')}</div> : relations.filter((edge) => edge.relation_type !== "child_of" && (edge.from_node_id === selectedNodeId || edge.to_node_id === selectedNodeId)).map((edge) => <div key={edge.id} className="rounded border border-gray-800 bg-gray-950/60 p-2"><div className="flex items-center justify-between gap-2 text-gray-300"><span>{edge.from_node_id === selectedNodeId ? "→" : "←"} {edge.relation_type}</span><button type="button" onClick={() => api.deleteEdge(edge.id).then(() => setRelations((rows) => rows.filter((row) => row.id !== edge.id))).catch((error: unknown) => setRelationError(u(`刪除失敗：${(error as Error).message}`,`删除失败：${(error as Error).message}`,`Delete failed: ${(error as Error).message}`)))} className="text-red-300 hover:text-red-200">{u('移除','移除','Remove')}</button></div><div className="mt-1 text-[11px] text-gray-500">{nodeTitles.get(edge.from_node_id) || u("未知", "未知", "Unknown")} → {nodeTitles.get(edge.to_node_id) || u("未知", "未知", "Unknown")}</div><label className="mt-2 block text-[11px] text-gray-500">{u('權重','权重','Weight')} {edge.weight.toFixed(2)}<input type="range" min="0" max="1" step="0.05" value={edge.weight} onChange={(event) => void saveRelation(edge, { weight: Number(event.target.value) })} className="mt-1 w-full accent-purple-500" /></label><textarea defaultValue={edge.note} onBlur={(event) => { if (event.target.value !== edge.note) void saveRelation(edge, { note: event.target.value }); }} placeholder={u("關係依據／備註", "关系依据/备注", "Relationship rationale / notes")} className="mt-2 min-h-12 w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 text-[11px] text-gray-200" /></div>)}</div></div>}

      {/* Heatmap legend */}
      {heatmapMode && (
        <div className="absolute bottom-20 left-3 bg-gray-900/90 border border-gray-700 rounded-xl px-3 py-2 text-xs text-gray-400 space-y-1 z-10">
          <div className="text-gray-300 font-medium mb-1.5">{u('最後更新','最后更新','Last updated')}</div>
          {[
            { color: "#22c55e", label: u("< 1 天", "< 1 天", "< 1 day") },
            { color: "#eab308", label: u("1-3 天", "1-3 天", "1–3 days") },
            { color: "#f97316", label: u("3-7 天", "3-7 天", "3–7 days") },
            { color: "#ef4444", label: u("> 7 天", "> 7 天", "> 7 days") },
            { color: "#a78bfa", label: u("從未更新", "从未更新", "Never updated") },
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
          {u('🔍 聚焦模式：雙擊節點退出','🔍 聚焦模式：双击节点退出','🔍 Focus mode: double-click a node to exit')}
        </div>
      )}
    </div>
  );
}
