"use client";

import type { Dispatch, SetStateAction } from "react";
import { MATURITY_COLORS, MATURITY_LABELS, NODE_TYPE_ICONS, type GNode, type Maturity } from "@/lib/types";

interface NodeHeaderProps {
  selectedNode: GNode;
  maturity: Maturity;
  lineagePath: { id: string; title: string }[];
  isRootNode: boolean;
  editing: boolean;
  editTitle: string;
  setEditTitle: Dispatch<SetStateAction<string>>;
}

export function NodeHeader({
  selectedNode,
  maturity,
  lineagePath,
  isRootNode,
  editing,
  editTitle,
  setEditTitle,
}: NodeHeaderProps) {
  const maturityColor = MATURITY_COLORS[maturity] || "#666";
  const maturityLabel = MATURITY_LABELS[maturity] || maturity;
  const icon = NODE_TYPE_ICONS[selectedNode.node_type] || "📌";

  return (
    <div className="px-3 py-2 border-b border-[var(--border)] bg-[var(--bg-panel)]/50 space-y-1">
      <div className="flex items-center gap-2">
        <span className="text-sm">{icon}</span>
        {editing ? (
          <input
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            className="flex-1 rounded px-2 py-0.5 text-xs text-[var(--text-primary)] surface-subtle"
          />
        ) : (
          <h2 className="text-sm font-semibold text-[var(--text-primary)] flex-1 truncate">
            {selectedNode.title}
          </h2>
        )}
        <span
          className="text-[11px] px-1.5 py-0.5 rounded-full border"
          style={{ borderColor: maturityColor, color: maturityColor }}
        >
          {maturityLabel}
        </span>
      </div>
      <div className="text-[11px] text-[var(--text-faint)] truncate">
        {selectedNode.node_type} · {isRootNode ? "主線根" : "主線分支"} · 主線脈絡：{lineagePath.map((node) => node.title).join(" / ")}
      </div>
    </div>
  );
}
