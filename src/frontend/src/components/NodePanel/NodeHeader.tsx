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
    <div className="p-4 border-b border-[var(--border)] bg-[var(--bg-panel)]/55">
      <div className="eyebrow-label mb-2">Selected node</div>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">{icon}</span>
        {editing ? (
          <input
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            className="flex-1 rounded px-2 py-1 text-sm text-[var(--text-primary)] surface-subtle"
          />
        ) : (
          <h2 className="text-base font-semibold text-[var(--text-primary)] flex-1 truncate">
            {selectedNode.title}
          </h2>
        )}
      </div>
      <div className="flex items-center gap-2">
        <span
          className="text-xs px-2 py-0.5 rounded-full border"
          style={{ borderColor: maturityColor, color: maturityColor }}
        >
          {maturityLabel}
        </span>
        <span className="text-xs text-[var(--text-faint)]">{selectedNode.node_type}</span>
      </div>
      <div className="mt-4 rounded-xl surface-subtle p-3">
        <div className="eyebrow-label">主線脈絡</div>
        <div className="flex flex-wrap gap-1.5 mt-1">
          {lineagePath.map((node) => (
            <span
              key={node.id}
              className={`text-[11px] px-2 py-1 rounded-full border ${node.id === selectedNode.id ? "text-blue-200 border-blue-700/60 bg-blue-950/40" : "text-gray-400 border-gray-700 bg-gray-900/80"}`}
            >
              {node.title}
            </span>
          ))}
        </div>
         <p className="text-[11px] text-[var(--text-faint)] mt-2">
           {isRootNode ? "目前位於主線根節點。" : "先看主線脈絡，再決定要補強、延伸或挑戰這條分支。"}
         </p>
      </div>
    </div>
  );
}
