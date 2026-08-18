"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type Dispatch, type SetStateAction } from "react";
import {
  NODE_TYPE_ICONS,
  type GNode,
  type GrowthMode,
} from "@/lib/types";
import { loadLLMConfig, saveLLMConfig, type LLMProviderType } from "@/lib/llm-provider";
import { api } from "@/lib/api";
import { createAIPanelController, diagnosticMessage, MAX_MODEL_NAME, providerIdentity, type AIProviderIdentity } from "@/lib/ai-panel-controller";
import { mountAIPanelLifecycle } from "@/lib/ai-panel-lifecycle";
import type { ProviderConfig } from "@/lib/types";
import { providerActionDisabled } from "@/lib/provider-pending";
import { useI18n } from "@/i18n/provider";
import { msg } from "@/i18n/ui";


interface NodeAIProps {
  selectedNode: GNode;
  aiInstruction: string;
  setAiInstruction: Dispatch<SetStateAction<string>>;
  aiMode: GrowthMode;
  setAiMode: Dispatch<SetStateAction<GrowthMode>>;
  aiLoading: boolean;
  aiError: { code?: string; status?: number; requestId?: string; message: string; action: "expand" | "deepen"; elapsedMs: number } | null;
  clearAIError: () => void;
  invalidateAISelection: () => void;
  expandNode: (nodeId: string, identity: AIProviderIdentity, instruction?: string, mode?: GrowthMode) => Promise<void>;
  deepenNode: (nodeId: string, identity: AIProviderIdentity, instruction?: string) => Promise<void>;
  expandSuggestions: { title: string; summary: string; node_type: string }[] | null;
  acceptSuggestion: (index: number) => Promise<void>;
  ignoreSuggestion: (index: number) => void;
  acceptAllSuggestions: () => Promise<void>;
  deepenResult: { enriched_summary: string; content_blocks: { title: string; body: string; block_type: string }[]; target_node_id: string } | null;
  acceptDeepen: () => Promise<void>;
  acceptDeepenSummary: () => Promise<unknown>;
  acceptDeepenBlock: (index: number) => Promise<unknown>;
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
  aiError,
  clearAIError,
  invalidateAISelection,
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
  const [modelDraft, setModelDraft] = useState(""); const [elapsed, setElapsed] = useState(0);
  const selectedRef = useRef<ProviderConfig | undefined>(undefined); const localeRef=useRef(locale);localeRef.current=locale;
  const controllerRef=useRef<ReturnType<typeof createAIPanelController>|null>(null);
  if(!controllerRef.current)controllerRef.current=createAIPanelController({listProviders:api.listProviders,updateModel:api.updateProviderModel,testConnection:api.testConnection,confirm:(text)=>confirm(text),copy:(text)=>navigator.clipboard.writeText(text),now:()=>Date.now(),locale:()=>localeRef.current,currentIdentity:()=>selectedRef.current?providerIdentity(selectedRef.current):null,onSaved:(p)=>{const next={provider:p.provider_type as LLMProviderType,providerId:p.id,model:p.model_name,revision:p.revision};setLlmConfig(next);saveLLMConfig(next);setModelDraft(p.model_name)},onInvalidate:invalidateAISelection});
  const controller=controllerRef.current;const panel=useSyncExternalStore(controller.subscribe,controller.getSnapshot,controller.getSnapshot);const profiles=panel.profiles,profileState=panel.profileState,savingModel=panel.saving,modelError=panel.modelError,testState=panel.test;
  const selectedProfile=profiles.find(p=>p.id===llmConfig?.providerId);selectedRef.current=selectedProfile;const providerDisabled=providerActionDisabled(selectedProfile);const currentIdentity=()=>selectedProfile?providerIdentity(selectedProfile):null;
  const invalidateTest=()=>controller.invalidate();const loadProfiles=()=>{void controller.list()};
  // Controller and parent invalidator are intentionally captured for this mount.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(()=>mountAIPanelLifecycle({controller,target:window,loadProfiles,refresh:()=>{setLlmConfig(loadLLMConfig());controller.invalidate();invalidateAISelection()}}),[]);
  useEffect(()=>{setModelDraft(selectedProfile?.model_name||"");controller.invalidate()},[selectedProfile?.id,selectedProfile?.model_name,controller]);
  useEffect(()=>{if(!selectedProfile||!llmConfig)return;const authoritative=providerIdentity(selectedProfile);if(llmConfig.providerId===authoritative.providerId&&llmConfig.provider===authoritative.providerType&&llmConfig.model===authoritative.model&&llmConfig.revision!==authoritative.revision){const next={provider:authoritative.providerType,providerId:authoritative.providerId,model:authoritative.model,revision:authoritative.revision};setLlmConfig(next);saveLLMConfig(next)}},[selectedProfile,llmConfig]);
  useEffect(()=>{if(!aiLoading&&testState?.kind!=="testing"){setElapsed(0);return}const started=Date.now(),timer=setInterval(()=>setElapsed(Math.floor((Date.now()-started)/1000)),1000);return()=>clearInterval(timer)},[aiLoading,testState?.kind]);
  const selectProvider=(id:string)=>{const p=profiles.find(x=>x.id===id);if(!p)return;controller.invalidate();const next={provider:p.provider_type as LLMProviderType,providerId:p.id,model:p.model_name,revision:p.revision};saveLLMConfig(next);setLlmConfig(next);setModelDraft(p.model_name);invalidateAISelection()};const saveModel=()=>{void controller.save(modelDraft)};const testConnection=()=>{void controller.test()};


  const aiProvider = llmConfig?.provider || "mock";
  const isMockProvider = aiProvider === "mock";
  const costHint = isMockProvider ? m("Mock 模式不會呼叫外部 API。","Mock 模式不会调用外部 API。","Mock mode does not call an external API.") : m("真模型模式：每次展開/深化可能消耗 API 額度。","真实模型模式：每次展开或深化都可能消耗 API 配额。","Live-model mode: each expand or deepen action may consume API quota.");

  const savedIdentity=()=>{const x=loadLLMConfig();return x?{providerId:x.providerId,providerType:x.provider,model:x.model,revision:x.revision}:null};
  const handleExpand=()=>{const identity=currentIdentity();if(!identity||!selectedProfile)return;controller.generate({actionLabel:m("展開分支","展开分支","Expand branch"),profileName:selectedProfile.name,identity,savedIdentity,dispatch:()=>{void expandNode(selectedNode.id,identity,aiInstruction||undefined,aiMode)}})};
  const handleDeepen=()=>{const identity=currentIdentity();if(!identity||!selectedProfile)return;controller.generate({actionLabel:m("深化內容","深化内容","Deepen content"),profileName:selectedProfile.name,identity,savedIdentity,dispatch:()=>{void deepenNode(selectedNode.id,identity,aiInstruction||undefined)}})};

  return (
    <>
      <Section title={m("AI 生長","AI 生长","AI growth")} subtitle={m("切換模式，避免所有衍生結果都走同一種形狀。","切换模式，避免所有衍生结果采用相同结构。","Switch modes so generated results do not all follow the same shape.")} tone="ai">
        <div className={`rounded-lg border px-3 py-2 text-xs leading-5 ${isMockProvider ? "border-green-800/40 bg-green-950/20 text-green-200/80" : "border-amber-800/40 bg-amber-950/20 text-amber-200/80"}`}>
          <label className="block font-medium">{m("AI 設定檔","AI 配置","AI profile")}</label>
          <select aria-label={m("AI 設定檔","AI 配置","AI profile")} value={selectedProfile?.id || ""} onChange={(e)=>selectProvider(e.target.value)} disabled={aiLoading || testState?.kind==="testing"} className="w-full rounded bg-gray-900 px-2 py-1">
            <option value="">{m("選擇可用設定檔…","选择可用配置…","Select an enabled profile…")}</option>
            {profiles.map((p)=><option key={p.id} value={p.id}>{p.name} · {p.provider_type} · {p.model_name}</option>)}
          </select>
          <div className="mt-2 flex gap-2"><input aria-label={m("模型","模型","Model")} value={modelDraft} maxLength={MAX_MODEL_NAME} onChange={(e)=>{setModelDraft(e.target.value);invalidateTest();invalidateAISelection();}} disabled={providerDisabled || savingModel || aiLoading} className="min-w-0 flex-1 rounded bg-gray-900 px-2 py-1"/><button type="button" onClick={saveModel} disabled={providerDisabled || savingModel || !modelDraft.trim() || modelDraft.trim()===selectedProfile?.model_name} className="rounded border px-2">{m("儲存模型","保存模型","Save model")}</button><button type="button" onClick={testConnection} disabled={providerDisabled || testState?.kind==="testing" || modelDraft.trim()!==selectedProfile?.model_name} className="rounded border px-2">{testState?.kind==="testing"?m("測試中","测试中","Testing"):m("測試","测试","Test")}</button></div>
          {(modelError||panel.copyMessage||panel.generationError) && <div role="alert" className="text-red-300">{modelError||panel.copyMessage||panel.generationError}</div>}
          {modelDraft.trim()!==selectedProfile?.model_name && <div className="text-amber-300">{m("模型尚未儲存；後端仍使用已儲存模型。","模型尚未保存；后端仍使用已保存模型。","Unsaved model; the backend still uses the saved model.")}</div>}
          <div>{costHint}</div>
          {testState && <div className="mt-1" role="status">{testState.kind.toUpperCase()} · {testState.kind==="testing"?elapsed:Math.ceil(testState.elapsed/1000)}s · {testState.message}{testState.status?` · HTTP ${testState.status}`:""}{testState.code?` · ${testState.code}`:""}{testState.requestId?` · ID ${testState.requestId}`:""}</div>}
        </div>
        {profileState==="loading" && <div role="status" className="text-xs">{m("載入設定檔…","加载配置…","Loading profiles…")}</div>}
        {profileState==="error" && <div role="alert" className="rounded border border-red-800 p-2 text-xs text-red-300">{m("無法載入設定檔。","无法加载配置。","Could not load profiles.")} <button type="button" className="underline" onClick={loadProfiles}>{m("重試","重试","Retry")}</button></div>}
        {profileState==="ready" && profiles.length===0 && <div role="status" className="text-xs">{m("沒有已啟用的設定檔。","没有已启用的配置。","No enabled profiles.")}</div>}
        {profileState==="ready" && profiles.length>0 && !selectedProfile && <div role="alert" className="rounded border border-red-800 p-2 text-xs text-red-300">{m("所選設定檔不存在或已停用，請選擇可用設定檔。","所选配置不存在或已停用，请选择可用配置。","The selected profile is missing or disabled. Select an enabled profile.")}</div>}
        {(aiLoading || testState?.kind==="testing") && <div role="status" className="text-xs text-purple-200">{m("等待 AI 回應","等待 AI 响应","Waiting for AI")} · {elapsed}s · {m("最多約 62 秒，不顯示虛假進度。","最长约 62 秒，不显示虚假进度。","Maximum wait about 62 seconds; no artificial progress.")}</div>}
        {aiError && <div role="alert" className="rounded border border-red-800 bg-red-950/20 p-2 text-xs text-red-200"><div>{diagnosticMessage(locale,aiError.code)}</div><div>HTTP {aiError.status || "—"} · {aiError.code || "LLM_UPSTREAM_ERROR"}{aiError.requestId?` · ID ${aiError.requestId}`:""} · {Math.ceil(aiError.elapsedMs/1000)}s</div>{aiError.requestId && <button type="button" className="underline" onClick={()=>void controller.copy(aiError.requestId!)}>{m("複製請求 ID","复制请求 ID","Copy request ID")}</button>}<button type="button" onClick={clearAIError} className="underline">{m("關閉；請重試相同操作","关闭；请重试相同操作","Dismiss; retry the same action")}</button></div>}

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
            disabled={aiLoading || providerDisabled || modelDraft.trim()!==selectedProfile?.model_name}
            className="flex-1 px-3 py-2 bg-purple-900/60 hover:bg-purple-800 disabled:bg-gray-800 disabled:text-gray-600 text-purple-200 text-sm rounded-lg transition-colors border border-purple-700/50"
          >
            {aiLoading ? m("⏳ 生長中…","⏳ 生长中…","⏳ Growing…") : m("🌱 展開分支","🌱 展开分支","🌱 Expand branch")}
          </button>
          <button
            type="button"
            onClick={handleDeepen}
            disabled={aiLoading || providerDisabled || modelDraft.trim()!==selectedProfile?.model_name}
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
