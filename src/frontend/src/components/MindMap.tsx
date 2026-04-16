"use client";

import { useCallback, useEffect, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  BackgroundVariant,
  addEdge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { GrowthNode } from "./GrowthNode";
import type { GNode, Maturity } from "@/lib/types";
import { useStore } from "@/stores/useStore";

const nodeTypes = { growth: GrowthNode };

// Convert tree to React Flow nodes/edges with auto-layout
function treeToFlow(
  root: GNode,
  selectedId: string | null,
  highlightedIds: string[]
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  const NODE_W = 220;
  const NODE_GAP = 40;
  const LEVEL_H = 150;

  function calcWidth(node: GNode): number {
    const children = node.children || [];
    if (children.length === 0) return NODE_W;
    const childrenWidth = children.reduce((sum, c) => sum + calcWidth(c), 0);
    return childrenWidth + (children.length - 1) * NODE_GAP;
  }

  function place(node: GNode, x: number, y: number) {
    const isHighlighted = highlightedIds.includes(node.id);
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
      },
    });

    const children = node.children || [];
    if (children.length === 0) return;

    const totalWidth = children.reduce((sum, c) => sum + calcWidth(c), 0) + (children.length - 1) * NODE_GAP;
    let cx = x + NODE_W / 2 - totalWidth / 2;

    for (const child of children) {
      const cw = calcWidth(child);
      const childX = cx + cw / 2 - NODE_W / 2;

      edges.push({
        id: `${node.id}-${child.id}`,
        source: node.id,
        target: child.id,
        style: child.is_mainline ? { stroke: "#60a5fa", strokeWidth: 2.5 } : { stroke: "#333", strokeWidth: 1.5 },
        animated: false,
      });

      place(child, childX, y + LEVEL_H);
      cx += cw + NODE_GAP;
    }
  }

  place(root, 400, 0);
  return { nodes, edges };
}

export function MindMap() {
  const rootNode = useStore((s) => s.rootNode);
  const selectedNodeId = useStore((s) => s.selectedNodeId);
  const selectNode = useStore((s) => s.selectNode);
  const reparentNode = useStore((s) => s.reparentNode);
  const highlightedNodeIds = useStore((s) => s.highlightedNodeIds);

  const { flowNodes, flowEdges } = useMemo(() => {
    if (!rootNode) return { flowNodes: [], flowEdges: [] };
    const { nodes, edges } = treeToFlow(rootNode, selectedNodeId, highlightedNodeIds);
    return { flowNodes: nodes, flowEdges: edges };
  }, [rootNode, selectedNodeId, highlightedNodeIds]);

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

  const onPaneClick = useCallback(() => {
    selectNode(null);
  }, [selectNode]);

  const onConnect = useCallback(
    (connection: Connection) => {
      // Drag from source to target = reparent source under target
      if (connection.source && connection.target) {
        reparentNode(connection.source, connection.target);
      }
    },
    [reparentNode]
  );

  if (!rootNode) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        選擇或建立一個專案
      </div>
    );
  }

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={onNodeClick}
      onPaneClick={onPaneClick}
      onConnect={onConnect}
      nodeTypes={nodeTypes}
      fitView
      minZoom={0.2}
      maxZoom={2}
      defaultViewport={{ x: 0, y: 0, zoom: 0.8 }}
    >
      <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#222" />
      <Controls />
      <MiniMap
        nodeColor={(n) => {
          const d = n.data as Record<string, unknown>;
          return d?.isSelected ? "#3b82f6" : d?.isHighlighted ? "#f59e0b" : "#333";
        }}
        maskColor="rgba(0,0,0,0.7)"
      />
    </ReactFlow>
  );
}
