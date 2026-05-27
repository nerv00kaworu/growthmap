"use client";

import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import {
  GROWTH_MODE_HELP,
  GROWTH_MODE_LABELS,
  NODE_TYPE_ICONS,
  type GNode,
  type GrowthMode,
} from "@/lib/types";
import { DEFAULT_MODELS, loadLLMConfig } from "@/lib/llm-provider";

const PROVIDER_LABELS: Record<string, string> = {
  mock: "Mock / Demo",
  openai_compatible: "OpenAI-compatible",
  custom: "Custom Endpoint",
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google Gemini",
  openclaw: "OpenClaw",
};

const NODE_TYPE_LABELS: Record<string, string> = {
  idea: "想法",
  concept: "概念",
  task: "任務",
  question: "問題",
  decision: "決策",
  risk: "風險",
  resource: "資源",
  note: "筆記",
  module: "模組",
};

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
  ignoreSuggestion: (index: number) => void;
  acceptAllSuggestions: () => Promise<void>;
  deepenResult: { enriched_summary: string; content_blocks: { title: string; body: string; block_type: string }[]; target_node_id: string } | null;
  acceptDeepen: () => Promise<void>;
  acceptDeepenSummary: () => Promise<void>;
  acceptDeepenBlock: (index: number) => Promise<void>;
  ignoreDeepenBlock: (index: number) => void;
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
  ignoreSuggestion,
  acceptAllSuggestions,
  deepenResult,
  acceptDeepen,
  acceptDeepenSummary,
  acceptDeepenBlock,
  ignoreDeepenBlock,
  dismissAI,
  Section,
}: NodeAIProps) {
  const [llmConfig, setLlmConfig] = useState(() => loadLLMConfig());

  useEffect(() => {
    const refreshConfig = () => setLlmConfig(loadLLMConfig());
    window.addEventListener("storage", refreshConfig);
    window.addEventListener("focus", refreshConfig);
    return () => {
      window.removeEventListener("storage", refreshConfig);
      window.removeEventListener("focus", refreshConfig);
    };
  }, []);

  const aiProvider = llmConfig?.provider || "mock";
  const aiModel = llmConfig?.model || DEFAULT_MODELS[aiProvider] || "未設定";
  const isMockProvider = aiProvider === "mock";
  const costHint = useMemo(() => {
    if (isMockProvider) return "Mock 模式不會呼叫外部 API。";
    return "真模型模式：每次展開/深化可能消耗 API 額度。";
  }, [isMockProvider]);

  const confirmRealModel = (action: string) => {
    if (isMockProvider) return true;
    return confirm(`目前使用真模型 provider（${PROVIDER_LABELS[aiProvider] || aiProvider} / ${aiModel}）。\n\n「${action}」可能消耗 API 額度，是否繼續？`);
  };

  const handleExpand = () => {
    if (!confirmRealModel("展開分支")) return;
    expandNode(selectedNode.id, aiInstruction || undefined, aiMode);
  };

  const handleDeepen = () => {
    if (!confirmRealModel("深化內容")) return;
    deepenNode(selectedNode.id, aiInstruction || undefined);
  };

  return (
    <>
      <Section title="AI 生長" subtitle="切換模式，避免所有衍生結果都走同一種形狀。" tone="ai">
        <div className={`rounded-lg border px-3 py-2 text-xs leading-5 ${isMockProvider ? "border-green-800/40 bg-green-950/20 text-green-200/80" : "border-amber-800/40 bg-amber-950/20 text-amber-200/80"}`}>
          <div className="font-medium">
            目前 AI：{PROVIDER_LABELS[aiProvider] || aiProvider} / {aiModel}
          </div>
          <div>{costHint}</div>
        </div>

        <div className="surface-subtle rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="eyebrow-label">生長模式</span>
            <select
              value={aiMode}
              onChange={(e) => setAiMode(e.target.value as GrowthMode)}
              className="rounded px-2 py-1 text-xs text-[var(--text-primary)] surface-subtle"
            >
              {Object.entries(GROWTH_MODE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
          <p className="text-xs text-[var(--text-faint)]">{GROWTH_MODE_HELP[aiMode]}</p>
        </div>
        <input
          value={aiInstruction}
          onChange={(e) => setAiInstruction(e.target.value)}
          placeholder="可選：給 AI 的指示..."
          className="w-full surface-subtle rounded px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-faint)] focus:border-blue-500 focus:outline-none"
        />
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleExpand}
            disabled={aiLoading}
            className="flex-1 px-3 py-2 bg-purple-900/60 hover:bg-purple-800 disabled:bg-gray-800 disabled:text-gray-600 text-purple-200 text-sm rounded-lg transition-colors border border-purple-700/50"
          >
            {aiLoading ? "⏳ 生長中..." : "🌱 展開分支"}
          </button>
          <button
            type="button"
            onClick={handleDeepen}
            disabled={aiLoading}
            className="flex-1 px-3 py-2 bg-teal-900/60 hover:bg-teal-800 disabled:bg-gray-800 disabled:text-gray-600 text-teal-200 text-sm rounded-lg transition-colors border border-teal-700/50"
          >
            {aiLoading ? "⏳ 深化中..." : "🔍 深化內容"}
          </button>
        </div>
      </Section>

      {expandSuggestions && expandSuggestions.length > 0 && (
        <Section title="分支建議" subtitle="先挑最有價值的分支採用，不要一次全收進來。" tone="ai">
          <div className="flex items-center justify-between">
            <div className="eyebrow-label text-purple-300">🌱 分支建議</div>
            <button type="button" onClick={dismissAI} className="text-sm text-[var(--text-faint)] hover:text-[var(--text-primary)]">✕ 關閉</button>
          </div>
          {expandSuggestions.map((s, i) => (
            <div key={`${s.node_type}-${s.title}`} className="bg-gray-800/80 border border-purple-800/40 rounded-lg p-3 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-base text-gray-200">
                  {NODE_TYPE_ICONS[s.node_type] || "📌"} {s.title}
                </span>
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    onClick={() => acceptSuggestion(i)}
                    className="text-sm px-2 py-0.5 bg-green-800 hover:bg-green-700 text-green-200 rounded"
                  >
                    ✓ 採用
                  </button>
                  <button
                    type="button"
                    onClick={() => ignoreSuggestion(i)}
                    className="text-sm px-2 py-0.5 border border-gray-700 text-gray-400 hover:text-gray-200 rounded"
                  >
                    忽略
                  </button>
                </div>
              </div>
              <p className="text-sm text-gray-400">{s.summary}</p>
              <span className="text-xs text-gray-600">{NODE_TYPE_LABELS[s.node_type] || s.node_type}</span>
            </div>
          ))}
          <button
            type="button"
            onClick={acceptAllSuggestions}
            className="w-full text-sm py-1.5 bg-green-900/40 hover:bg-green-800/60 text-green-300 rounded border border-green-700/30"
          >
            ✓ 全部採用
          </button>
        </Section>
      )}

      {deepenResult && (
        <Section title="深化建議" subtitle="AI 先補內文骨架，再由你決定是否正式寫入。" tone="ai">
          <div className="flex items-center justify-between">
            <div className="eyebrow-label text-teal-300">🔍 深化建議</div>
            <button type="button" onClick={dismissAI} className="text-sm text-[var(--text-faint)] hover:text-[var(--text-primary)]">✕ 關閉</button>
          </div>
          <div className="bg-gray-800/80 border border-teal-800/40 rounded-lg p-3 space-y-3">
            <div className="rounded-lg border border-gray-700/70 bg-gray-900/40 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="eyebrow-label">摘要建議</span>
                <button
                  type="button"
                  onClick={acceptDeepenSummary}
                  className="text-xs px-2 py-1 bg-green-800 hover:bg-green-700 text-green-200 rounded"
                >
                  ✓ 套用摘要
                </button>
              </div>
              <p className="text-base text-[var(--text-primary)] mt-1 whitespace-pre-wrap">{deepenResult.enriched_summary}</p>
            </div>
            {deepenResult.content_blocks.map((block, index) => (
              <div key={`${block.block_type}-${block.title}-${index}`} className="rounded-lg border border-gray-700/70 bg-gray-900/40 p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs text-teal-500">{block.block_type}</span>
                  <div className="flex gap-1.5">
                    <button
                      type="button"
                      onClick={() => acceptDeepenBlock(index)}
                      className="text-xs px-2 py-1 bg-green-800 hover:bg-green-700 text-green-200 rounded"
                    >
                      ✓ 接受
                    </button>
                    <button
                      type="button"
                      onClick={() => ignoreDeepenBlock(index)}
                      className="text-xs px-2 py-1 border border-gray-700 text-gray-400 hover:text-gray-200 rounded"
                    >
                      忽略
                    </button>
                  </div>
                </div>
                <p className="text-sm text-gray-300 font-medium">{block.title}</p>
                <p className="text-sm text-gray-400 mt-0.5 whitespace-pre-wrap">{block.body}</p>
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={acceptDeepen}
            className="w-full text-sm py-1.5 bg-teal-900/40 hover:bg-teal-800/60 text-teal-300 rounded border border-teal-700/30"
          >
            ✓ 全部接受
          </button>
        </Section>
      )}
    </>
  );
}
