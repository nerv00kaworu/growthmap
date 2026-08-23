"use client";
import { useI18n } from "@/i18n/provider";
import { msg } from "@/i18n/ui";

import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { api } from "@/lib/api";
import type { GNode, NodeEditDraft, NodeFormalFieldKey } from "@/lib/types";
import { MATURITY_COLORS, MATURITY_LABELS, type Maturity, NODE_TYPE_ICONS } from "@/lib/types";
import { useStore } from "@/stores/useStore";
import { reorderBlockAuthoritatively } from "./block-reorder";

const NODE_TYPES = ["idea", "concept", "task", "question", "decision", "risk", "resource", "note", "module"];
const FORMAL_TEXT_FIELDS: { key: NodeFormalFieldKey; label: string }[] = [
  { key: "description", label: "Description" },
  { key: "rules_text", label: "Rules" },
  { key: "constraints_text", label: "Constraints" },
  { key: "examples_text", label: "Examples" },
  { key: "questions_text", label: "Questions / acceptance" },
  { key: "decision_notes", label: "Decision notes" },
];

const BLOCK_TYPE_LABELS: Record<string, string> = {
  note: "Note",
  spec: "Specification",
  decision: "Decision",
  todo: "To-do",
  risk: "Risk",
  paragraph: "Paragraph",
  resource: "Document",
  document: "Document",
  file: "Document",
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
  refreshTree: () => Promise<unknown>;
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
  onRefresh: () => Promise<unknown>;
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
  const { locale } = useI18n();
  const u = (tw: string, cn: string, en: string) => msg(locale, {"zh-TW":tw,"zh-CN":cn,en});
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
    if (!confirm(u(`確定刪除內容區塊「${label}」？此動作不可復原。`, `确定删除内容区块“${label}”吗？此操作无法撤销。`, `Delete content block “${label}”? This cannot be undone.`))) return;
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
            <button type="button" onClick={remove} className="text-xs text-red-400 hover:text-red-300">{u('🗑️ 刪除','🗑️ 删除','🗑️ Delete')}</button>
          </div>
        </div>
        <input
          value={editTitle}
          onChange={(e) => { setEditTitle(e.target.value); setDirty(true); }}
          className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-gray-200"
          placeholder={u("標題", "标题", "Title")}
        />
        <textarea
          value={editBody}
          onChange={(e) => { setEditBody(e.target.value); setDirty(true); }}
          className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-sm text-gray-300 min-h-[60px]"
          placeholder={u("內容", "内容", "Content")}
        />
        {dirty && (
          <button onClick={save} className="text-sm px-2 py-1 bg-green-700 hover:bg-green-600 text-white rounded">
            {u('💾 儲存','💾 保存','💾 Save')}
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
  const { locale } = useI18n();
  const u = (tw: string, cn: string, en: string) => msg(locale, {"zh-TW":tw,"zh-CN":cn,en});
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
    if (!confirm(u(`確定將方案線「${currentBranch.name}」合併到選定主線節點？\n\n合併後方案線會結束，並把整個方案子樹接到目標節點下方。`, `确定将方案线“${currentBranch.name}”合并到所选主线节点吗？\n\n合并后方案线将结束，并把整个方案子树连接到目标节点下方。`, `Merge scenario “${currentBranch.name}” into the selected main-line node?\n\nThe scenario will end and its entire subtree will be attached below the target node.`))) return;
    await mergeBranch(currentBranch.id, mergeTargetId);
    setShowBranchReview(false);
  };

  const moveBlock = async (index: number, direction: -1 | 1) => {
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= blocks.length) return;

    try {
      // The backend atomically moves the whole interval and owns sibling revisions.
      // Send exactly one PATCH, then replace local state with authoritative order.
      const result = await reorderBlockAuthoritatively(
        blocks, index, direction,
        (blockId, orderIndex) => api.updateBlock(blockId, { order_index: orderIndex }),
        async () => {
          const projectId = selectedNode.project_id;
          const [project, node, authoritativeBlocks] = await Promise.all([
            api.getProject(projectId, false),
            api.getNode(selectedNode.id, false),
            api.getBlocks(selectedNode.id, false),
          ]);
          return { project, node, blocks: authoritativeBlocks as ContentBlockItem[] };
        },
        ({ project, node, blocks: rows }) => {
          api.rememberResponse([project, node, rows]);
          setBlocks(rows);
        },
        () => api.invalidateBlockOwner(selectedNode.id),
      );
      if (result.moved) {
        // Owner CAS and blocks are already coherent. A broader tree refresh is
        // best-effort and must not relabel the committed reorder as a failure.
        try { await refreshTree(); } catch { /* coherent owner snapshot remains valid */ }
      }
    } catch (error) {
      if (error instanceof Error && error.message === "CONTENT_REORDER_SAVED_REFRESH_FAILED") {
        alert(u("內容順序已儲存，但重新載入失敗；請重新整理後再編輯。", "内容顺序已保存，但重新加载失败；请刷新后再编辑。", "Content order was saved, but reload failed. Refresh before editing again."));
      } else {
        alert(u(`調整內容區塊順序失敗：${error instanceof Error ? error.message : "未知錯誤"}`,`调整内容区块顺序失败：${error instanceof Error ? error.message : "未知错误"}`,`Failed to reorder content blocks: ${error instanceof Error ? error.message : "Unknown error"}`));
      }
    }
  };

  const handleAddDoc = async () => {
    if (!newDocTitle.trim() && !newDocUrl.trim()) {
      alert(u('請至少輸入文件標題或 URL','请至少输入文件标题或 URL','Enter at least a document title or URL'));
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
      alert(u(`新增綁定文件失敗：${error instanceof Error ? error.message : '未知錯誤'}`,`新增绑定文件失败：${error instanceof Error ? error.message : '未知错误'}`,`Failed to attach document: ${error instanceof Error ? error.message : 'Unknown error'}`));
    }
  };

  const handleRemoveDoc = async (doc: BoundDoc) => {
    if (!doc.id) return;
    const label = doc.title || doc.name || doc.filename || doc.url || u("文件", "文件", "Document");
    if (!confirm(u(`確定移除綁定文件「${label}」？`,`确定移除绑定文件“${label}”吗？`,`Remove attached document “${label}”?`))) return;
    try {
      await api.deleteBlock(doc.id);
      setBlocks((prev) => prev.filter((block) => block.id !== doc.id));
      await refreshTree();
    } catch (error) {
      alert(u(`移除綁定文件失敗：${error instanceof Error ? error.message : '未知錯誤'}`,`移除绑定文件失败：${error instanceof Error ? error.message : '未知错误'}`,`Failed to remove attached document: ${error instanceof Error ? error.message : 'Unknown error'}`));
    }
  };

  const handleCreateBlock = async () => {
    if (!newBlockBody.trim() && !newBlockTitle.trim()) {
      alert(u('請至少輸入標題或內容','请至少输入标题或内容','Enter at least a title or content'));
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
      alert(u(`新增內容區塊失敗：${error instanceof Error ? error.message : '未知錯誤'}`,`新增内容区块失败：${error instanceof Error ? error.message : '未知错误'}`,`Failed to add content block: ${error instanceof Error ? error.message : 'Unknown error'}`));
    }
  };

  return (
    <div className="space-y-3">
      {currentBranch && (
        <div className="rounded-xl border border-purple-800/50 bg-purple-950/25 px-4 py-3 text-sm text-purple-100">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="font-semibold">{u('🔀 方案線模式：','🔀 方案线模式：','🔀 Scenario mode: ')}{currentBranch.name}</div>
              <p className="mt-1 text-xs leading-5 text-purple-200/70">
                {u('這是平行方案，不會直接改動主線。確認方向可合併回原本開出的主線節點。','这是平行方案，不会直接改动主线。确认方向后可合并回原先分出的主线节点。','This is a parallel scenario and does not directly change the main line. Once confirmed, merge it back into its source main-line node.')}
              </p>
            </div>
            <button
              type="button"
              onClick={openBranchReview}
              disabled={branchLoading}
              className="shrink-0 rounded-lg border border-purple-500/50 bg-purple-700/40 px-3 py-1.5 text-xs text-purple-100 hover:bg-purple-600/50 disabled:opacity-50"
            >
              {branchLoading ? u("讀取中…", "加载中…", "Loading…") : u("檢視並合併", "查看并合并", "Review and merge")}
            </button>
          </div>
        </div>
      )}

      <Section title={u("內容工作區", "内容工作区", "Content workspace")} subtitle={u("正式欄位與內容區塊分開保存；此處不會自動遷移或複製內容。", "正式字段与内容区块分开保存；此处不会自动迁移或复制内容。", "Formal fields and content blocks are stored separately; content is never migrated or copied automatically.")} tone={editing ? "edit" : "neutral"}>
        <div className="space-y-4">
          <div>
            <label className="text-sm text-gray-500 uppercase tracking-wider">{u('成熟度','成熟度','Maturity')}</label>
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
            <label className="text-sm text-gray-500 uppercase tracking-wider">{u('摘要','摘要','Summary')}</label>
            {editing ? (
              <textarea
                value={editSummary}
                onChange={(e) => setEditSummary(e.target.value)}
                className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-sm text-gray-200 mt-1 min-h-[96px]"
              />
            ) : (
              <div className="mt-2 rounded-xl border border-gray-800 bg-gray-900/50 p-4">
                <p className="text-base leading-7 text-gray-300 whitespace-pre-wrap">
                  {selectedNode.summary || u("（無摘要）", "（无摘要）", "(No summary)")}
                </p>
              </div>
            )}
          </div>

          <div className="space-y-3 rounded-xl border border-gray-700/80 bg-gray-900/35 p-3">
            <div>
              <label className="text-sm text-gray-300 uppercase tracking-wider">{u('節點正式欄位','节点正式字段','Formal node fields')}</label>
              <p className="mt-1 text-xs text-gray-500">{u('直接對應後端 nodes 欄位；空值仍會明示，不會偽裝成內容區塊。','直接对应后端 nodes 字段；空值仍会明确显示，不会伪装成内容区块。','Maps directly to backend node fields; empty values remain explicit and are never presented as content blocks.')}</p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <label className="text-xs text-gray-500">{u('節點狀態','节点状态','Node status')}
                {editing ? (
                  <input value={editFields.status} onChange={(e) => setEditFields((prev) => ({ ...prev, status: e.target.value }))} className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200" />
                ) : <div className="mt-1 text-sm text-gray-300">{selectedNode.status || u("（未填）", "（未填写）", "(Not provided)")}</div>}
              </label>
              <label className="text-xs text-gray-500">{u('工作流狀態','工作流状态','Workflow status')}
                {editing ? (
                  <input value={editFields.workflow_status} onChange={(e) => setEditFields((prev) => ({ ...prev, workflow_status: e.target.value }))} className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200" />
                ) : <div className="mt-1 text-sm text-gray-300">{selectedNode.workflow_status || u("（未填）", "（未填写）", "(Not provided)")}</div>}
              </label>
              <label className="text-xs text-gray-500">{u('優先級','优先级','Priority')}
                {editing ? (
                  <input type="number" value={editFields.priority} onChange={(e) => setEditFields((prev) => ({ ...prev, priority: Number(e.target.value) }))} className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200" />
                ) : <div className="mt-1 text-sm text-gray-300">{selectedNode.priority ?? u("（未填）", "（未填写）", "(Not provided)")}</div>}
              </label>
              <label className="text-xs text-gray-500">{u('信心值','信心值','Confidence')}
                {editing ? (
                  <input type="number" min="0" max="1" step="0.01" value={editFields.confidence} onChange={(e) => setEditFields((prev) => ({ ...prev, confidence: Number(e.target.value) }))} className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200" />
                ) : <div className="mt-1 text-sm text-gray-300">{selectedNode.confidence ?? u("（未填）", "（未填写）", "(Not provided)")}</div>}
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
                    {selectedNode[key] || u("（未填）", "（未填写）", "(Not provided)")}
                  </div>
                )}
              </div>
            ))}

            <div>
              <label className="text-xs text-gray-500">{u('檔案路徑（每行一筆）','文件路径（每行一条）','File paths (one per line)')}</label>
              {editing ? (
                <textarea
                  value={editFields.file_paths.join("\n")}
                  onChange={(e) => setEditFields((prev) => ({ ...prev, file_paths: e.target.value.split("\n").map((path) => path.trim()).filter(Boolean) }))}
                  className="mt-1 min-h-[72px] w-full rounded border border-gray-700 bg-gray-900 p-2 font-mono text-xs text-gray-200"
                  placeholder={u("（未填）", "（未填写）", "(Not provided)")}
                />
              ) : (selectedNode.file_paths || []).length > 0 ? (
                <ul className="mt-1 space-y-1 rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-2 font-mono text-xs text-gray-300">
                  {(selectedNode.file_paths || []).map((path, index) => <li key={`${path}-${index}`} className="break-all">{path}</li>)}
                </ul>
              ) : <div className="mt-1 text-sm text-gray-500">{u('（未填）','（未填写）','(Not provided)')}</div>}
            </div>
          </div>

          <div className="space-y-3 border-t border-gray-800 pt-4">
            <div>
              <label className="text-sm text-gray-500 uppercase tracking-wider">{u('📄 內容區塊','📄 内容区块','📄 Content blocks')}</label>
              <p className="mt-1 text-xs text-gray-600">{u('獨立的 content_blocks 記錄，不與上方正式欄位互相轉換。','独立的 content_blocks 记录，不与上方正式字段相互转换。','Independent content_blocks records; they are not converted to or from the formal fields above.')}</p>
            </div>

            {editing && (
              <div className="rounded-xl border border-blue-900/40 bg-blue-950/20 p-3 space-y-2">
                <div className="flex gap-2">
                  <select
                    value={newBlockType}
                    onChange={(e) => setNewBlockType(e.target.value)}
                    className="bg-gray-800 border border-gray-700 rounded-md px-2 py-1.5 text-xs text-gray-200"
                  >
                    <option value="note">{u('筆記','笔记','Note')}</option>
                    <option value="spec">{u('規格','规格','Specification')}</option>
                    <option value="decision">{u('決策','决策','Decision')}</option>
                    <option value="todo">{u('待辦','待办','To-do')}</option>
                    <option value="risk">{u('風險','风险','Risk')}</option>
                  </select>
                  <input
                    value={newBlockTitle}
                    onChange={(e) => setNewBlockTitle(e.target.value)}
                    placeholder={u("區塊標題（選填）", "区块标题（可选）", "Block title (optional)")}
                    className="flex-1 bg-gray-900 border border-gray-700 rounded-md px-2.5 py-1.5 text-sm text-gray-200"
                  />
                </div>
                <textarea
                  value={newBlockBody}
                  onChange={(e) => setNewBlockBody(e.target.value)}
                  placeholder={u("輸入內容區塊...", "输入内容区块...", "Enter block content…")}
                  className="w-full bg-gray-900 border border-gray-700 rounded-md px-2.5 py-2 text-sm text-gray-200 min-h-[72px]"
                />
                <button
                  type="button"
                  onClick={handleCreateBlock}
                  disabled={!newBlockBody.trim() && !newBlockTitle.trim()}
                  className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm"
                >
                  {u('+ 新增內容區塊','+ 新增内容区块','+ Add content block')}
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
                {u('尚無內容區塊。','暂无内容区块。','No content blocks yet.')}
              </div>
            )}
          </div>

          <div className="space-y-3">
            <label className="text-sm text-gray-500 uppercase tracking-wider">{u('📎 已綁定文件','📎 已绑定文件','📎 Attached documents')}</label>

            <div className="rounded-xl border border-gray-800 bg-gray-900/40 p-3 space-y-2">
                <div className="flex gap-2">
                  <input
                    value={newDocTitle}
                    onChange={(e) => setNewDocTitle(e.target.value)}
                    placeholder={u("文件標題", "文件标题", "Document title")}
                    className="flex-1 bg-gray-900 border border-gray-700 rounded-md px-2.5 py-1.5 text-sm text-gray-200"
                  />
                  <input
                    value={newDocUrl}
                    onChange={(e) => setNewDocUrl(e.target.value)}
                    placeholder={u("URL / 路徑", "URL / 路径", "URL / path")}
                    className="flex-1 bg-gray-900 border border-gray-700 rounded-md px-2.5 py-1.5 text-sm text-gray-200"
                  />
                </div>
                <input
                  value={newDocSummary}
                  onChange={(e) => setNewDocSummary(e.target.value)}
                  placeholder={u("文件摘要（選填）", "文件摘要（可选）", "Document summary (optional)")}
                  className="w-full bg-gray-900 border border-gray-700 rounded-md px-2.5 py-1.5 text-sm text-gray-200"
                />
                <button
                  type="button"
                  onClick={handleAddDoc}
                  disabled={!newDocTitle.trim() && !newDocUrl.trim()}
                  className="px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 disabled:text-gray-600 text-white text-sm"
                >
                  {u('+ 綁定文件','+ 绑定文件','+ Attach document')}
                </button>
              </div>

            {boundDocs.length > 0 ? (
              <div className="space-y-2">
                {boundDocs.map((doc, index) => {
                  const label = doc.title || doc.name || doc.filename || u(`文件 ${index + 1}`,`文件 ${index + 1}`,`Document ${index + 1}`);
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
                              {u('開啟','打开','Open')}
                            </a>
                          )}
                          {editing && doc.id && (
                            <button
                              type="button"
                              onClick={() => handleRemoveDoc(doc)}
                              className="text-xs text-red-400 hover:text-red-300"
                            >
                              {u('移除','移除','Remove')}
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
                {u('尚無綁定文件。','暂无绑定文件。','No attached documents.')}
              </div>
            )}
          </div>
        </div>
      </Section>

      <Section title={u("內容工具", "内容工具", "Content tools")} subtitle={u("主線內容擴寫：直接新增到目前路徑。", "主线内容扩写：直接新增到当前路径。", "Extend main-line content by adding directly to the current path.")} tone="edit">
        <div>
          <label className="text-sm text-gray-500 uppercase tracking-wider">{u('主線新增節點','主线新增节点','Add main-line node')}</label>
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
              placeholder={u("輸入節點標題...", "输入节点标题...", "Enter node title…")}
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

      <Section title={u("方案工具", "方案工具", "Scenario tools")} subtitle={currentBranch ? u("目前在方案線中；可上方合併回主線，或到設定刪除方案線。", "当前位于方案线中；可在上方合并回主线，或到设置中删除方案线。", "You are in a scenario; merge it into the main line above, or delete it under Settings.") : u("用來開平行方案線（分支），不是主線擴寫。", "用于创建平行方案线（分支），不是扩写主线。", "Create a parallel scenario (branch), not a main-line extension.")} tone="neutral">
        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between">
              <div className="text-sm text-gray-500 uppercase tracking-wider">{u('子節點','子节点','Child nodes')}</div>
              {hasChildren && (
                <button
                  type="button"
                  onClick={() => { setBranchName(""); setBranchDesc(""); setShowBranchModal(true); }}
                  className="text-xs px-2.5 py-1 rounded border border-purple-700/50 bg-purple-950/30 text-purple-300 hover:bg-purple-900/40"
                >
                  {u('🔀 開新方案線','🔀 新建方案线','🔀 New scenario')}
                </button>
              )}
            </div>
            <p className="text-base text-gray-400 mt-1">{selectedNode.children?.length || 0} {u('個','个','items')}</p>
            <p className="text-[11px] text-gray-500 mt-0.5">{u('建立後可在頂欄「🌿 main」旁的分支下拉切換。','创建后可在顶栏“🌿 main”旁的分支下拉菜单中切换。','After creation, switch from the branch menu beside “🌿 main” in the top bar.')}</p>
            {hasChildren ? (
              <div className="mt-2.5 space-y-1.5">
                {selectedNode.children?.map((child) => (
                  <div key={child.id} className="flex items-center justify-between gap-2.5 rounded-lg border border-gray-800 bg-gray-900/55 px-3 py-1.5">
                    <div className="min-w-0">
                      <div className="text-sm text-gray-100 font-medium flex items-center gap-2">
                        <span className="truncate">{child.title}</span>
                        {child.is_mainline && <span className="text-xs text-blue-300 border border-blue-500/40 rounded-full px-1.5 py-0.5">{u('主線','主线','Main line')}</span>}
                      </div>
                      <div className="text-[11px] text-gray-500 truncate mt-0.5">{child.summary || child.node_type}</div>
                    </div>
                    {!child.is_mainline && (
                      <button
                        type="button"
                        onClick={() => onPromoteMainline(selectedNode.id, child.id)}
                        className="shrink-0 text-sm px-2.5 py-1 rounded border border-blue-700/50 bg-blue-950/30 text-blue-300 hover:bg-blue-900/40"
                      >
                        {u('設為主線','设为主线','Set as main line')}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-3 rounded-lg border border-dashed border-gray-800/80 bg-gray-900/20 px-3.5 py-4 text-sm text-gray-500">
                {u('尚無子節點。','暂无子节点。','No child nodes.')}
              </div>
            )}
          </div>
        </div>
      </Section>

      {showBranchReview && currentBranch && branchComparison && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 px-4" onClick={() => setShowBranchReview(false)}>
          <div className="w-full max-w-lg space-y-4 rounded-xl border border-purple-800/60 bg-[#111] p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div>
              <h3 className="text-sm font-semibold text-gray-100">{u('🔎 方案線檢視：','🔎 方案线查看：','🔎 Scenario review: ')}{currentBranch.name}</h3>
              <p className="mt-1 text-xs text-gray-500">{u('比較目前方案根節點與開出來源；確認目標後才會合併。','比较当前方案根节点与来源；确认目标后才会合并。','Compare the scenario root with its source; merging occurs only after you confirm the target.')}</p>
            </div>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
                <div className="text-gray-500">{u('來源主線','来源主线','Source main line')}</div>
                <div className="mt-1 font-medium text-gray-200">{branchComparison.source?.title || u("來源已不存在", "来源已不存在", "Source no longer exists")}</div>
                <div className="mt-1 text-gray-500">{u('內容區塊','内容区块','Content blocks')} {branchComparison.diff.source_block_count}</div>
              </div>
              <div className="rounded-lg border border-purple-800/50 bg-purple-950/20 p-3">
                <div className="text-purple-300/70">{u('方案根節點','方案根节点','Scenario root')}</div>
                <div className="mt-1 font-medium text-purple-100">{branchComparison.branch_root?.title || u("無方案根節點", "无方案根节点", "No scenario root")}</div>
                <div className="mt-1 text-purple-200/60">{u('節點','节点','Nodes')} {branchComparison.diff.branch_node_count} · {u('內容區塊','内容区块','Content blocks')} {branchComparison.diff.branch_block_count}</div>
              </div>
            </div>
            <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-3 text-xs text-gray-400">
              <div className="mb-1 text-gray-300">{u('差異摘要','差异摘要','Difference summary')}</div>
              <div className="flex flex-wrap gap-2">
                <span className={branchComparison.diff.title_changed ? "text-amber-300" : "text-gray-600"}>{u('標題','标题','Title')}{branchComparison.diff.title_changed ? u('已變更','已更改',' changed') : u('未變更','未更改',' unchanged')}</span>
                <span className={branchComparison.diff.summary_changed ? "text-amber-300" : "text-gray-600"}>{u('摘要','摘要','Summary')}{branchComparison.diff.summary_changed ? u('已變更','已更改',' changed') : u('未變更','未更改',' unchanged')}</span>
                <span className={branchComparison.diff.maturity_changed ? "text-amber-300" : "text-gray-600"}>{u('成熟度','成熟度','Maturity')}{branchComparison.diff.maturity_changed ? u('已變更','已更改',' changed') : u('未變更','未更改',' unchanged')}</span>
              </div>
            </div>
            <label className="block text-xs text-gray-400">
              {u('合併到主線節點','合并到主线节点','Merge into main-line node')}
              <select value={mergeTargetId} onChange={(e) => setMergeTargetId(e.target.value)} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100 focus:border-purple-500 focus:outline-none">
                {mergeTargets.map((target) => <option key={target.id} value={target.id}>{"  ".repeat(target.ancestor_path?.length || 0)}{target.title}</option>)}
              </select>
            </label>
            <div className="flex gap-2">
              <button type="button" onClick={handleMergeCurrentBranch} disabled={!mergeTargetId || branchLoading} className="flex-1 rounded-lg bg-purple-700 px-3 py-2 text-sm text-white hover:bg-purple-600 disabled:bg-gray-700">{u('確認合併','确认合并','Confirm merge')}</button>
              <button type="button" onClick={() => setShowBranchReview(false)} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-300">{u('取消','取消','Cancel')}</button>
            </div>
          </div>
        </div>
      )}

      {showBranchModal && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center" onClick={() => setShowBranchModal(false)}>
          <div className="bg-[#111] border border-gray-700 rounded-xl p-5 w-72 space-y-3" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-gray-200">{u('🔀 開新方案線','🔀 新建方案线','🔀 New scenario')}</h3>
            <input
              value={branchName}
              onChange={(e) => setBranchName(e.target.value)}
              placeholder={u("方案線名稱（例：方案B：微服務架構）", "方案线名称（例：方案B：微服务架构）", "Scenario name (e.g. Option B: microservices)")}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:border-purple-500 focus:outline-none"
            />
            <input
              value={branchDesc}
              onChange={(e) => setBranchDesc(e.target.value)}
              placeholder={u("描述（選填）", "描述（可选）", "Description (optional)")}
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
                {u('建立','创建','Create')}
              </button>
              <button
                type="button"
                onClick={() => setShowBranchModal(false)}
                className="px-3 py-2 text-gray-500 hover:text-gray-300 text-sm"
              >
                {u('取消','取消','Cancel')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
