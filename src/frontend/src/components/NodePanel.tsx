"use client";

import { useState } from "react";
import { useStore } from "@/stores/useStore";
import { NodeHeader } from "./NodePanel/NodeHeader";
import { NodeContent } from "./NodePanel/NodeContent";
import { NodeAI } from "./NodePanel/NodeAI";
import { NodeHistorySection } from "./NodePanel/NodeHistory";
import { NodeChat } from "./NodePanel/NodeChat";
import type { GNode, GrowthMode, Maturity, NodeEditDraft } from "@/lib/types";
import { useI18n } from "@/i18n/provider";
import { msg } from "@/i18n/ui";

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
    <section className={`rounded-xl border p-4 space-y-2.5 ${toneClass}`}>
      <div className="space-y-1">
        <h3 className="text-xs font-semibold tracking-wide text-[var(--text-primary)] uppercase">{title}</h3>
        {subtitle && <p className="text-[11px] leading-5 text-[var(--text-faint)]">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
};

type Tab = "content" | "ai" | "chat" | "history";

export function NodePanel() {
  const { locale, t } = useI18n();
  const m = (tw: string, cn: string, en: string) => msg(locale, {"zh-TW":tw,"zh-CN":cn,en});
  const selectedNode = useStore((s) => s.selectedNode);
  const rootNode = useStore((s) => s.rootNode);
  const addChildNode = useStore((s) => s.addChildNode);
  const updateNode = useStore((s) => s.updateNode);
  const deleteNode = useStore((s) => s.deleteNode);
  const promoteMainlineChild = useStore((s) => s.promoteMainlineChild);
  const expandNode = useStore((s) => s.expandNode);
  const deepenNode = useStore((s) => s.deepenNode);
  const acceptSuggestion = useStore((s) => s.acceptSuggestion);
  const ignoreSuggestion = useStore((s) => s.ignoreSuggestion);
  const acceptAllSuggestions = useStore((s) => s.acceptAllSuggestions);
  const acceptDeepen = useStore((s) => s.acceptDeepen);
  const acceptDeepenSummary = useStore((s) => s.acceptDeepenSummary);
  const acceptDeepenBlock = useStore((s) => s.acceptDeepenBlock);
  const ignoreDeepenBlock = useStore((s) => s.ignoreDeepenBlock);
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
  const [editFields, setEditFields] = useState<NodeEditDraft>({
    description: "", rules_text: "", constraints_text: "", examples_text: "",
    questions_text: "", decision_notes: "", status: "active", workflow_status: "draft",
    priority: 0, confidence: 0.5, file_paths: [],
  });
  const [aiInstruction, setAiInstruction] = useState("");
  const [aiMode, setAiMode] = useState<GrowthMode>("explore");

  if (!selectedNode) {
    return (
      <div className="h-full flex items-center justify-center text-[var(--text-faint)] text-sm p-6">
        <div className="text-center">
          <div className="text-4xl mb-3">🌳</div>
          <div>{m("點擊節點查看詳情", "点击节点查看详情", "Click a node to view details")}</div>
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
    setEditFields({
      description: selectedNode.description || "",
      rules_text: selectedNode.rules_text || "",
      constraints_text: selectedNode.constraints_text || "",
      examples_text: selectedNode.examples_text || "",
      questions_text: selectedNode.questions_text || "",
      decision_notes: selectedNode.decision_notes || "",
      status: selectedNode.status || "active",
      workflow_status: selectedNode.workflow_status || "draft",
      priority: selectedNode.priority ?? 0,
      confidence: selectedNode.confidence ?? 0.5,
      file_paths: selectedNode.file_paths || [],
    });
    setEditing(true);
  };

  const saveEdit = async () => {
    await updateNode(selectedNode.id, { title: editTitle, summary: editSummary, ...editFields });
    setEditing(false);
  };

  const TABS: { key: Tab; label: string }[] = [
    { key: "content", label: m("內容", "内容", "Content") },
    { key: "ai", label: "AI" },
    { key: "chat", label: m("對話", "对话", "Chat") },
    { key: "history", label: m("歷史", "历史", "History") },
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
      <div className="flex border-b border-[var(--border)] bg-[var(--bg-panel)]/80 px-1.5 gap-0 shrink-0">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setActiveTab(t.key)}
            className={`px-3 py-2 text-[11px] font-medium transition-colors border-b-2 -mb-px ${
              activeTab === t.key
                ? "border-blue-400 text-blue-200 bg-blue-950/20"
                : "border-transparent text-gray-400 hover:text-gray-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-[linear-gradient(180deg,rgba(17,24,39,0.16)_0%,rgba(10,10,10,0)_100%)]">
        {activeTab === "content" && (
          <NodeContent
            selectedNode={selectedNode as GNode}
            editing={editing}
            editSummary={editSummary}
            setEditSummary={setEditSummary}
            editFields={editFields}
            setEditFields={setEditFields}
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
            ignoreSuggestion={ignoreSuggestion}
            acceptAllSuggestions={acceptAllSuggestions}
            deepenResult={deepenResult}
            acceptDeepen={acceptDeepen}
            acceptDeepenSummary={acceptDeepenSummary}
            acceptDeepenBlock={acceptDeepenBlock}
            ignoreDeepenBlock={ignoreDeepenBlock}
            dismissAI={dismissAI}
            Section={Section}
          />
        )}

        {activeTab === "chat" && (
          <Section title={m("節點對話", "节点对话", "Node chat")} subtitle={m("與 AI 顧問討論此節點的設計與方向。", "与 AI 顾问讨论此节点的设计与方向。", "Discuss this node’s design and direction with the AI advisor.")} tone="ai">
            <NodeChat selectedNode={selectedNode as GNode} />
          </Section>
        )}

        {activeTab === "history" && (
          <NodeHistorySection selectedNode={selectedNode as GNode} Section={Section} />
        )}
      </div>

      <div className="p-2 border-t border-[var(--border)] bg-[var(--bg-panel)]/80 flex gap-1.5">
        {editing ? (
          <>
            <button type="button" onClick={saveEdit} className="flex-1 px-3 py-1.5 bg-green-600 hover:bg-green-500 text-white text-sm rounded-md">
              {m("儲存", "保存", "Save")}
            </button>
            <button type="button" onClick={() => setEditing(false)} className="px-3 py-1.5 surface-subtle text-[var(--text-muted)] text-sm rounded-md hover:text-[var(--text-primary)]">
              {m("取消", "取消", "Cancel")}
            </button>
          </>
        ) : (
          <>
            <button type="button" onClick={startEdit} className="flex-1 px-3 py-1.5 surface-subtle text-[var(--text-primary)] text-sm rounded-md hover:border-blue-500/40 hover:text-blue-100">
              ✏️ {m("編輯", "编辑", "Edit")}
            </button>
            <button
              type="button"
              onClick={() => { if (confirm(t("confirm.deleteNode"))) deleteNode(selectedNode.id); }}
              className="px-3 py-1.5 rounded-md border border-red-900/40 bg-red-950/30 hover:bg-red-900/40 text-red-300 text-sm"
            >
              🗑️
            </button>
          </>
        )}
      </div>
    </div>
  );
}
