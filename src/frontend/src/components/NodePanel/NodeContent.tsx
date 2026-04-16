"use client";

import { useState, type Dispatch, type SetStateAction } from "react";
import { api } from "@/lib/api";
import type { GNode } from "@/lib/types";
import { MATURITY_COLORS, MATURITY_LABELS, type Maturity, NODE_TYPE_ICONS } from "@/lib/types";

const NODE_TYPES = ["idea", "concept", "task", "question", "decision", "risk", "resource", "note", "module"];

interface NodeContentProps {
  selectedNode: GNode;
  editing: boolean;
  editSummary: string;
  setEditSummary: Dispatch<SetStateAction<string>>;
  newChildTitle: string;
  setNewChildTitle: Dispatch<SetStateAction<string>>;
  onAddChild: (nodeType?: string) => Promise<void>;
  onPromoteMainline: (parentId: string, childId: string) => Promise<void>;
  refreshTree: () => Promise<void>;
  Section: (props: { title: string; subtitle?: string; tone?: "neutral" | "ai" | "edit"; children: React.ReactNode }) => React.JSX.Element;
}

interface ContentBlockCardProps {
  blockId: string;
  blockType: string;
  title: string;
  body: string;
  editing: boolean;
  onRefresh: () => Promise<void>;
}

function ContentBlockCard({ blockId, blockType, title, body, editing, onRefresh }: ContentBlockCardProps) {
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
          <span className="text-xs text-blue-400 uppercase">{blockType}</span>
          <button onClick={remove} className="text-xs text-red-400 hover:text-red-300">🗑️ 刪除</button>
        </div>
        <input
          value={editTitle}
          onChange={(e) => { setEditTitle(e.target.value); setDirty(true); }}
          className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-gray-200"
          placeholder="標題"
        />
        <textarea
          value={editBody}
          onChange={(e) => { setEditBody(e.target.value); setDirty(true); }}
          className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-sm text-gray-300 min-h-[60px]"
          placeholder="內容"
        />
        {dirty && (
          <button onClick={save} className="text-sm px-2 py-1 bg-green-700 hover:bg-green-600 text-white rounded">
            💾 儲存
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="bg-gray-800/60 border border-gray-700 rounded-lg p-3">
      <span className="text-xs text-blue-400 uppercase">{blockType}</span>
      {title && <p className="text-sm text-gray-200 font-medium mt-1">{title}</p>}
      {body && <p className="text-sm text-gray-400 mt-1 whitespace-pre-wrap">{body}</p>}
    </div>
  );
}

export function NodeContent({
  selectedNode,
  editing,
  editSummary,
  setEditSummary,
  newChildTitle,
  setNewChildTitle,
  onAddChild,
  onPromoteMainline,
  refreshTree,
  Section,
}: NodeContentProps) {
  const [newChildType, setNewChildType] = useState("idea");

  const handleMaturityChange = async (newMaturity: string) => {
    await api.updateNode(selectedNode.id, { maturity: newMaturity } as Partial<GNode>);
    await refreshTree();
  };

  return (
    <Section title="節點內容" subtitle="先整理摘要，再補內容區塊與子節點。" tone={editing ? "edit" : "neutral"}>
      <div>
        <label className="text-sm text-gray-500 uppercase tracking-wider">成熟度</label>
        <div className="flex items-center gap-2 mt-1">
          <span
            className="w-3 h-3 rounded-full shrink-0"
            style={{ backgroundColor: MATURITY_COLORS[selectedNode.maturity as Maturity] || "#888" }}
          />
          <select
            value={selectedNode.maturity}
            onChange={(e) => handleMaturityChange(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          >
            {(Object.keys(MATURITY_LABELS) as Maturity[]).map((m) => (
              <option key={m} value={m}>{MATURITY_LABELS[m]}</option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="text-sm text-gray-500 uppercase tracking-wider">摘要</label>
        {editing ? (
          <textarea
            value={editSummary}
            onChange={(e) => setEditSummary(e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-sm text-gray-200 mt-1 min-h-[80px]"
          />
        ) : (
          <p className="text-base text-gray-300 mt-1">
            {selectedNode.summary || "（無摘要）"}
          </p>
        )}
      </div>

      {selectedNode.content_blocks && selectedNode.content_blocks.length > 0 && (
        <div className="space-y-3">
          <label className="text-sm text-gray-500 uppercase tracking-wider">📄 內容區塊</label>
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
                onRefresh={refreshTree}
              />
            );
          })}
        </div>
      )}

      <div>
        <label className="text-sm text-gray-500 uppercase tracking-wider">手動新增子節點</label>
        <div className="flex gap-2 mt-1">
          <select
            value={newChildType}
            onChange={(e) => setNewChildType(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none shrink-0"
          >
            {NODE_TYPES.map((t) => (
              <option key={t} value={t}>{NODE_TYPE_ICONS[t] || ""} {t}</option>
            ))}
          </select>
          <input
            value={newChildTitle}
            onChange={(e) => setNewChildTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onAddChild(newChildType)}
            placeholder="輸入節點標題..."
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
          />
          <button
            onClick={() => onAddChild(newChildType)}
            disabled={!newChildTitle.trim()}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm rounded transition-colors"
          >
            +
          </button>
        </div>
      </div>

      <div>
        <div className="text-sm text-gray-500 uppercase tracking-wider">子節點</div>
        <p className="text-base text-gray-400 mt-1">{selectedNode.children?.length || 0} 個</p>
        {selectedNode.children && selectedNode.children.length > 0 && (
          <div className="mt-2 space-y-2">
            {selectedNode.children.map((child) => (
              <div key={child.id} className="flex items-center justify-between rounded-lg border border-gray-800 bg-gray-900/60 px-3 py-2">
                <div>
                  <div className="text-base text-gray-200 flex items-center gap-2">
                    <span>{child.title}</span>
                    {child.is_mainline && <span className="text-xs text-blue-300 border border-blue-500/40 rounded-full px-1.5 py-0.5">主線</span>}
                  </div>
                  <div className="text-xs text-gray-500">{child.summary || child.node_type}</div>
                </div>
                {!child.is_mainline && (
                  <button
                    type="button"
                    onClick={() => onPromoteMainline(selectedNode.id, child.id)}
                    className="text-sm px-2.5 py-1 rounded border border-blue-700/50 bg-blue-950/30 text-blue-300 hover:bg-blue-900/40"
                  >
                    設為主線
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </Section>
  );
}
