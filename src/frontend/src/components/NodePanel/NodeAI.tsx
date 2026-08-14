"use client";

import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import {
  NODE_TYPE_ICONS,
  type GNode,
  type GrowthMode,
} from "@/lib/types";
import { DEFAULT_MODELS, loadLLMConfig } from "@/lib/llm-provider";
import { useI18n } from "@/i18n/provider";
import { msg } from "@/i18n/ui";

const PROVIDER_LABELS: Record<string, string> = {
  mock: "Mock / Demo",
  openai_compatible: "OpenAI-compatible",
  custom: "Custom Endpoint",
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google Gemini",
  openclaw: "OpenClaw",
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
  const { locale } = useI18n();
  const m = (tw: string, cn: string, en: string) => msg(locale, {"zh-TW":tw,"zh-CN":cn,en});
  const growthLabels: Record<GrowthMode,string>={focused:m("聚焦主線","聚焦主线","Focus main line"),explore:m("探索延伸","探索延伸","Explore outward"),challenge:m("挑戰假設","挑战假设","Challenge assumptions")};
  const growthHelp: Record<GrowthMode,string>={focused:m("補齊當前主線缺口，避免一次跳太遠。","补齐当前主线缺口，避免偏离过远。","Fill gaps in the main line without jumping too far."),explore:m("沿著主題向相鄰空間擴張。","沿主题向相邻空间扩展。","Expand into adjacent areas of the topic."),challenge:m("提出反例、風險與替代方向。","提出反例、风险与替代方向。","Surface counterexamples, risks, and alternatives.")};
  const nodeTypeLabels: Record<string,string> = { idea:m("想法","想法","Idea"), concept:m("概念","概念","Concept"), task:m("任務","任务","Task"), question:m("問題","问题","Question"), decision:m("決策","决策","Decision"), risk:m("風險","风险","Risk"), resource:m("資源","资源","Resource"), note:m("筆記","笔记","Note"), module:m("模組","模块","Module") };
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
  const aiModel = llmConfig?.model || DEFAULT_MODELS[aiProvider] || m("未設定","未设置","Not set");
  const isMockProvider = aiProvider === "mock";
  const costHint = isMockProvider ? m("Mock 模式不會呼叫外部 API。","Mock 模式不会调用外部 API。","Mock mode does not call an external API.") : m("真模型模式：每次展開/深化可能消耗 API 額度。","真实模型模式：每次展开或深化都可能消耗 API 配额。","Live-model mode: each expand or deepen action may consume API quota.");

  const confirmRealModel = (action: string) => {
    if (isMockProvider) return true;
    return confirm(`${m("目前使用真模型 provider", "当前使用真实模型 provider", "A live-model provider is active")} (${PROVIDER_LABELS[aiProvider] || aiProvider} / ${aiModel}).\n\n${action} — ${m("可能消耗 API 額度，是否繼續？", "可能消耗 API 配额，是否继续？", "This may consume API quota. Continue?")}`);
  };

  const handleExpand = () => {
    if (!confirmRealModel(m("展開分支","展开分支","Expand branch"))) return;
    expandNode(selectedNode.id, aiInstruction || undefined, aiMode);
  };

  const handleDeepen = () => {
    if (!confirmRealModel(m("深化內容","深化内容","Deepen content"))) return;
    deepenNode(selectedNode.id, aiInstruction || undefined);
  };

  return (
    <>
      <Section title={m("AI 生長","AI 生长","AI growth")} subtitle={m("切換模式，避免所有衍生結果都走同一種形狀。","切换模式，避免所有衍生结果采用相同结构。","Switch modes so generated results do not all follow the same shape.")} tone="ai">
        <div className={`rounded-lg border px-3 py-2 text-xs leading-5 ${isMockProvider ? "border-green-800/40 bg-green-950/20 text-green-200/80" : "border-amber-800/40 bg-amber-950/20 text-amber-200/80"}`}>
          <div className="font-medium">
            {m("目前 AI","当前 AI","Current AI")}:{PROVIDER_LABELS[aiProvider] || aiProvider} / {aiModel}
          </div>
          <div>{costHint}</div>
        </div>

        <div className="surface-subtle rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="eyebrow-label">{m("生長模式","生长模式","Growth mode")}</span>
            <select
              value={aiMode}
              onChange={(e) => setAiMode(e.target.value as GrowthMode)}
              className="rounded px-2 py-1 text-xs text-[var(--text-primary)] surface-subtle"
            >
              {Object.entries(growthLabels).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
          <p className="text-xs text-[var(--text-faint)]">{growthHelp[aiMode]}</p>
        </div>
        <input
          value={aiInstruction}
          onChange={(e) => setAiInstruction(e.target.value)}
          placeholder={m("可選：給 AI 的指示…","可选：给 AI 的指令…","Optional: instructions for AI…")}
          className="w-full surface-subtle rounded px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-faint)] focus:border-blue-500 focus:outline-none"
        />
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleExpand}
            disabled={aiLoading}
            className="flex-1 px-3 py-2 bg-purple-900/60 hover:bg-purple-800 disabled:bg-gray-800 disabled:text-gray-600 text-purple-200 text-sm rounded-lg transition-colors border border-purple-700/50"
          >
            {aiLoading ? m("⏳ 生長中…","⏳ 生长中…","⏳ Growing…") : m("🌱 展開分支","🌱 展开分支","🌱 Expand branch")}
          </button>
          <button
            type="button"
            onClick={handleDeepen}
            disabled={aiLoading}
            className="flex-1 px-3 py-2 bg-teal-900/60 hover:bg-teal-800 disabled:bg-gray-800 disabled:text-gray-600 text-teal-200 text-sm rounded-lg transition-colors border border-teal-700/50"
          >
            {aiLoading ? m("⏳ 深化中…","⏳ 深化中…","⏳ Deepening…") : m("🔍 深化內容","🔍 深化内容","🔍 Deepen content")}
          </button>
        </div>
      </Section>

      {expandSuggestions && expandSuggestions.length > 0 && (
        <Section title={m("分支建議","分支建议","Branch suggestions")} subtitle={m("先挑最有價值的分支採用，不要一次全收進來。","先采用最有价值的分支，不必一次全部接受。","Choose the most valuable branches instead of accepting everything at once.")} tone="ai">
          <div className="flex items-center justify-between">
            <div className="eyebrow-label text-purple-300">🌱 {m("分支建議","分支建议","Branch suggestions")}</div>
            <button type="button" onClick={dismissAI} className="text-sm text-[var(--text-faint)] hover:text-[var(--text-primary)]">✕ {m("關閉","关闭","Close")}</button>
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
                    ✓ {m("採用","采用","Accept")}
                  </button>
                  <button
                    type="button"
                    onClick={() => ignoreSuggestion(i)}
                    className="text-sm px-2 py-0.5 border border-gray-700 text-gray-400 hover:text-gray-200 rounded"
                  >
                    {m("忽略","忽略","Ignore")}
                  </button>
                </div>
              </div>
              <p className="text-sm text-gray-400">{s.summary}</p>
              <span className="text-xs text-gray-600">{nodeTypeLabels[s.node_type] || s.node_type}</span>
            </div>
          ))}
          <button
            type="button"
            onClick={acceptAllSuggestions}
            className="w-full text-sm py-1.5 bg-green-900/40 hover:bg-green-800/60 text-green-300 rounded border border-green-700/30"
          >
            ✓ {m("全部採用","全部采用","Accept all")}
          </button>
        </Section>
      )}

      {deepenResult && (
        <Section title={m("深化建議","深化建议","Deepening suggestions")} subtitle={m("AI 先補內文骨架，再由你決定是否正式寫入。","AI 先补充内容结构，再由你决定是否写入。","AI drafts the content structure; you decide what to apply.")} tone="ai">
          <div className="flex items-center justify-between">
            <div className="eyebrow-label text-teal-300">🔍 {m("深化建議","深化建议","Deepening suggestions")}</div>
            <button type="button" onClick={dismissAI} className="text-sm text-[var(--text-faint)] hover:text-[var(--text-primary)]">✕ {m("關閉","关闭","Close")}</button>
          </div>
          <div className="bg-gray-800/80 border border-teal-800/40 rounded-lg p-3 space-y-3">
            <div className="rounded-lg border border-gray-700/70 bg-gray-900/40 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="eyebrow-label">{m("摘要建議","摘要建议","Summary suggestion")}</span>
                <button
                  type="button"
                  onClick={acceptDeepenSummary}
                  className="text-xs px-2 py-1 bg-green-800 hover:bg-green-700 text-green-200 rounded"
                >
                  ✓ {m("套用摘要","应用摘要","Apply summary")}
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
                      ✓ {m("接受","接受","Accept")}
                    </button>
                    <button
                      type="button"
                      onClick={() => ignoreDeepenBlock(index)}
                      className="text-xs px-2 py-1 border border-gray-700 text-gray-400 hover:text-gray-200 rounded"
                    >
                      {m("忽略","忽略","Ignore")}
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
            ✓ {m("全部接受","全部接受","Accept all")}
          </button>
        </Section>
      )}
    </>
  );
}
