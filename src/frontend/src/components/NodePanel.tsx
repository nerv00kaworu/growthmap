"use client";

import { useState } from "react";
import { useStore } from "@/stores/useStore";
import { NodeHeader } from "./NodePanel/NodeHeader";
import { NodeContent } from "./NodePanel/NodeContent";
import { NodeAI } from "./NodePanel/NodeAI";
import { NodeHistorySection } from "./NodePanel/NodeHistory";
import { NodeChat } from "./NodePanel/NodeChat";
import type { GNode, GrowthMode, Maturity } from "@/lib/types";

interface SectionProps {
  title: string;
  subtitle?: string;
  tone?: "neutral" | "ai" | "edit";
  children: React.ReactNode;
}

const Section = ({ title, subtitle, tone = "neutral", children }: SectionProps) => {
  const toneClass = {
    neutral: "surface-subtle",
    ai: "border-purple-900/40 bg-purple-950/20 shadow-[0_0_0_1px_rgba(88,28,135,0.08)]",
    edit: "border-blue-900/40 bg-blue-950/20 shadow-[0_0_0_1px_rgba(30,64,175,0.08)]",
  }[tone];

  return (
    <section className={`rounded-xl border p-5 space-y-3 ${toneClass}`}>
      <div className="space-y-1">
        <div className="eyebrow-label">{title}</div>
        {subtitle && <p className="text-[11px] text-[var(--text-faint)]">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
};

type Tab = "content" | "ai" | "chat" | "history";

export function NodePanel() {
  const selectedNode = useStore((s) => s.selectedNode);
  const rootNode = useStore((s) => s.rootNode);
  const addChildNode = useStore((s) => s.addChildNode);
  const updateNode = useStore((s) => s.updateNode);
  const deleteNode = useStore((s) => s.deleteNode);
  const promoteMainlineChild = useStore((s) => s.promoteMainlineChild);
  const expandNode = useStore((s) => s.expandNode);
  const deepenNode = useStore((s) => s.deepenNode);
  const acceptSuggestion = useStore((s) => s.acceptSuggestion);
  const acceptAllSuggestions = useStore((s) => s.acceptAllSuggestions);
  const acceptDeepen = useStore((s) => s.acceptDeepen);
  const dismissAI = useStore((s) => s.dismissAI);
  const expandSuggestions = useStore((s) => s.expandSuggestions);
  const deepenResult = useStore((s) => s.deepenResult);
  const aiLoading = useStore((s) => s.aiLoading);
  const refreshTree = useStore((s) => s.refreshTree);

  const [activeTab, setActiveTab] = useState<Tab>("content");
  const [newChildTitle, setNewChildTitle] = useState("");
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editSummary, setEditSummary] = useState("");
  const [aiInstruction, setAiInstruction] = useState("");
  const [aiMode, setAiMode] = useState<GrowthMode>("explore");

  if (!selectedNode) {
    return (
      <div className="h-full flex items-center justify-center text-[var(--text-faint)] text-sm p-6">
        <div className="text-center">
          <div className="text-4xl mb-3">🌳</div>
          <div>點擊節點查看詳情</div>
        </div>
      </div>
    );
  }

  const maturity = selectedNode.maturity as Maturity;
  const lineagePath = [...(selectedNode.ancestor_path || []), { id: selectedNode.id, title: selectedNode.title }];
  const isRootNode = rootNode?.id === selectedNode.id;

  const handleAddChild = async (nodeType?: string) => {
    if (!newChildTitle.trim()) return;
    await addChildNode(selectedNode.id, newChildTitle.trim(), nodeType);
    setNewChildTitle("");
  };

  const startEdit = () => {
    setEditTitle(selectedNode.title);
    setEditSummary(selectedNode.summary || "");
    setEditing(true);
  };

  const saveEdit = async () => {
    await updateNode(selectedNode.id, { title: editTitle, summary: editSummary });
    setEditing(false);
  };

  const TABS: { key: Tab; label: string }[] = [
    { key: "content", label: "內容" },
    { key: "ai", label: "AI" },
    { key: "chat", label: "對話" },
    { key: "history", label: "歷史" },
  ];

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <NodeHeader
        selectedNode={selectedNode as GNode}
        maturity={maturity}
        lineagePath={lineagePath}
        isRootNode={isRootNode}
        editing={editing}
        editTitle={editTitle}
        setEditTitle={setEditTitle}
      />

      {/* Tab bar */}
      <div className="flex border-b border-[var(--border)] bg-[var(--bg-panel)]/80 px-2 gap-0 shrink-0">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setActiveTab(t.key)}
            className={`px-4 py-2.5 text-xs font-medium transition-colors border-b-2 -mb-px ${
              activeTab === t.key
                ? "border-blue-500 text-blue-300"
                : "border-transparent text-gray-500 hover:text-gray-300"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-4 bg-[linear-gradient(180deg,rgba(17,24,39,0.16)_0%,rgba(10,10,10,0)_100%)]">
        {activeTab === "content" && (
          <NodeContent
            selectedNode={selectedNode as GNode}
            editing={editing}
            editSummary={editSummary}
            setEditSummary={setEditSummary}
            newChildTitle={newChildTitle}
            setNewChildTitle={setNewChildTitle}
            onAddChild={handleAddChild}
            onPromoteMainline={promoteMainlineChild}
            refreshTree={refreshTree}
            Section={Section}
          />
        )}

        {activeTab === "ai" && (
          <NodeAI
            selectedNode={selectedNode as GNode}
            aiInstruction={aiInstruction}
            setAiInstruction={setAiInstruction}
            aiMode={aiMode}
            setAiMode={setAiMode}
            aiLoading={aiLoading}
            expandNode={expandNode}
            deepenNode={deepenNode}
            expandSuggestions={expandSuggestions}
            acceptSuggestion={acceptSuggestion}
            acceptAllSuggestions={acceptAllSuggestions}
            deepenResult={deepenResult}
            acceptDeepen={acceptDeepen}
            dismissAI={dismissAI}
            Section={Section}
          />
        )}

        {activeTab === "chat" && (
          <Section title="節點對話" subtitle="與 AI 顧問討論此節點的設計與方向。" tone="ai">
            <NodeChat selectedNode={selectedNode as GNode} />
          </Section>
        )}

        {activeTab === "history" && (
          <NodeHistorySection selectedNode={selectedNode as GNode} Section={Section} />
        )}
      </div>

      <div className="p-3 border-t border-[var(--border)] bg-[var(--bg-panel)]/80 flex gap-2">
        {editing ? (
          <>
            <button type="button" onClick={saveEdit} className="flex-1 px-3 py-2 bg-green-600 hover:bg-green-500 text-white text-sm rounded-lg">
              儲存
            </button>
            <button type="button" onClick={() => setEditing(false)} className="px-3 py-2 surface-subtle text-[var(--text-muted)] text-sm rounded-lg hover:text-[var(--text-primary)]">
              取消
            </button>
          </>
        ) : (
          <>
            <button type="button" onClick={startEdit} className="flex-1 px-3 py-2 surface-subtle text-[var(--text-primary)] text-sm rounded-lg hover:border-blue-500/40 hover:text-blue-100">
              ✏️ 編輯
            </button>
            <button
              type="button"
              onClick={() => { if (confirm("確定刪除此節點？")) deleteNode(selectedNode.id); }}
              className="px-3 py-2 rounded-lg border border-red-900/40 bg-red-950/30 hover:bg-red-900/40 text-red-300 text-sm"
            >
              🗑️
            </button>
          </>
        )}
      </div>
    </div>
  );
}
