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
  isMainline: boolean;
  isHighlighted?: boolean;
  heatColor?: string;
  isBranch?: boolean;
  updatedAt?: string;
}

function GrowthNodeComponent({ data }: NodeProps) {
  const d = data as unknown as GrowthNodeData;
  const maturityColor = MATURITY_COLORS[d.maturity] || "#666";
  const effectiveColor = d.isSelected ? maturityColor : d.heatColor || maturityColor;
  const icon = NODE_TYPE_ICONS[d.nodeType] || "📌";

  return (
    <div
      className="relative px-5 py-4 rounded-lg border-2 min-w-[180px] max-w-[280px] cursor-pointer transition-all duration-200"
      style={{
        background: d.isSelected
          ? "#1e293b"
          : d.isMainline
          ? "#172554"
          : d.isBranch
          ? "#1a1228"
          : "#141414",
        borderColor: d.isSelected
          ? maturityColor
          : d.isHighlighted
          ? "#f59e0b"
          : d.isBranch
          ? "#7c3aed"
          : d.heatColor
          ? d.heatColor
          : d.isMainline
          ? "#60a5fa"
          : "#2a2a2a",
        borderStyle: d.isBranch ? "dashed" : "solid",
        boxShadow: d.isSelected
          ? `0 0 12px ${maturityColor}40`
          : d.isHighlighted
          ? "0 0 12px rgba(245,158,11,0.5)"
          : d.heatColor
          ? `0 0 6px ${d.heatColor}30`
          : d.isMainline
          ? "0 0 0 1px rgba(96,165,250,0.35)"
          : "none",
      }}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-600 !w-2 !h-2" />

      {/* Maturity dot */}
      <div
        className="absolute top-2 right-2 w-2.5 h-2.5 rounded-full"
        style={{ background: d.heatColor || maturityColor }}
        title={d.maturity}
      />

      {/* Branch badge */}
      {d.isBranch && (
        <div className="absolute top-2 left-2 text-[9px] text-purple-300 border border-purple-700/50 rounded-full px-1.5 bg-purple-950/60">
          分支
        </div>
      )}

      {/* Title */}
      <div className={`text-base font-medium text-gray-100 flex items-center gap-1.5 ${d.isBranch ? "mt-3" : ""}`}>
        <span>{icon}</span>
        <span className="truncate">{d.label}</span>
        {d.isMainline && !d.isBranch && (
          <span className="text-[10px] text-blue-300 border border-blue-500/40 rounded-full px-1.5 py-0.5">MAIN</span>
        )}
      </div>

      {/* Summary */}
      {d.summary && (
        <div className="text-sm text-gray-400 mt-1 line-clamp-2">{d.summary}</div>
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
