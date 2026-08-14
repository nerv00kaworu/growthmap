import { create } from "zustand";
import { activeMsg } from "@/i18n/ui";
const ui=(tw:string,cn:string,en:string)=>activeMsg({"zh-TW":tw,"zh-CN":cn,en});
import type { GNode, GrowthMode, Project, Branch, BranchComparison } from "@/lib/types";
import { api } from "@/lib/api";
import { runMutationWithConflict, type ConflictState } from "@/lib/conflict";
import {
  findNode,
  insertChild,
  markMainlineChild,
  patchNode,
  pushUndo,
  removeNode,
  searchNodes,
  type UndoEntry,
} from "./tree-utils";

function advanceProjectRevision(set: (partial: Partial<GrowthMapStore>) => void, project: Project, authoritative?: number) {
  const updated = { ...project, revision: authoritative ?? project.revision + 1 };
  set({ currentProject: updated, projects: useStore.getState().projects.map((row) => row.id === updated.id ? updated : row) });
}

function applyCreateRevisions(set: (partial: Partial<GrowthMapStore>) => void, project: Project, tree: GNode, created: GNode): GNode {
  advanceProjectRevision(set, project, created.authoritative_project_revision);
  if (created.authoritative_parent_id && created.authoritative_parent_revision) {
    return patchNode(tree, created.authoritative_parent_id, { revision: created.authoritative_parent_revision } as Partial<GNode>);
  }
  return tree;
}

interface GrowthMapStore {
  // State
  projects: Project[];
  currentProject: Project | null;
  rootNode: GNode | null;
  selectedNodeId: string | null;
  selectedNode: GNode | null;
  loading: boolean;
  error: string | null;
  conflict: ConflictState | null;

  // Undo
  undoStack: UndoEntry[];
  toast: string | null;

  // Search
  searchQuery: string;
  highlightedNodeIds: string[];

  // Branches
  branches: Branch[];
  currentBranch: Branch | null;
  branchComparison: BranchComparison | null;
  branchLoading: boolean;

  // Actions
  loadProjects: () => Promise<void>;
  selectProject: (project: Project) => Promise<void>;
  selectNode: (nodeId: string | null) => void;
  createProject: (name: string, description?: string, goal?: string) => Promise<void>;
  addChildNode: (parentId: string, title: string, nodeType?: string) => Promise<void>;
  updateNode: (nodeId: string, data: Partial<GNode>) => Promise<void>;
  deleteNode: (nodeId: string) => Promise<void>;
  refreshTree: () => Promise<void>;
  promoteMainlineChild: (parentId: string, childId: string) => Promise<void>;
  reparentNode: (nodeId: string, newParentId: string) => Promise<void>;
  undo: () => void;
  setSearchQuery: (q: string) => void;
  setToast: (msg: string | null) => void;

  // Branch actions
  loadBranches: (projectId: string) => Promise<void>;
  createBranch: (sourceNodeId: string, name: string, description?: string) => Promise<void>;
  selectBranch: (branch: Branch | null) => Promise<void>;
  compareBranch: (branchId: string) => Promise<BranchComparison | null>;
  archiveBranch: (branchId: string) => Promise<void>;
  mergeBranch: (branchId: string, targetNodeId: string) => Promise<void>;

  // AI
  expandSuggestions: { title: string; summary: string; node_type: string }[] | null;
  expandTargetNodeId: string | null;
  deepenResult: { enriched_summary: string; content_blocks: { title: string; body: string; block_type: string }[]; target_node_id: string } | null;
  aiLoading: boolean;
  expandNode: (nodeId: string, instruction?: string, mode?: GrowthMode) => Promise<void>;
  deepenNode: (nodeId: string, instruction?: string) => Promise<void>;
  acceptSuggestion: (index: number) => Promise<void>;
  ignoreSuggestion: (index: number) => void;
  acceptAllSuggestions: () => Promise<void>;
  acceptDeepen: () => Promise<void>;
  acceptDeepenSummary: () => Promise<void>;
  acceptDeepenBlock: (index: number) => Promise<void>;
  ignoreDeepenBlock: (index: number) => void;
  dismissAI: () => void;
}

export const useStore = create<GrowthMapStore>((set, get) => ({
  projects: [],
  currentProject: null,
  rootNode: null,
  selectedNodeId: null,
  selectedNode: null,
  loading: false,
  error: null,
  conflict: null,
  expandSuggestions: null,
  expandTargetNodeId: null,
  deepenResult: null,
  aiLoading: false,
  undoStack: [],
  toast: null,
  searchQuery: "",
  highlightedNodeIds: [],
  branches: [],
  currentBranch: null,
  branchComparison: null,
  branchLoading: false,

  loadProjects: async () => {
    try {
      const projects = await api.listProjects();
      set({ projects });
    } catch (e: unknown) {
      set({ error: (e as Error).message });
    }
  },

  selectProject: async (project) => {
    set({ loading: true, currentProject: project, selectedNodeId: null, selectedNode: null, undoStack: [], currentBranch: null, branches: [], branchComparison: null });
    try {
      const rootNode = await api.getSubtree(project.root_node_id);
      set({ rootNode, loading: false });
      // Load branches in background
      get().loadBranches(project.id);
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  selectNode: (nodeId) => {
    const { rootNode } = get();
    const selectedNode = nodeId && rootNode ? findNode(rootNode, nodeId) : null;
    set({ selectedNodeId: nodeId, selectedNode });
  },

  createProject: async (name, description, goal) => {
    const project = await api.createProject({ name, description, goal });
    const { projects } = get();
    set({ projects: [...projects, project] });
    await get().selectProject(project);
  },

  addChildNode: async (parentId, title, nodeType) => {
    const { currentProject, rootNode } = get();
    if (!currentProject || !rootNode) return;
    const { undoStack } = get();
    const newUndoStack = pushUndo(undoStack, rootNode, ui(`新增子節點: ${title}`,`新增子节点: ${title}`,`Add child node: ${title}`));
    const outcome = await runMutationWithConflict(
      () => api.createNode(currentProject.id, {
        title,
        parent_id: parentId,
        branch_id: get().currentBranch?.id,
        node_type: nodeType,
      }),
      () => get().refreshTree(),
      { nodeDraft: title },
    );
    if (outcome.conflict) { set({ conflict: outcome.conflict, error: outcome.conflict.message }); return; }
    const newNode = outcome.value!;
    const child: GNode = {
      id: newNode.id,
      title: newNode.title,
      summary: newNode.summary || "",
      node_type: newNode.node_type || "idea",
      maturity: newNode.maturity || "seed",
      priority: newNode.priority ?? 0,
      confidence: newNode.confidence ?? 0.5,
      description: newNode.description || "",
      rules_text: newNode.rules_text || "",
      constraints_text: newNode.constraints_text || "",
      examples_text: newNode.examples_text || "",
      questions_text: newNode.questions_text || "",
      decision_notes: newNode.decision_notes || "",
      workflow_status: newNode.workflow_status || "draft",
      tags: newNode.tags || [],
      file_paths: newNode.file_paths || [],
      created_by: newNode.created_by || "human",
      last_edited_by: newNode.last_edited_by || "human",
      position_x: newNode.position_x ?? 0,
      position_y: newNode.position_y ?? 0,
      meta: {},
      project_id: currentProject.id,
      status: newNode.status || "active",
      content_blocks: [],
      children: [],
      created_at: newNode.created_at || "",
      updated_at: newNode.updated_at || "",
      revision: newNode.revision || 1,
    };
    const updated = applyCreateRevisions(set, currentProject, insertChild(rootNode, parentId, child), newNode);
    set({ rootNode: updated, undoStack: newUndoStack });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  updateNode: async (nodeId, data) => {
    const { rootNode, undoStack, currentProject } = get();
    const existing = rootNode ? findNode(rootNode, nodeId) : null;
    if (!currentProject || !existing) return;
    if (rootNode) {
      const newUndoStack = pushUndo(undoStack, rootNode, ui('更新節點','更新节点','Update node'));
      set({ undoStack: newUndoStack });
    }
    const saved = await api.updateNode(nodeId, { ...data, expected_project_revision: currentProject.revision, expected_revision: existing.revision });
    if (!rootNode) return;
    const updated = patchNode(rootNode, nodeId, saved);
    advanceProjectRevision(set, currentProject);
    set({ rootNode: updated });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  deleteNode: async (nodeId) => {
    const { rootNode, undoStack, selectedNodeId, currentProject } = get();
    const existing = rootNode ? findNode(rootNode, nodeId) : null;
    if (!currentProject || !existing) return;
    if (rootNode) {
      const node = findNode(rootNode, nodeId);
      const newUndoStack = pushUndo(undoStack, rootNode, ui(`刪除節點: ${node?.title || nodeId}`,`删除节点: ${node?.title || nodeId}`,`Delete node: ${node?.title || nodeId}`));
      set({ undoStack: newUndoStack });
    }
    await api.deleteNode(nodeId, currentProject.revision, existing.revision);
    advanceProjectRevision(set, currentProject);
    if (!rootNode) return;
    const updated = removeNode(rootNode, nodeId);
    set({ rootNode: updated });
    if (selectedNodeId === nodeId) {
      set({ selectedNodeId: null, selectedNode: null });
    } else if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  refreshTree: async () => {
    const { currentProject } = get();
    if (!currentProject) return;
    const { currentBranch } = get();
    const rootNode = currentBranch
      ? (await api.getBranchSubtree(currentBranch.id)).tree
      : await api.getSubtree(currentProject.root_node_id);
    set({ rootNode });
    const { selectedNodeId } = get();
    if (selectedNodeId && rootNode) {
      set({ selectedNode: findNode(rootNode, selectedNodeId) });
    }
  },

  promoteMainlineChild: async (parentId, childId) => {
    const { rootNode, currentProject } = get();
    if (!rootNode || !currentProject) return;
    const child = findNode(rootNode, childId);
    const edgeRevision = typeof child?.meta?.edge_revision === "number" ? child.meta.edge_revision : 1;
    await api.promoteChildMainline(parentId, childId, currentProject.revision, edgeRevision);
    advanceProjectRevision(set, currentProject);
    const updated = markMainlineChild(rootNode, parentId, childId);
    set({ rootNode: updated });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  reparentNode: async (nodeId, newParentId) => {
    const { rootNode, undoStack } = get();
    if (!rootNode) return;
    const node = findNode(rootNode, nodeId);
    const newUndoStack = pushUndo(undoStack, rootNode, ui(`移動節點: ${node?.title || nodeId}`,`移动节点: ${node?.title || nodeId}`,`Move node: ${node?.title || nodeId}`));
    set({ undoStack: newUndoStack });
    try {
      const currentProject = get().currentProject;
      const newParent = findNode(rootNode, newParentId);
      const oldParent = (() => {
        const walk = (candidate: GNode): GNode | null => candidate.children?.some((child) => child.id === nodeId)
          ? candidate : (candidate.children || []).map(walk).find(Boolean) || null;
        return walk(rootNode);
      })();
      if (!currentProject || !node || !newParent || !oldParent) return;
      const response = await fetch(`/api/nodes/${nodeId}/reparent`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_parent_id: newParentId, expected_project_revision: currentProject.revision,
          expected_revision: node.revision, expected_new_parent_revision: newParent.revision,
          expected_old_parent_revision: oldParent.revision }),
      });
      if (!response.ok) throw new Error(`API ${response.status}: ${await response.text()}`);
      advanceProjectRevision(set, currentProject);
      await get().refreshTree();
    } catch (e: unknown) {
      set({ error: (e as Error).message });
    }
  },

  undo: () => {
    const { undoStack } = get();
    if (undoStack.length === 0) return;
    const [entry, ...rest] = undoStack;
    set({ rootNode: entry.rootNode, undoStack: rest, toast: ui(`已復原: ${entry.description}`,`已恢复: ${entry.description}`,`Restored: ${entry.description}`) });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(entry.rootNode, selectedNodeId) });
    }
  },

  setSearchQuery: (q) => {
    const { rootNode } = get();
    const highlightedNodeIds = rootNode ? searchNodes(rootNode, q) : [];
    set({ searchQuery: q, highlightedNodeIds });
  },

  setToast: (msg) => set({ toast: msg }),

  // Branch actions
  loadBranches: async (projectId) => {
    try {
      const branches = await api.listBranches(projectId);
      set({ branches });
    } catch (e: unknown) {
      console.error("Failed to load branches:", e);
    }
  },

  createBranch: async (sourceNodeId, name, description) => {
    const { currentProject } = get();
    if (!currentProject) return;
    try {
      const branch = await api.createBranch(currentProject.id, { expected_project_revision: currentProject.revision, source_node_id: sourceNodeId, name, description });
      advanceProjectRevision(set, currentProject);
      const { branches } = get();
      set({ branches: [...branches, branch], toast: ui(`✅ 方案線「${name}」已建立`,`✅ 方案线“${name}”已创建`,`✅ Scenario “${name}” created`) });
      await get().selectBranch(branch);
    } catch (e: unknown) {
      set({ error: (e as Error).message });
    }
  },

  selectBranch: async (branch) => {
    const { currentProject } = get();
    if (!currentProject) return;
    set({ loading: true, branchLoading: true, selectedNodeId: null, selectedNode: null, branchComparison: null });
    try {
      if (!branch) {
        const rootNode = await api.getSubtree(currentProject.root_node_id);
        set({ currentBranch: null, rootNode, loading: false, branchLoading: false });
        return;
      }
      const result = await api.getBranchSubtree(branch.id);
      if (!result.tree) throw new Error(ui('方案線沒有可顯示的根節點','方案线没有可显示的根节点','This scenario has no displayable root node.'));
      set({ currentBranch: branch, rootNode: result.tree, loading: false, branchLoading: false });
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false, branchLoading: false });
    }
  },

  compareBranch: async (branchId) => {
    set({ branchLoading: true });
    try {
      const branchComparison = await api.compareBranch(branchId);
      set({ branchComparison, branchLoading: false });
      return branchComparison;
    } catch (e: unknown) {
      set({ error: (e as Error).message, branchLoading: false });
      return null;
    }
  },

  archiveBranch: async (branchId) => {
    try {
      const { currentProject, branches, currentBranch } = get();
      const branch = branches.find((row) => row.id === branchId);
      if (!currentProject || !branch) return;
      await api.archiveBranch(branchId, currentProject.revision, branch.revision);
      advanceProjectRevision(set, currentProject);
      const remaining = branches.filter((branch) => branch.id !== branchId);
      set({ branches: remaining, branchComparison: null, toast: ui('🗃️ 方案線已封存','🗃️ 方案线已归档','🗃️ Scenario archived') });
      if (currentBranch?.id === branchId && currentProject) {
        await get().selectBranch(null);
      }
    } catch (e: unknown) {
      set({ error: (e as Error).message });
    }
  },

  mergeBranch: async (branchId, targetNodeId) => {
    set({ branchLoading: true });
    try {
      const { currentProject, branches } = get();
      const branch = branches.find((row) => row.id === branchId);
      const target = get().rootNode ? findNode(get().rootNode!, targetNodeId) : null;
      if (!currentProject || !branch || !target) return;
      await api.mergeBranch(branchId, targetNodeId, currentProject.revision, branch.revision, target.revision);
      advanceProjectRevision(set, currentProject);
      set({
        branches: branches.filter((b) => b.id !== branchId),
        currentBranch: null,
        branchComparison: null,
        selectedNodeId: null,
        selectedNode: null,
        toast: ui('✅ 方案線已合併回主線','✅ 方案线已合并回主线','✅ Scenario merged into main line'),
      });
      if (currentProject) {
        const rootNode = await api.getSubtree(currentProject.root_node_id);
        set({ rootNode, branchLoading: false });
      } else {
        set({ branchLoading: false });
      }
    } catch (e: unknown) {
      set({ error: (e as Error).message, branchLoading: false });
    }
  },

  expandNode: async (nodeId, instruction, mode = "explore") => {
    set({ aiLoading: true, expandSuggestions: null, expandTargetNodeId: nodeId, deepenResult: null });
    try {
      const result = await api.expand(nodeId, instruction, undefined, mode);
      set({ expandSuggestions: result.suggestions, aiLoading: false });
    } catch (e: unknown) {
      set({ error: (e as Error).message, aiLoading: false });
    }
  },

  deepenNode: async (nodeId, instruction) => {
    set({ aiLoading: true, deepenResult: null, expandSuggestions: null });
    try {
      const result = await api.deepen(nodeId, instruction);
      set({ deepenResult: { ...result, target_node_id: nodeId }, aiLoading: false });
    } catch (e: unknown) {
      set({ error: (e as Error).message, aiLoading: false });
    }
  },

  acceptSuggestion: async (index) => {
    const { expandSuggestions, expandTargetNodeId, currentProject, rootNode, undoStack } = get();
    if (!expandSuggestions || !expandTargetNodeId || !currentProject || !rootNode) return;
    const newUndoStack = pushUndo(undoStack, rootNode, ui('接受 AI 建議','接受 AI 建议','Accept AI suggestion'));
    set({ undoStack: newUndoStack });
    const s = expandSuggestions[index];
    const outcome = await runMutationWithConflict(
      () => api.createNode(currentProject.id, {
        title: s.title,
        summary: s.summary,
        parent_id: expandTargetNodeId,
        branch_id: get().currentBranch?.id,
        node_type: s.node_type,
      }),
      () => get().refreshTree(),
      { suggestionInput: s.title },
    );
    if (outcome.conflict) { set({ conflict: outcome.conflict, error: outcome.conflict.message }); return; }
    const newNode = outcome.value!;
    const child: GNode = {
      ...newNode,
      summary: newNode.summary || "",
      node_type: newNode.node_type || "idea",
      maturity: newNode.maturity || "seed",
      meta: {},
      project_id: currentProject.id,
      content_blocks: [],
      children: [],
      created_at: newNode.created_at || "",
      updated_at: newNode.updated_at || "",
    };
    const updated = applyCreateRevisions(set, currentProject, insertChild(rootNode, expandTargetNodeId, child), newNode);
    const remaining = expandSuggestions.filter((_, i) => i !== index);
    set({
      rootNode: updated,
      expandSuggestions: remaining.length > 0 ? remaining : null,
      toast: ui(`✅ 已建立 AI 建議節點「${s.title}」`,`✅ 已创建 AI 建议节点“${s.title}”`,`✅ Created AI-suggested node “${s.title}”`),
    });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  ignoreSuggestion: (index) => {
    const { expandSuggestions } = get();
    if (!expandSuggestions) return;
    const remaining = expandSuggestions.filter((_, i) => i !== index);
    set({
      expandSuggestions: remaining.length > 0 ? remaining : null,
      toast: ui('已忽略一個 AI 分支建議','已忽略一个 AI 分支建议','Ignored one AI branch suggestion'),
    });
  },

  acceptAllSuggestions: async () => {
    const { expandSuggestions, expandTargetNodeId, currentProject, rootNode, undoStack } = get();
    if (!expandSuggestions || !expandTargetNodeId || !currentProject || !rootNode) return;
    if (!confirm(ui(`確定採用全部 ${expandSuggestions.length} 個 AI 分支建議？`,`确定采用全部 ${expandSuggestions.length} 个 AI 分支建议吗？`,`Accept all ${expandSuggestions.length} AI branch suggestions?`))) return;
    const newUndoStack = pushUndo(undoStack, rootNode, ui('接受全部 AI 建議','接受全部 AI 建议','Accept all AI suggestions'));
    set({ undoStack: newUndoStack });
    let tree = rootNode;
    for (const s of expandSuggestions) {
      const outcome = await runMutationWithConflict(
        () => api.createNode(currentProject.id, {
          title: s.title,
          summary: s.summary,
          parent_id: expandTargetNodeId,
          branch_id: get().currentBranch?.id,
          node_type: s.node_type,
        }),
        () => get().refreshTree(),
        { suggestionInput: s.title },
      );
      if (outcome.conflict) {
        set({ conflict: outcome.conflict, error: outcome.conflict.message });
        return;
      }
      const newNode = outcome.value!;
      tree = applyCreateRevisions(set, get().currentProject!, tree, newNode);
      const child: GNode = {
        ...newNode,
        summary: newNode.summary || "",
        node_type: newNode.node_type || "idea",
        maturity: newNode.maturity || "seed",
        meta: {},
        project_id: currentProject.id,
        content_blocks: [],
        children: [],
        created_at: newNode.created_at || "",
        updated_at: newNode.updated_at || "",
      };
      tree = insertChild(tree, expandTargetNodeId, child);
    }
    await get().refreshTree();
    set({ expandSuggestions: null, toast: ui(`✅ 已建立 ${expandSuggestions.length} 個 AI 建議節點`,`✅ 已创建 ${expandSuggestions.length} 个 AI 建议节点`,`✅ Created ${expandSuggestions.length} AI-suggested nodes`) });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(tree, selectedNodeId) });
    }
  },

  acceptDeepen: async () => {
    set({ conflict: null });
    await get().acceptDeepenSummary();
    if (get().conflict) return;
    const { deepenResult } = get();
    if (!deepenResult) return;
    for (let i = deepenResult.content_blocks.length - 1; i >= 0; i--) {
      await get().acceptDeepenBlock(i);
    }
    set({ deepenResult: null });
  },

  acceptDeepenSummary: async () => {
    const { deepenResult, rootNode, undoStack } = get();
    if (!deepenResult || !rootNode) return;
    const targetId = deepenResult.target_node_id;
    const newUndoStack = pushUndo(undoStack, rootNode, ui('接受 AI 摘要建議','接受 AI 摘要建议','Accept AI summary suggestion'));
    set({ undoStack: newUndoStack });
    const outcome = await runMutationWithConflict(
      () => api.updateNode(targetId, { summary: deepenResult.enriched_summary } as Partial<GNode>),
      () => get().refreshTree(),
      { suggestionInput: deepenResult.enriched_summary },
    );
    if (outcome.conflict) { set({ conflict: outcome.conflict, error: outcome.conflict.message }); return; }
    const updated = patchNode(rootNode, targetId, outcome.value!);
    set({ rootNode: updated, toast: ui('✅ 已套用 AI 摘要建議','✅ 已应用 AI 摘要建议','✅ Applied AI summary suggestion') });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  acceptDeepenBlock: async (index) => {
    const { deepenResult, rootNode, undoStack } = get();
    if (!deepenResult || !rootNode) return;
    const block = deepenResult.content_blocks[index];
    if (!block) return;
    const targetId = deepenResult.target_node_id;
    const newUndoStack = pushUndo(undoStack, rootNode, ui(`接受 AI 內容區塊: ${block.title}`,`接受 AI 内容区块: ${block.title}`,`Accept AI content block: ${block.title}`));
    set({ undoStack: newUndoStack });
    const outcome = await runMutationWithConflict(
      () => api.createBlock(targetId, {
        block_type: block.block_type,
        content: { title: block.title, body: block.body },
      }) as Promise<{ id: string; node_id: string; block_type: string; content: Record<string, string>; order_index: number }>,
      () => get().refreshTree(),
      { suggestionInput: `${block.title}\n${block.body}` },
    );
    if (outcome.conflict) { set({ conflict: outcome.conflict, error: outcome.conflict.message }); return; }
    const created = outcome.value!;
    const target = findNode(rootNode, targetId);
    const existingBlocks = target?.content_blocks || [];
    const updated = patchNode(rootNode, targetId, {
      content_blocks: [...existingBlocks, created],
    } as Partial<GNode>);
    const remainingBlocks = deepenResult.content_blocks.filter((_, i) => i !== index);
    set({
      rootNode: updated,
      deepenResult: remainingBlocks.length > 0 ? { ...deepenResult, content_blocks: remainingBlocks } : null,
      toast: ui('✅ 已寫入 AI 內容區塊','✅ 已写入 AI 内容区块','✅ Added AI content block'),
    });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  ignoreDeepenBlock: (index) => {
    const { deepenResult } = get();
    if (!deepenResult) return;
    const remainingBlocks = deepenResult.content_blocks.filter((_, i) => i !== index);
    set({
      deepenResult: remainingBlocks.length > 0 ? { ...deepenResult, content_blocks: remainingBlocks } : null,
      toast: ui('已忽略一個 AI 內容區塊','已忽略一个 AI 内容区块','Ignored one AI content block'),
    });
  },

  dismissAI: () => {
    set({ expandSuggestions: null, deepenResult: null });
  },
}));
