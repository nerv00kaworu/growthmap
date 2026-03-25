"use client";

import { useState } from "react";
import { useStore } from "@/stores/useStore";
import { NodeHeader } from "./NodePanel/NodeHeader";
import { NodeContent } from "./NodePanel/NodeContent";
import { NodeAI } from "./NodePanel/NodeAI";
import { NodeHistorySection } from "./NodePanel/NodeHistory";
import type { GNode, GrowthMode, Maturity } from "@/lib/types";

interface SectionProps {
  title: string;
  subtitle?: string;
  tone?: "neutral" | "ai" | "edit";
  children: React.ReactNode;
}

const Section = ({ title, subtitle, tone = "neutral", children }: SectionProps) => {
  const toneClass = {
    neutral: "border-gray-800 bg-gray-900/35",
    ai: "border-purple-900/40 bg-purple-950/20",
    edit: "border-blue-900/40 bg-blue-950/20",
  }[tone];

  return (
    <section className={`rounded-xl border p-3 space-y-3 ${toneClass}`}>
      <div className="space-y-1">
        <label className="text-xs text-gray-400 uppercase tracking-wider">{title}</label>
        {subtitle && <p className="text-[11px] text-gray-600">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
};

export function NodePanel() {
  const selectedNode = useStore((s) => s.selectedNode);
  const rootNode = useStore((s) => s.rootNode);
  const addChildNode = useStore((s) => s.addChildNode);
  const updateNode = useStore((s) => s.updateNode);
  const deleteNode = useStore((s) => s.deleteNode);
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

  const [newChildTitle, setNewChildTitle] = useState("");
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editSummary, setEditSummary] = useState("");
  const [aiInstruction, setAiInstruction] = useState("");
  const [aiMode, setAiMode] = useState<GrowthMode>("explore");

  if (!selectedNode) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500 text-sm p-6">
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

  const handleAddChild = async () => {
    if (!newChildTitle.trim()) return;
    await addChildNode(selectedNode.id, newChildTitle.trim());
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

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <NodeContent
          selectedNode={selectedNode as GNode}
          editing={editing}
          editSummary={editSummary}
          setEditSummary={setEditSummary}
          newChildTitle={newChildTitle}
          setNewChildTitle={setNewChildTitle}
          onAddChild={handleAddChild}
          refreshTree={refreshTree}
          Section={Section}
        />

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

        <NodeHistorySection selectedNode={selectedNode as GNode} Section={Section} />
      </div>

      <div className="p-3 border-t border-gray-800 flex gap-2">
        {editing ? (
          <>
            <button onClick={saveEdit} className="flex-1 px-3 py-1.5 bg-green-600 hover:bg-green-500 text-white text-sm rounded">
              儲存
            </button>
            <button onClick={() => setEditing(false)} className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm rounded">
              取消
            </button>
          </>
        ) : (
          <>
            <button onClick={startEdit} className="flex-1 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm rounded">
              ✏️ 編輯
            </button>
            <button
              onClick={() => { if (confirm("確定刪除此節點？")) deleteNode(selectedNode.id); }}
              className="px-3 py-1.5 bg-red-900/50 hover:bg-red-800 text-red-400 text-sm rounded"
            >
              🗑️
            </button>
          </>
        )}
      </div>
    </div>
  );
}
