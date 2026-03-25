"use client";

import { useState, type Dispatch, type SetStateAction } from "react";
import type { GNode } from "@/lib/types";

interface NodeContentProps {
  selectedNode: GNode;
  editing: boolean;
  editSummary: string;
  setEditSummary: Dispatch<SetStateAction<string>>;
  newChildTitle: string;
  setNewChildTitle: Dispatch<SetStateAction<string>>;
  onAddChild: () => Promise<void>;
  onUpdateBlock: (nodeId: string, blockId: string, data: { content?: Record<string, string>; block_type?: string }) => Promise<void>;
  onDeleteBlock: (nodeId: string, blockId: string) => Promise<void>;
  Section: (props: { title: string; subtitle?: string; tone?: "neutral" | "ai" | "edit"; children: React.ReactNode }) => React.JSX.Element;
}

interface ContentBlockCardProps {
  blockId: string;
  blockType: string;
  title: string;
  body: string;
  editing: boolean;
  nodeId: string;
  onUpdateBlock: (nodeId: string, blockId: string, data: { content?: Record<string, string>; block_type?: string }) => Promise<void>;
  onDeleteBlock: (nodeId: string, blockId: string) => Promise<void>;
}

function ContentBlockCard({ blockId, blockType, title, body, editing, nodeId, onUpdateBlock, onDeleteBlock }: ContentBlockCardProps) {
  const [editTitle, setEditTitle] = useState(title);
  const [editBody, setEditBody] = useState(body);
  const [dirty, setDirty] = useState(false);

  const save = async () => {
    await onUpdateBlock(nodeId, blockId, { content: { title: editTitle, body: editBody } });
    setDirty(false);
  };

  const remove = async () => {
    await onDeleteBlock(nodeId, blockId);
  };

  if (editing) {
    return (
      <div className="bg-gray-800/60 border border-blue-700/50 rounded-lg p-3 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-blue-400 uppercase">{blockType}</span>
          <button type="button" onClick={remove} className="text-[10px] text-red-400 hover:text-red-300">🗑️ 刪除</button>
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
          <button type="button" onClick={save} className="text-xs px-2 py-1 bg-green-700 hover:bg-green-600 text-white rounded">
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

export function NodeContent({
  selectedNode,
  editing,
  editSummary,
  setEditSummary,
  newChildTitle,
  setNewChildTitle,
  onAddChild,
  onUpdateBlock,
  onDeleteBlock,
  Section,
}: NodeContentProps) {
  return (
    <Section title="節點內容" subtitle="先整理摘要，再補內容區塊與子節點。" tone={editing ? "edit" : "neutral"}>
      <div>
        <div className="text-xs text-gray-500 uppercase tracking-wider">摘要</div>
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

      {selectedNode.content_blocks && selectedNode.content_blocks.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs text-gray-500 uppercase tracking-wider">📄 內容區塊</div>
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
                nodeId={selectedNode.id}
                onUpdateBlock={onUpdateBlock}
                onDeleteBlock={onDeleteBlock}
              />
            );
          })}
        </div>
      )}

      <div>
        <div className="text-xs text-gray-500 uppercase tracking-wider">手動新增子節點</div>
        <div className="flex gap-2 mt-1">
          <input
            value={newChildTitle}
            onChange={(e) => setNewChildTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onAddChild()}
            placeholder="輸入節點標題..."
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
          />
            <button
              type="button"
              onClick={onAddChild}
              disabled={!newChildTitle.trim()}
              className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm rounded transition-colors"
          >
            +
          </button>
        </div>
      </div>

      <div>
        <div className="text-xs text-gray-500 uppercase tracking-wider">子節點</div>
        <p className="text-sm text-gray-400 mt-1">{selectedNode.children?.length || 0} 個</p>
      </div>
    </Section>
  );
}
