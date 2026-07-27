"use client";

import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { api } from "@/lib/api";
import type { GNode, NodeEditDraft, NodeFormalFieldKey } from "@/lib/types";
import { MATURITY_COLORS, MATURITY_LABELS, type Maturity, NODE_TYPE_ICONS } from "@/lib/types";
import { useStore } from "@/stores/useStore";

const NODE_TYPES = ["idea", "concept", "task", "question", "decision", "risk", "resource", "note", "module"];
const FORMAL_TEXT_FIELDS: { key: NodeFormalFieldKey; label: string }[] = [
  { key: "description", label: "描述" },
  { key: "rules_text", label: "規則" },
  { key: "constraints_text", label: "限制" },
  { key: "examples_text", label: "範例" },
  { key: "questions_text", label: "問題／驗收" },
  { key: "decision_notes", label: "決策紀錄" },
];

const BLOCK_TYPE_LABELS: Record<string, string> = {
  note: "筆記",
  spec: "規格",
  decision: "決策",
  todo: "待辦",
  risk: "風險",
  paragraph: "段落",
  resource: "文件",
  document: "文件",
  file: "文件",
};

interface NodeContentProps {
  selectedNode: GNode;
  editing: boolean;
  editSummary: string;
  setEditSummary: Dispatch<SetStateAction<string>>;
  editFields: NodeEditDraft;
  setEditFields: Dispatch<SetStateAction<NodeEditDraft>>;
  newChildTitle: string;
  setNewChildTitle: Dispatch<SetStateAction<string>>;
  onAddChild: (nodeType?: string) => Promise<void>;
  onPromoteMainline: (parentId: string, childId: string) => Promise<void>;
  refreshTree: () => Promise<void>;
  Section: (props: { title: string; subtitle?: string; tone?: "neutral" | "ai" | "edit"; children: React.ReactNode }) => React.JSX.Element;
}

type ContentBlockItem = {
  id: string;
  node_id: string;
  block_type: string;
  content: Record<string, string>;
  order_index: number;
};

interface ContentBlockCardProps {
  blockId: string;
  blockType: string;
  title: string;
  body: string;
  editing: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onMoveUp: () => Promise<void>;
  onMoveDown: () => Promise<void>;
  onRefresh: () => Promise<void>;
}

type BoundDoc = {
  id?: string;
  title?: string;
  name?: string;
  filename?: string;
  url?: string;
  path?: string;
  type?: string;
  summary?: string;
};

function ContentBlockCard({ blockId, blockType, title, body, editing, canMoveUp, canMoveDown, onMoveUp, onMoveDown, onRefresh }: ContentBlockCardProps) {
  const [editTitle, setEditTitle] = useState(title);
  const [editBody, setEditBody] = useState(body);
  const [dirty, setDirty] = useState(false);

  const save = async () => {
    await api.updateBlock(blockId, { content: { title: editTitle, body: editBody } });
    setDirty(false);
    await onRefresh();
  };

  const remove = async () => {
    const label = title || BLOCK_TYPE_LABELS[blockType] || blockType;
    if (!confirm(`確定刪除內容區塊「${label}」？此動作不可復原。`)) return;
    await api.deleteBlock(blockId);
    await onRefresh();
  };

  if (editing) {
    return (
      <div className="bg-gray-800/60 border border-blue-700/50 rounded-lg p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-blue-400">{BLOCK_TYPE_LABELS[blockType] || blockType}</span>
          <div className="flex items-center gap-1">
            <button type="button" onClick={onMoveUp} disabled={!canMoveUp} className="text-xs px-1.5 py-0.5 rounded border border-gray-700 text-gray-300 hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed">↑</button>
            <button type="button" onClick={onMoveDown} disabled={!canMoveDown} className="text-xs px-1.5 py-0.5 rounded border border-gray-700 text-gray-300 hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed">↓</button>
            <button type="button" onClick={remove} className="text-xs text-red-400 hover:text-red-300">🗑️ 刪除</button>
          </div>
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
    <div className="bg-gray-800/55 border border-gray-700 rounded-lg p-2.5">
      <span className="text-xs text-blue-400">{BLOCK_TYPE_LABELS[blockType] || blockType}</span>
      {title && <p className="text-sm text-gray-200 font-medium mt-0.5">{title}</p>}
      {body && <p className="text-sm text-gray-400 mt-0.5 leading-6 whitespace-pre-wrap">{body}</p>}
    </div>
  );
}

function readBoundDocs(meta: Record<string, unknown>): BoundDoc[] {
  const candidates = [
    meta.bound_documents,
    meta.boundDocs,
    meta.linked_documents,
    meta.linkedDocs,
    meta.attached_documents,
    meta.attachedDocs,
    meta.documents,
    meta.files,
  ];

  for (const candidate of candidates) {
    if (Array.isArray(candidate)) {
      return candidate.filter((item): item is BoundDoc => typeof item === "object" && item !== null);
    }
  }

  return [];
}

export function NodeContent({
  selectedNode,
  editing,
  editSummary,
  setEditSummary,
  editFields,
  setEditFields,
  newChildTitle,
  setNewChildTitle,
  onAddChild,
  onPromoteMainline,
  refreshTree,
  Section,
}: NodeContentProps) {
  const [newChildType, setNewChildType] = useState("idea");
  const [showBranchModal, setShowBranchModal] = useState(false);
  const [showBranchReview, setShowBranchReview] = useState(false);
  const [branchName, setBranchName] = useState("");
  const [branchDesc, setBranchDesc] = useState("");
  const [newBlockType, setNewBlockType] = useState("note");
  const [newBlockTitle, setNewBlockTitle] = useState("");
  const [newBlockBody, setNewBlockBody] = useState("");
  const [newDocTitle, setNewDocTitle] = useState("");
  const [newDocUrl, setNewDocUrl] = useState("");
  const [newDocSummary, setNewDocSummary] = useState("");
  const [blocks, setBlocks] = useState<ContentBlockItem[]>(() =>
    (selectedNode.content_blocks || []) as ContentBlockItem[]
  );
  const createBranch = useStore((s) => s.createBranch);
  const currentBranch = useStore((s) => s.currentBranch);
  const currentProject = useStore((s) => s.currentProject);
  const branchComparison = useStore((s) => s.branchComparison);
  const branchLoading = useStore((s) => s.branchLoading);
  const compareBranch = useStore((s) => s.compareBranch);
  const mergeBranch = useStore((s) => s.mergeBranch);
  const [mergeTargets, setMergeTargets] = useState<GNode[]>([]);
  const [mergeTargetId, setMergeTargetId] = useState("");
  const boundDocs: BoundDoc[] = [
    ...readBoundDocs(selectedNode.meta || {}),
    ...blocks
      .filter((block) => ["resource", "document", "file"].includes(block.block_type))
      .map((block) => ({
        id: block.id,
        title: block.content?.title,
        url: block.content?.url,
        path: block.content?.path,
        summary: block.content?.summary || block.content?.body,
        type: BLOCK_TYPE_LABELS[block.block_type] || block.block_type,
      })),
  ];
  const contentBlocks = blocks.filter((block) => !["resource", "document", "file"].includes(block.block_type));
  const hasContentBlocks = contentBlocks.length > 0;
  const hasChildren = (selectedNode.children?.length || 0) > 0;

  useEffect(() => {
    setBlocks((selectedNode.content_blocks || []) as ContentBlockItem[]);

    let alive = true;
    api.getBlocks(selectedNode.id)
      .then((rows) => {
        if (alive) setBlocks(rows as ContentBlockItem[]);
      })
      .catch(() => {
        // fallback to subtree-provided blocks
      });

    return () => {
      alive = false;
    };
  }, [selectedNode.id, selectedNode.content_blocks]);

  const handleMaturityChange = async (newMaturity: string) => {
    await api.updateNode(selectedNode.id, { maturity: newMaturity } as Partial<GNode>);
    await refreshTree();
  };

  const flattenTree = (node: GNode): GNode[] => [node, ...(node.children || []).flatMap(flattenTree)];

  const openBranchReview = async () => {
    if (!currentBranch || !currentProject) return;
    const [comparison, mainTree] = await Promise.all([
      compareBranch(currentBranch.id),
      api.getSubtree(currentProject.root_node_id),
    ]);
    if (!comparison) return;
    setMergeTargets(flattenTree(mainTree));
    setMergeTargetId(currentBranch.source_node_id || mainTree.id);
    setShowBranchReview(true);
  };

  const handleMergeCurrentBranch = async () => {
    if (!currentBranch || !mergeTargetId) return;
    if (!confirm(`確定將方案線「${currentBranch.name}」合併到選定主線節點？\n\n合併後方案線會結束，並把整個方案子樹接到目標節點下方。`)) return;
    await mergeBranch(currentBranch.id, mergeTargetId);
    setShowBranchReview(false);
  };

  const moveBlock = async (index: number, direction: -1 | 1) => {
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= blocks.length) return;

    const current = blocks[index];
    const target = blocks[nextIndex];
    const nextBlocks = [...blocks];
    [nextBlocks[index], nextBlocks[nextIndex]] = [nextBlocks[nextIndex], nextBlocks[index]];

    setBlocks(nextBlocks.map((block, order_index) => ({ ...block, order_index })));

    try {
      await Promise.all([
        api.updateBlock(current.id, { order_index: nextIndex }),
        api.updateBlock(target.id, { order_index: index }),
      ]);
      await refreshTree();
    } catch (error) {
      setBlocks(blocks);
      alert(`調整內容區塊順序失敗：${error instanceof Error ? error.message : "未知錯誤"}`);
    }
  };

  const handleAddDoc = async () => {
    if (!newDocTitle.trim() && !newDocUrl.trim()) {
      alert("請至少輸入文件標題或 URL");
      return;
    }

    try {
      const created = await api.createBlock(selectedNode.id, {
        block_type: "resource",
        content: {
          title: newDocTitle.trim() || newDocUrl.trim(),
          url: newDocUrl.trim(),
          summary: newDocSummary.trim(),
        },
      }) as ContentBlockItem;
      setBlocks((prev) => [...prev, created]);
      setNewDocTitle("");
      setNewDocUrl("");
      setNewDocSummary("");
      await refreshTree();
    } catch (error) {
      alert(`新增綁定文件失敗：${error instanceof Error ? error.message : "未知錯誤"}`);
    }
  };

  const handleRemoveDoc = async (doc: BoundDoc) => {
    if (!doc.id) return;
    const label = doc.title || doc.name || doc.filename || doc.url || "文件";
    if (!confirm(`確定移除綁定文件「${label}」？`)) return;
    try {
      await api.deleteBlock(doc.id);
      setBlocks((prev) => prev.filter((block) => block.id !== doc.id));
      await refreshTree();
    } catch (error) {
      alert(`移除綁定文件失敗：${error instanceof Error ? error.message : "未知錯誤"}`);
    }
  };

  const handleCreateBlock = async () => {
    if (!newBlockBody.trim() && !newBlockTitle.trim()) {
      alert("請至少輸入標題或內容");
      return;
    }

    try {
      const created = await api.createBlock(selectedNode.id, {
        block_type: newBlockType,
        content: { title: newBlockTitle.trim(), body: newBlockBody.trim() },
      }) as ContentBlockItem;

      setBlocks((prev) => [...prev, created]);
      setNewBlockTitle("");
      setNewBlockBody("");
      await refreshTree();
    } catch (error) {
      alert(`新增內容區塊失敗：${error instanceof Error ? error.message : "未知錯誤"}`);
    }
  };

  return (
    <div className="space-y-3">
      {currentBranch && (
        <div className="rounded-xl border border-purple-800/50 bg-purple-950/25 px-4 py-3 text-sm text-purple-100">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="font-semibold">🔀 方案線模式：{currentBranch.name}</div>
              <p className="mt-1 text-xs leading-5 text-purple-200/70">
                這是平行方案，不會直接改動主線。確認方向可合併回原本開出的主線節點。
              </p>
            </div>
            <button
              type="button"
              onClick={openBranchReview}
              disabled={branchLoading}
              className="shrink-0 rounded-lg border border-purple-500/50 bg-purple-700/40 px-3 py-1.5 text-xs text-purple-100 hover:bg-purple-600/50 disabled:opacity-50"
            >
              {branchLoading ? "讀取中…" : "檢視並合併"}
            </button>
          </div>
        </div>
      )}

      <Section title="內容工作區" subtitle="正式欄位與內容區塊分開保存；此處不會自動遷移或複製內容。" tone={editing ? "edit" : "neutral"}>
        <div className="space-y-4">
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
                className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-sm text-gray-200 mt-1 min-h-[96px]"
              />
            ) : (
              <div className="mt-2 rounded-xl border border-gray-800 bg-gray-900/50 p-4">
                <p className="text-base leading-7 text-gray-300 whitespace-pre-wrap">
                  {selectedNode.summary || "（無摘要）"}
                </p>
              </div>
            )}
          </div>

          <div className="space-y-3 rounded-xl border border-gray-700/80 bg-gray-900/35 p-3">
            <div>
              <label className="text-sm text-gray-300 uppercase tracking-wider">節點正式欄位</label>
              <p className="mt-1 text-xs text-gray-500">直接對應後端 nodes 欄位；空值仍會明示，不會偽裝成內容區塊。</p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <label className="text-xs text-gray-500">節點狀態
                {editing ? (
                  <input value={editFields.status} onChange={(e) => setEditFields((prev) => ({ ...prev, status: e.target.value }))} className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200" />
                ) : <div className="mt-1 text-sm text-gray-300">{selectedNode.status || "（未填）"}</div>}
              </label>
              <label className="text-xs text-gray-500">工作流狀態
                {editing ? (
                  <input value={editFields.workflow_status} onChange={(e) => setEditFields((prev) => ({ ...prev, workflow_status: e.target.value }))} className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200" />
                ) : <div className="mt-1 text-sm text-gray-300">{selectedNode.workflow_status || "（未填）"}</div>}
              </label>
              <label className="text-xs text-gray-500">優先級
                {editing ? (
                  <input type="number" value={editFields.priority} onChange={(e) => setEditFields((prev) => ({ ...prev, priority: Number(e.target.value) }))} className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200" />
                ) : <div className="mt-1 text-sm text-gray-300">{selectedNode.priority ?? "（未填）"}</div>}
              </label>
              <label className="text-xs text-gray-500">信心值
                {editing ? (
                  <input type="number" min="0" max="1" step="0.01" value={editFields.confidence} onChange={(e) => setEditFields((prev) => ({ ...prev, confidence: Number(e.target.value) }))} className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200" />
                ) : <div className="mt-1 text-sm text-gray-300">{selectedNode.confidence ?? "（未填）"}</div>}
              </label>
            </div>

            {FORMAL_TEXT_FIELDS.map(({ key, label }) => (
              <div key={key}>
                <label className="text-xs text-gray-500">{label}</label>
                {editing ? (
                  <textarea
                    value={editFields[key]}
                    onChange={(e) => setEditFields((prev) => ({ ...prev, [key]: e.target.value }))}
                    className="mt-1 min-h-[88px] w-full rounded border border-gray-700 bg-gray-900 p-2 text-sm leading-6 text-gray-200"
                  />
                ) : (
                  <div className="mt-1 rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-2 text-sm leading-6 text-gray-300 whitespace-pre-wrap">
                    {selectedNode[key] || "（未填）"}
                  </div>
                )}
              </div>
            ))}

            <div>
              <label className="text-xs text-gray-500">檔案路徑（每行一筆）</label>
              {editing ? (
                <textarea
                  value={editFields.file_paths.join("\n")}
                  onChange={(e) => setEditFields((prev) => ({ ...prev, file_paths: e.target.value.split("\n").map((path) => path.trim()).filter(Boolean) }))}
                  className="mt-1 min-h-[72px] w-full rounded border border-gray-700 bg-gray-900 p-2 font-mono text-xs text-gray-200"
                  placeholder="（未填）"
                />
              ) : (selectedNode.file_paths || []).length > 0 ? (
                <ul className="mt-1 space-y-1 rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-2 font-mono text-xs text-gray-300">
                  {(selectedNode.file_paths || []).map((path, index) => <li key={`${path}-${index}`} className="break-all">{path}</li>)}
                </ul>
              ) : <div className="mt-1 text-sm text-gray-500">（未填）</div>}
            </div>
          </div>

          <div className="space-y-3 border-t border-gray-800 pt-4">
            <div>
              <label className="text-sm text-gray-500 uppercase tracking-wider">📄 內容區塊</label>
              <p className="mt-1 text-xs text-gray-600">獨立的 content_blocks 記錄，不與上方正式欄位互相轉換。</p>
            </div>

            {editing && (
              <div className="rounded-xl border border-blue-900/40 bg-blue-950/20 p-3 space-y-2">
                <div className="flex gap-2">
                  <select
                    value={newBlockType}
                    onChange={(e) => setNewBlockType(e.target.value)}
                    className="bg-gray-800 border border-gray-700 rounded-md px-2 py-1.5 text-xs text-gray-200"
                  >
                    <option value="note">筆記</option>
                    <option value="spec">規格</option>
                    <option value="decision">決策</option>
                    <option value="todo">待辦</option>
                    <option value="risk">風險</option>
                  </select>
                  <input
                    value={newBlockTitle}
                    onChange={(e) => setNewBlockTitle(e.target.value)}
                    placeholder="區塊標題（選填）"
                    className="flex-1 bg-gray-900 border border-gray-700 rounded-md px-2.5 py-1.5 text-sm text-gray-200"
                  />
                </div>
                <textarea
                  value={newBlockBody}
                  onChange={(e) => setNewBlockBody(e.target.value)}
                  placeholder="輸入內容區塊..."
                  className="w-full bg-gray-900 border border-gray-700 rounded-md px-2.5 py-2 text-sm text-gray-200 min-h-[72px]"
                />
                <button
                  type="button"
                  onClick={handleCreateBlock}
                  disabled={!newBlockBody.trim() && !newBlockTitle.trim()}
                  className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm"
                >
                  + 新增內容區塊
                </button>
              </div>
            )}

            {hasContentBlocks ? (
              contentBlocks.map((block, index) => {
                const content = block.content as unknown as Record<string, string>;
                return (
                  <ContentBlockCard
                    key={block.id}
                    blockId={block.id}
                    blockType={block.block_type}
                    title={content?.title || ""}
                    body={content?.body || ""}
                    editing={editing}
                    canMoveUp={index > 0}
                    canMoveDown={index < blocks.length - 1}
                    onMoveUp={() => moveBlock(blocks.findIndex((b) => b.id === block.id), -1)}
                    onMoveDown={() => moveBlock(blocks.findIndex((b) => b.id === block.id), 1)}
                    onRefresh={refreshTree}
                  />
                );
              })
            ) : (
              <div className="rounded-lg border border-dashed border-gray-800/80 bg-gray-900/20 px-3.5 py-4 text-sm text-gray-500">
                尚無內容區塊。
              </div>
            )}
          </div>

          <div className="space-y-3">
            <label className="text-sm text-gray-500 uppercase tracking-wider">📎 已綁定文件</label>

            <div className="rounded-xl border border-gray-800 bg-gray-900/40 p-3 space-y-2">
                <div className="flex gap-2">
                  <input
                    value={newDocTitle}
                    onChange={(e) => setNewDocTitle(e.target.value)}
                    placeholder="文件標題"
                    className="flex-1 bg-gray-900 border border-gray-700 rounded-md px-2.5 py-1.5 text-sm text-gray-200"
                  />
                  <input
                    value={newDocUrl}
                    onChange={(e) => setNewDocUrl(e.target.value)}
                    placeholder="URL / 路徑"
                    className="flex-1 bg-gray-900 border border-gray-700 rounded-md px-2.5 py-1.5 text-sm text-gray-200"
                  />
                </div>
                <input
                  value={newDocSummary}
                  onChange={(e) => setNewDocSummary(e.target.value)}
                  placeholder="文件摘要（選填）"
                  className="w-full bg-gray-900 border border-gray-700 rounded-md px-2.5 py-1.5 text-sm text-gray-200"
                />
                <button
                  type="button"
                  onClick={handleAddDoc}
                  disabled={!newDocTitle.trim() && !newDocUrl.trim()}
                  className="px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 disabled:text-gray-600 text-white text-sm"
                >
                  + 綁定文件
                </button>
              </div>

            {boundDocs.length > 0 ? (
              <div className="space-y-2">
                {boundDocs.map((doc, index) => {
                  const label = doc.title || doc.name || doc.filename || `文件 ${index + 1}`;
                  const href = doc.url || doc.path;
                  const metaText = [doc.type, doc.summary].filter(Boolean).join(" · ");
                  return (
                    <div key={doc.id || href || `${label}-${index}`} className="rounded-lg border border-gray-800 bg-gray-900/50 px-3 py-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-gray-200 break-words">{label}</div>
                          {metaText && <div className="mt-1 text-xs text-gray-500 break-words">{metaText}</div>}
                        </div>
                        <div className="shrink-0 flex items-center gap-2">
                          {href && (
                            <a
                              href={href}
                              target="_blank"
                              rel="noreferrer"
                              className="text-xs text-blue-300 hover:text-blue-200"
                            >
                              開啟
                            </a>
                          )}
                          {editing && doc.id && (
                            <button
                              type="button"
                              onClick={() => handleRemoveDoc(doc)}
                              className="text-xs text-red-400 hover:text-red-300"
                            >
                              移除
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-gray-800/80 bg-gray-900/20 px-3.5 py-4 text-sm text-gray-500">
                尚無綁定文件。
              </div>
            )}
          </div>
        </div>
      </Section>

      <Section title="內容工具" subtitle="主線內容擴寫：直接新增到目前路徑。" tone="edit">
        <div>
          <label className="text-sm text-gray-500 uppercase tracking-wider">主線新增節點</label>
          <div className="mt-1 flex gap-2">
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
      </Section>

      <Section title="方案工具" subtitle={currentBranch ? "目前在方案線中；可上方合併回主線，或到更多操作刪除方案線。" : "用來開平行方案線（分支），不是主線擴寫。"} tone="neutral">
        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between">
              <div className="text-sm text-gray-500 uppercase tracking-wider">子節點</div>
              {hasChildren && (
                <button
                  type="button"
                  onClick={() => { setBranchName(""); setBranchDesc(""); setShowBranchModal(true); }}
                  className="text-xs px-2.5 py-1 rounded border border-purple-700/50 bg-purple-950/30 text-purple-300 hover:bg-purple-900/40"
                >
                  🔀 開新方案線
                </button>
              )}
            </div>
            <p className="text-base text-gray-400 mt-1">{selectedNode.children?.length || 0} 個</p>
            <p className="text-[11px] text-gray-500 mt-0.5">建立後可在頂欄「🌿 main」旁的分支下拉切換。</p>
            {hasChildren ? (
              <div className="mt-2.5 space-y-1.5">
                {selectedNode.children?.map((child) => (
                  <div key={child.id} className="flex items-center justify-between gap-2.5 rounded-lg border border-gray-800 bg-gray-900/55 px-3 py-1.5">
                    <div className="min-w-0">
                      <div className="text-sm text-gray-100 font-medium flex items-center gap-2">
                        <span className="truncate">{child.title}</span>
                        {child.is_mainline && <span className="text-xs text-blue-300 border border-blue-500/40 rounded-full px-1.5 py-0.5">主線</span>}
                      </div>
                      <div className="text-[11px] text-gray-500 truncate mt-0.5">{child.summary || child.node_type}</div>
                    </div>
                    {!child.is_mainline && (
                      <button
                        type="button"
                        onClick={() => onPromoteMainline(selectedNode.id, child.id)}
                        className="shrink-0 text-sm px-2.5 py-1 rounded border border-blue-700/50 bg-blue-950/30 text-blue-300 hover:bg-blue-900/40"
                      >
                        設為主線
                      </button>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-3 rounded-lg border border-dashed border-gray-800/80 bg-gray-900/20 px-3.5 py-4 text-sm text-gray-500">
                尚無子節點。
              </div>
            )}
          </div>
        </div>
      </Section>

      {showBranchReview && currentBranch && branchComparison && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 px-4" onClick={() => setShowBranchReview(false)}>
          <div className="w-full max-w-lg space-y-4 rounded-xl border border-purple-800/60 bg-[#111] p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div>
              <h3 className="text-sm font-semibold text-gray-100">🔎 方案線檢視：{currentBranch.name}</h3>
              <p className="mt-1 text-xs text-gray-500">比較目前方案根節點與開出來源；確認目標後才會合併。</p>
            </div>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
                <div className="text-gray-500">來源主線</div>
                <div className="mt-1 font-medium text-gray-200">{branchComparison.source?.title || "來源已不存在"}</div>
                <div className="mt-1 text-gray-500">內容區塊 {branchComparison.diff.source_block_count}</div>
              </div>
              <div className="rounded-lg border border-purple-800/50 bg-purple-950/20 p-3">
                <div className="text-purple-300/70">方案根節點</div>
                <div className="mt-1 font-medium text-purple-100">{branchComparison.branch_root?.title || "無方案根節點"}</div>
                <div className="mt-1 text-purple-200/60">節點 {branchComparison.diff.branch_node_count} · 內容區塊 {branchComparison.diff.branch_block_count}</div>
              </div>
            </div>
            <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-3 text-xs text-gray-400">
              <div className="mb-1 text-gray-300">差異摘要</div>
              <div className="flex flex-wrap gap-2">
                <span className={branchComparison.diff.title_changed ? "text-amber-300" : "text-gray-600"}>標題{branchComparison.diff.title_changed ? "已變更" : "未變更"}</span>
                <span className={branchComparison.diff.summary_changed ? "text-amber-300" : "text-gray-600"}>摘要{branchComparison.diff.summary_changed ? "已變更" : "未變更"}</span>
                <span className={branchComparison.diff.maturity_changed ? "text-amber-300" : "text-gray-600"}>成熟度{branchComparison.diff.maturity_changed ? "已變更" : "未變更"}</span>
              </div>
            </div>
            <label className="block text-xs text-gray-400">
              合併到主線節點
              <select value={mergeTargetId} onChange={(e) => setMergeTargetId(e.target.value)} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100 focus:border-purple-500 focus:outline-none">
                {mergeTargets.map((target) => <option key={target.id} value={target.id}>{"  ".repeat(target.ancestor_path?.length || 0)}{target.title}</option>)}
              </select>
            </label>
            <div className="flex gap-2">
              <button type="button" onClick={handleMergeCurrentBranch} disabled={!mergeTargetId || branchLoading} className="flex-1 rounded-lg bg-purple-700 px-3 py-2 text-sm text-white hover:bg-purple-600 disabled:bg-gray-700">確認合併</button>
              <button type="button" onClick={() => setShowBranchReview(false)} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-300">取消</button>
            </div>
          </div>
        </div>
      )}

      {showBranchModal && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center" onClick={() => setShowBranchModal(false)}>
          <div className="bg-[#111] border border-gray-700 rounded-xl p-5 w-72 space-y-3" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-gray-200">🔀 開新方案線</h3>
            <input
              value={branchName}
              onChange={(e) => setBranchName(e.target.value)}
              placeholder="方案線名稱（例：方案B：微服務架構）"
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:border-purple-500 focus:outline-none"
            />
            <input
              value={branchDesc}
              onChange={(e) => setBranchDesc(e.target.value)}
              placeholder="描述（選填）"
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:border-purple-500 focus:outline-none"
            />
            <div className="flex gap-2">
              <button
                type="button"
                disabled={!branchName.trim()}
                onClick={async () => {
                  if (!branchName.trim()) return;
                  await createBranch(selectedNode.id, branchName.trim(), branchDesc.trim());
                  setShowBranchModal(false);
                }}
                className="flex-1 px-3 py-2 bg-purple-700 hover:bg-purple-600 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm rounded-lg transition-colors"
              >
                建立
              </button>
              <button
                type="button"
                onClick={() => setShowBranchModal(false)}
                className="px-3 py-2 text-gray-500 hover:text-gray-300 text-sm"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
