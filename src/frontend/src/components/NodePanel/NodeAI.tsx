"use client";

import type { Dispatch, SetStateAction } from "react";
import {
  GROWTH_MODE_HELP,
  GROWTH_MODE_LABELS,
  NODE_TYPE_ICONS,
  type GNode,
  type GrowthMode,
} from "@/lib/types";

interface NodeAIProps {
  selectedNode: GNode;
  aiInstruction: string;
  setAiInstruction: Dispatch<SetStateAction<string>>;
  aiMode: GrowthMode;
  setAiMode: Dispatch<SetStateAction<GrowthMode>>;
  aiLoading: boolean;
  expandNode: (nodeId: string, instruction?: string, mode?: GrowthMode) => Promise<void>;
  deepenNode: (nodeId: string, instruction?: string) => Promise<void>;
  expandSuggestions: { title: string; summary: string; node_type: string }[] | null;
  acceptSuggestion: (index: number) => Promise<void>;
  acceptAllSuggestions: () => Promise<void>;
  deepenResult: { enriched_summary: string; content_blocks: { title: string; body: string; block_type: string }[]; target_node_id: string } | null;
  acceptDeepen: () => Promise<void>;
  dismissAI: () => void;
  Section: (props: { title: string; subtitle?: string; tone?: "neutral" | "ai" | "edit"; children: React.ReactNode }) => React.JSX.Element;
}

export function NodeAI({
  selectedNode,
  aiInstruction,
  setAiInstruction,
  aiMode,
  setAiMode,
  aiLoading,
  expandNode,
  deepenNode,
  expandSuggestions,
  acceptSuggestion,
  acceptAllSuggestions,
  deepenResult,
  acceptDeepen,
  dismissAI,
  Section,
}: NodeAIProps) {
  return (
    <>
      <Section title="AI 生長" subtitle="切換模式，避免所有衍生結果都走同一種形狀。" tone="ai">
        <div className="bg-gray-900/70 border border-gray-800 rounded-lg p-2.5 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] text-gray-500">生長模式</span>
            <select
              value={aiMode}
              onChange={(e) => setAiMode(e.target.value as GrowthMode)}
              className="bg-gray-950 border border-gray-700 rounded px-2 py-1 text-[11px] text-gray-200"
            >
              {Object.entries(GROWTH_MODE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
          <p className="text-[11px] text-gray-600">{GROWTH_MODE_HELP[aiMode]}</p>
        </div>
        <input
          value={aiInstruction}
          onChange={(e) => setAiInstruction(e.target.value)}
          placeholder="可選：給 AI 的指示..."
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-300 placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
        />
        <div className="flex gap-2">
          <button
            onClick={() => expandNode(selectedNode.id, aiInstruction || undefined, aiMode)}
            disabled={aiLoading}
            className="flex-1 px-3 py-2 bg-purple-900/60 hover:bg-purple-800 disabled:bg-gray-800 disabled:text-gray-600 text-purple-200 text-xs rounded transition-colors border border-purple-700/50"
          >
            {aiLoading ? "⏳ 生長中..." : "🌱 展開分支"}
          </button>
          <button
            onClick={() => deepenNode(selectedNode.id, aiInstruction || undefined)}
            disabled={aiLoading}
            className="flex-1 px-3 py-2 bg-teal-900/60 hover:bg-teal-800 disabled:bg-gray-800 disabled:text-gray-600 text-teal-200 text-xs rounded transition-colors border border-teal-700/50"
          >
            {aiLoading ? "⏳ 深化中..." : "🔍 深化內容"}
          </button>
        </div>
      </Section>

      {expandSuggestions && expandSuggestions.length > 0 && (
        <Section title="分支建議" subtitle="先挑最有價值的分支採用，不要一次全收進來。" tone="ai">
          <div className="flex items-center justify-between">
            <label className="text-xs text-purple-400 uppercase tracking-wider">🌱 分支建議</label>
            <button onClick={dismissAI} className="text-xs text-gray-500 hover:text-gray-300">✕ 關閉</button>
          </div>
          {expandSuggestions.map((s, i) => (
            <div key={i} className="bg-gray-800/80 border border-purple-800/40 rounded-lg p-3 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-200">
                  {NODE_TYPE_ICONS[s.node_type] || "📌"} {s.title}
                </span>
                <button
                  onClick={() => acceptSuggestion(i)}
                  className="text-xs px-2 py-0.5 bg-green-800 hover:bg-green-700 text-green-200 rounded"
                >
                  ✓ 採用
                </button>
              </div>
              <p className="text-xs text-gray-400">{s.summary}</p>
              <span className="text-[10px] text-gray-600">{s.node_type}</span>
            </div>
          ))}
          <button
            onClick={acceptAllSuggestions}
            className="w-full text-xs py-1.5 bg-green-900/40 hover:bg-green-800/60 text-green-300 rounded border border-green-700/30"
          >
            ✓ 全部採用
          </button>
        </Section>
      )}

      {deepenResult && (
        <Section title="深化建議" subtitle="AI 先補內文骨架，再由你決定是否正式寫入。" tone="ai">
          <div className="flex items-center justify-between">
            <label className="text-xs text-teal-400 uppercase tracking-wider">🔍 深化建議</label>
            <button onClick={dismissAI} className="text-xs text-gray-500 hover:text-gray-300">✕ 關閉</button>
          </div>
          <div className="bg-gray-800/80 border border-teal-800/40 rounded-lg p-3 space-y-2">
            <div>
              <span className="text-[10px] text-gray-500 uppercase">更新摘要</span>
              <p className="text-sm text-gray-200 mt-0.5">{deepenResult.enriched_summary}</p>
            </div>
            {deepenResult.content_blocks.map((block, i) => (
              <div key={i} className="border-t border-gray-700 pt-2">
                <span className="text-[10px] text-teal-500">{block.block_type}</span>
                <p className="text-xs text-gray-300 font-medium">{block.title}</p>
                <p className="text-xs text-gray-400 mt-0.5 whitespace-pre-wrap">{block.body}</p>
              </div>
            ))}
          </div>
          <button
            onClick={acceptDeepen}
            className="w-full text-xs py-1.5 bg-teal-900/40 hover:bg-teal-800/60 text-teal-300 rounded border border-teal-700/30"
          >
            ✓ 接受深化
          </button>
        </Section>
      )}
    </>
  );
}
