"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { MATURITY_COLORS, NODE_TYPE_ICONS, type Maturity } from "@/lib/types";

interface GrowthNodeData {
  label: string;
  nodeType: string;
  maturity: Maturity;
  summary: string;
  isSelected: boolean;
  childCount: number;
}

function GrowthNodeComponent({ data }: NodeProps) {
  const d = data as unknown as GrowthNodeData;
  const color = MATURITY_COLORS[d.maturity] || "#666";
  const icon = NODE_TYPE_ICONS[d.nodeType] || "📌";

  return (
    <div
      className="relative px-4 py-3 rounded-lg border-2 min-w-[160px] max-w-[240px] cursor-pointer transition-all duration-200"
      style={{
        background: d.isSelected ? "#1e293b" : "#141414",
        borderColor: d.isSelected ? color : "#2a2a2a",
        boxShadow: d.isSelected ? `0 0 12px ${color}40` : "none",
      }}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-600 !w-2 !h-2" />

      {/* Maturity dot */}
      <div
        className="absolute top-2 right-2 w-2.5 h-2.5 rounded-full"
        style={{ background: color }}
        title={d.maturity}
      />

      {/* Title */}
      <div className="text-sm font-medium text-gray-100 flex items-center gap-1.5">
        <span>{icon}</span>
        <span className="truncate">{d.label}</span>
      </div>

      {/* Summary */}
      {d.summary && (
        <div className="text-xs text-gray-400 mt-1 line-clamp-2">{d.summary}</div>
      )}

      {/* Child count badge */}
      {d.childCount > 0 && (
        <div className="absolute -bottom-1 right-2 text-[10px] text-gray-500 bg-gray-800 px-1.5 rounded-full border border-gray-700">
          {d.childCount}
        </div>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-gray-600 !w-2 !h-2" />
    </div>
  );
}

export const GrowthNode = memo(GrowthNodeComponent);
