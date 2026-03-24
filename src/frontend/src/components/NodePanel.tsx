"use client";

import { useState } from "react";
import { useStore } from "@/stores/useStore";
import { api } from "@/lib/api";
import { MATURITY_LABELS, MATURITY_COLORS, NODE_TYPE_ICONS, type Maturity } from "@/lib/types";

function ContentBlockCard({
  blockId, blockType, title, body, editing, onRefresh
}: {
  blockId: string; blockType: string; title: string; body: string; editing: boolean; onRefresh: () => Promise<void>;
}) {
  const [editTitle, setEditTitle] = useState(title);
  const [editBody, setEditBody] = useState(body);
  const [dirty, setDirty] = useState(false);

  const save = async () => {
    await api.updateBlock(blockId, { content: { title: editTitle, body: editBody } });
    setDirty(false);
    await onRefresh();
  };

  const remove = async () => {
    await api.deleteBlock(blockId);
    await onRefresh();
  };

  if (editing) {
    return (
      <div className="bg-gray-800/60 border border-blue-700/50 rounded-lg p-3 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-blue-400 uppercase">{blockType}</span>
          <button onClick={remove} className="text-[10px] text-red-400 hover:text-red-300">🗑️ 刪除</button>
        </div>
        <input
          value={editTitle}
          onChange={(e) => { setEditTitle(e.target.value); setDirty(true); }}
          className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-xs text-gray-200"
          placeholder="標題"
        />
        <textarea
          value={editBody}
          onChange={(e) => { setEditBody(e.target.value); setDirty(true); }}
          className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-xs text-gray-300 min-h-[60px]"
          placeholder="內容"
        />
        {dirty && (
          <button onClick={save} className="text-xs px-2 py-1 bg-green-700 hover:bg-green-600 text-white rounded">
            💾 儲存
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="bg-gray-800/60 border border-gray-700 rounded-lg p-3">
      <span className="text-[10px] text-blue-400 uppercase">{blockType}</span>
      {title && <p className="text-xs text-gray-200 font-medium mt-1">{title}</p>}
      {body && <p className="text-xs text-gray-400 mt-1 whitespace-pre-wrap">{body}</p>}
    </div>
  );
}

const ACTION_LABELS: Record<string, string> = {
  create_node: "🌱 建立",
  update_node: "✏️ 編輯",
  create_project: "📁 建立專案",
  maturity_advance: "⬆️ 成熟度提升",
  ai_expand: "🤖 AI 展開",
  ai_deepen: "🤖 AI 深化",
};

function NodeHistory({ nodeId }: { nodeId: string }) {
  const [history, setHistory] = useState<{ id: string; action_type: string; actor_type: string; payload: Record<string, unknown>; created_at: string }[]>([]);
  const [show, setShow] = useState(false);

  const load = async () => {
    const h = await api.getHistory(nodeId);
    setHistory(h);
    setShow(true);
  };

  if (!show) {
    return (
      <button onClick={load} className="text-xs text-gray-500 hover:text-gray-300 underline">
        📜 查看操作歷史
      </button>
    );
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <label className="text-xs text-gray-500 uppercase tracking-wider">📜 歷史</label>
        <button onClick={() => setShow(false)} className="text-xs text-gray-600 hover:text-gray-400">收起</button>
      </div>
      {history.length === 0 ? (
        <p className="text-xs text-gray-600">無記錄</p>
      ) : (
        history.map((h) => (
          <div key={h.id} className="text-[11px] text-gray-500 flex gap-2">
            <span className="text-gray-600 shrink-0">{h.created_at ? new Date(h.created_at).toLocaleString("zh-TW", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}</span>
            <span>{ACTION_LABELS[h.action_type] || h.action_type}</span>
            {h.action_type === "maturity_advance" && h.payload && (
              <span className="text-yellow-500">
                {String(h.payload.from)} → {String(h.payload.to)}
              </span>
            )}
            <span className="text-gray-700">({h.actor_type})</span>
          </div>
        ))
      )}
    </div>
  );
}

export function NodePanel() {
  const selectedNode = useStore((s) => s.selectedNode);
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
  const maturityColor = MATURITY_COLORS[maturity] || "#666";
  const maturityLabel = MATURITY_LABELS[maturity] || maturity;
  const icon = NODE_TYPE_ICONS[selectedNode.node_type] || "📌";

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
      {/* Header */}
      <div className="p-4 border-b border-gray-800">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-lg">{icon}</span>
          {editing ? (
            <input
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              className="flex-1 bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm text-gray-100"
              autoFocus
            />
          ) : (
            <h2 className="text-base font-semibold text-gray-100 flex-1 truncate">
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
          <span className="text-xs text-gray-500">{selectedNode.node_type}</span>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Summary */}
        <div>
          <label className="text-xs text-gray-500 uppercase tracking-wider">摘要</label>
          {editing ? (
            <textarea
              value={editSummary}
              onChange={(e) => setEditSummary(e.target.value)}
              className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-sm text-gray-200 mt-1 min-h-[80px]"
            />
          ) : (
            <p className="text-sm text-gray-300 mt-1">
              {selectedNode.summary || "（無摘要）"}
            </p>
          )}
        </div>

        {/* Content Blocks */}
        {selectedNode.content_blocks && selectedNode.content_blocks.length > 0 && (
          <div className="space-y-2">
            <label className="text-xs text-gray-500 uppercase tracking-wider">📄 內容區塊</label>
            {selectedNode.content_blocks.map((block) => {
              const content = block.content as unknown as Record<string, string>;
              return (
                <ContentBlockCard
                  key={block.id}
                  blockId={block.id}
                  blockType={block.block_type}
                  title={content?.title || ""}
                  body={content?.body || ""}
                  editing={editing}
                  onRefresh={async () => { await refreshTree(); }}
                />
              );
            })}
          </div>
        )}

        {/* AI Actions */}
        <div className="space-y-2">
          <label className="text-xs text-gray-500 uppercase tracking-wider">🤖 AI 生長</label>
          <input
            value={aiInstruction}
            onChange={(e) => setAiInstruction(e.target.value)}
            placeholder="可選：給 AI 的指示..."
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-300 placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
          />
          <div className="flex gap-2">
            <button
              onClick={() => expandNode(selectedNode.id, aiInstruction || undefined)}
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
        </div>

        {/* Expand Suggestions */}
        {expandSuggestions && expandSuggestions.length > 0 && (
          <div className="space-y-2">
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
          </div>
        )}

        {/* Deepen Result */}
        {deepenResult && (
          <div className="space-y-2">
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
          </div>
        )}

        {/* Add child */}
        <div>
          <label className="text-xs text-gray-500 uppercase tracking-wider">手動新增子節點</label>
          <div className="flex gap-2 mt-1">
            <input
              value={newChildTitle}
              onChange={(e) => setNewChildTitle(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddChild()}
              placeholder="輸入節點標題..."
              className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
            />
            <button
              onClick={handleAddChild}
              disabled={!newChildTitle.trim()}
              className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm rounded transition-colors"
            >
              +
            </button>
          </div>
        </div>

        {/* Children count */}
        <div>
          <label className="text-xs text-gray-500 uppercase tracking-wider">子節點</label>
          <p className="text-sm text-gray-400 mt-1">{selectedNode.children?.length || 0} 個</p>
        </div>

        {/* History */}
        <NodeHistory nodeId={selectedNode.id} />

        {/* Meta */}
        <div className="text-xs text-gray-600 space-y-1 pt-2 border-t border-gray-800">
          <div>ID: <span className="text-gray-500 font-mono">{selectedNode.id.slice(0, 8)}...</span></div>
          <div>建立: {new Date(selectedNode.created_at).toLocaleString("zh-TW")}</div>
          <div>更新: {new Date(selectedNode.updated_at).toLocaleString("zh-TW")}</div>
        </div>
      </div>

      {/* Footer actions */}
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
