"use client";

import type { Dispatch, SetStateAction } from "react";
import { MATURITY_COLORS, NODE_TYPE_ICONS, type GNode, type Maturity } from "@/lib/types";
import { useI18n } from "@/i18n/provider";
import { msg } from "@/i18n/ui";

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
  const { locale } = useI18n();
  const m = (tw: string, cn: string, en: string) => msg(locale, {"zh-TW":tw,"zh-CN":cn,en});
  const maturityColor = MATURITY_COLORS[maturity] || "#666";
  const maturityLabel = ({ seed: m("🌱 種子", "🌱 种子", "🌱 Seed"), rough: m("🪨 粗胚", "🪨 雏形", "🪨 Rough"), developing: m("🔧 發展中", "🔧 发展中", "🔧 Developing"), stable: m("✅ 穩定", "✅ 稳定", "✅ Stable"), finalized: m("🔒 定稿", "🔒 定稿", "🔒 Finalized") } as Record<string,string>)[maturity] || maturity;
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
        {selectedNode.node_type} · {isRootNode ? m("主線根", "主线根", "Main root") : m("主線分支", "主线分支", "Main branch")} · {m("主線脈絡", "主线上下文", "Main lineage")}: {lineagePath.map((node) => node.title).join(" / ")}
      </div>
    </div>
  );
}
