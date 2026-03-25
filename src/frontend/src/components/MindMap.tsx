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
  BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { GrowthNode } from "./GrowthNode";
import type { GNode, Maturity } from "@/lib/types";
import { useStore } from "@/stores/useStore";

const nodeTypes = { growth: GrowthNode };

// Convert tree to React Flow nodes/edges with auto-layout
function treeToFlow(
  root: GNode,
  selectedId: string | null
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  const NODE_W = 220;
  const NODE_GAP = 40;
  const LEVEL_H = 150;

  // First pass: calculate subtree width for each node
  function calcWidth(node: GNode): number {
    const children = node.children || [];
    if (children.length === 0) return NODE_W;
    const childrenWidth = children.reduce((sum, c) => sum + calcWidth(c), 0);
    return childrenWidth + (children.length - 1) * NODE_GAP;
  }

  // Second pass: place nodes
  function place(node: GNode, x: number, y: number) {
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
        style: { stroke: "#333", strokeWidth: 1.5 },
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

  const { flowNodes, flowEdges } = useMemo(() => {
    if (!rootNode) return { flowNodes: [], flowEdges: [] };
    const { nodes, edges } = treeToFlow(rootNode, selectedNodeId);
    return { flowNodes: nodes, flowEdges: edges };
  }, [rootNode, selectedNodeId]);

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
          return d?.isSelected ? "#3b82f6" : "#333";
        }}
        maskColor="rgba(0,0,0,0.7)"
      />
    </ReactFlow>
  );
}
