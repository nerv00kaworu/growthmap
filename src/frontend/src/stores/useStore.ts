import { create } from "zustand";
import { activeMsg } from "@/i18n/ui";
const ui=(tw:string,cn:string,en:string)=>activeMsg({"zh-TW":tw,"zh-CN":cn,en});
import type { GNode, GrowthMode, Project, Branch, BranchComparison } from "@/lib/types";
import { api, ApiError } from "@/lib/api";
import type { AIProviderIdentity } from "@/lib/ai-panel-controller";
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
  refreshTree: () => Promise<"refreshed" | "superseded">;
  promoteMainlineChild: (parentId: string, childId: string) => Promise<void>;
  reparentNode: (nodeId: string, newParentId: string) => Promise<void>;
  undo: () => Promise<void>;
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
  aiError: { code?: string; status?: number; requestId?: string; message: string; action: "expand" | "deepen"; elapsedMs: number } | null;
  clearAIError: () => void;
  invalidateAISelection: () => void;
  expandNode: (nodeId: string, identity: AIProviderIdentity, instruction?: string, mode?: GrowthMode) => Promise<void>;
  deepenNode: (nodeId: string, identity: AIProviderIdentity, instruction?: string) => Promise<void>;
  acceptSuggestion: (index: number) => Promise<void>;
  ignoreSuggestion: (index: number) => void;
  acceptAllSuggestions: () => Promise<void>;
  acceptDeepen: () => Promise<void>;
  acceptDeepenSummary: (context?: DeepenOperationContext) => Promise<OperationStepResult>;
  acceptDeepenBlock: (index: number, context?: DeepenOperationContext) => Promise<OperationStepResult>;
  ignoreDeepenBlock: (index: number) => void;
  dismissAI: () => void;
}

let projectSelectionGeneration = 0;
let projectListGeneration = 0;
let branchLoadGeneration = 0;
let branchSelectionGeneration = 0;
let treeRefreshGeneration = 0;
let aiRequestGeneration = 0;
let comparisonGeneration = 0;
let undoOperationGeneration = 0;
let undoInFlight: Readonly<{ token: symbol; generation: number }> | null = null;

type OperationStepResult = "completed" | "conflict" | "superseded" | "failed";

type StoreOperationOwner = Readonly<{
  projectId: string;
  branchId: string | null;
  projectGeneration: number;
  branchGeneration: number;
}>;

function captureOperationOwner(projectId: string, branchId: string | null): StoreOperationOwner {
  return { projectId, branchId, projectGeneration: projectSelectionGeneration, branchGeneration: branchSelectionGeneration };
}

function ownsOperation(owner: StoreOperationOwner): boolean {
  const state = useStore.getState();
  return owner.projectGeneration === projectSelectionGeneration
    && owner.branchGeneration === branchSelectionGeneration
    && state.currentProject?.id === owner.projectId
    && (state.currentBranch?.id ?? null) === owner.branchId;
}

function retireUndoAfterOwnedCommit(
  set: (partial: Partial<GrowthMapStore>) => void,
  owner: StoreOperationOwner,
): boolean {
  if (!ownsOperation(owner)) return false;
  // Increment and clear in the same synchronous settlement turn. Any reserved
  // older undo immediately loses `current()` before it can publish again.
  ++undoOperationGeneration;
  set({ undoStack: [] });
  return true;
}

function pushOwnedUndo(
  stack: UndoEntry[], rootNode: GNode, description: string, owner: StoreOperationOwner,
  inverse?: UndoEntry["inverse"],
): UndoEntry[] {
  return pushUndo(stack, rootNode, description, owner, inverse);
}

type CreateNodeAuthority = Readonly<{
  id: string;
  projectId: string;
  branchId: string | null;
  parentId: string;
  projectRevision: number;
  parentRevision: number;
  nodeRevision: number;
}>;

function snapshotCreateNodeAuthority(value: unknown): CreateNodeAuthority | null {
  if (value === null || typeof value !== "object") return null;
  try {
    const readOwnData = (key: string): unknown => {
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (!descriptor || !("value" in descriptor) || descriptor.get || descriptor.set) throw new Error("unsafe create authority");
      return descriptor.value;
    };
    const id = readOwnData("id");
    const projectId = readOwnData("project_id");
    const rawBranchId = readOwnData("branch_id");
    const parentId = readOwnData("authoritative_parent_id");
    const projectRevision = readOwnData("authoritative_project_revision");
    const parentRevision = readOwnData("authoritative_parent_revision");
    const nodeRevision = readOwnData("revision");
    const branchId = rawBranchId === null || rawBranchId === undefined ? null : rawBranchId;
    if (typeof id !== "string" || id.length === 0
      || typeof projectId !== "string" || projectId.length === 0
      || (branchId !== null && (typeof branchId !== "string" || branchId.length === 0))
      || typeof parentId !== "string" || parentId.length === 0
      || !Number.isSafeInteger(projectRevision) || (projectRevision as number) <= 0
      || !Number.isSafeInteger(parentRevision) || (parentRevision as number) <= 0
      || !Number.isSafeInteger(nodeRevision) || (nodeRevision as number) <= 0) return null;
    return Object.freeze({
      id, projectId, branchId: branchId as string | null, parentId,
      projectRevision: projectRevision as number,
      parentRevision: parentRevision as number,
      nodeRevision: nodeRevision as number,
    });
  } catch {
    return null;
  }
}

type DeepenBlockToken = Readonly<{ token: symbol; originalIndex: number; title: string; body: string; block_type: string }>;
type DeepenOperationContext = Readonly<{
  owner: StoreOperationOwner;
  rootNode: GNode;
  targetId: string;
  summary: string;
  blocks: ReadonlyArray<DeepenBlockToken>;
}>;
const retiredDeepenTokens = new WeakMap<DeepenOperationContext, Set<symbol>>();

function captureDeepenContext(): DeepenOperationContext | null {
  const { deepenResult, currentProject, currentBranch, rootNode } = useStore.getState();
  if (!deepenResult || !currentProject || !rootNode || !findNode(rootNode, deepenResult.target_node_id)) return null;
  return Object.freeze({
    owner: captureOperationOwner(currentProject.id, currentBranch?.id ?? null),
    rootNode,
    targetId: deepenResult.target_node_id,
    summary: deepenResult.enriched_summary,
    blocks: Object.freeze(deepenResult.content_blocks.map((block, originalIndex) => Object.freeze({ ...block, originalIndex, token: Symbol("deepen-block") }))),
  });
}

function ownsDeepenContext(context: DeepenOperationContext): boolean {
  const currentRoot = useStore.getState().rootNode;
  return ownsOperation(context.owner)
    && context.rootNode.project_id === context.owner.projectId
    && Boolean(findNode(context.rootNode, context.targetId))
    && Boolean(currentRoot && findNode(currentRoot, context.targetId));
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
  aiError: null,
  undoStack: [],
  toast: null,
  searchQuery: "",
  highlightedNodeIds: [],
  branches: [],
  currentBranch: null,
  branchComparison: null,
  branchLoading: false,

  loadProjects: async () => {
    const generation = ++projectListGeneration;
    const owner = {
      projectId: get().currentProject?.id ?? null,
      branchId: get().currentBranch?.id ?? null,
      projectGeneration: projectSelectionGeneration,
      branchGeneration: branchSelectionGeneration,
    };
    const stillOwned = () => generation === projectListGeneration
      && owner.projectGeneration === projectSelectionGeneration
      && owner.branchGeneration === branchSelectionGeneration
      && (get().currentProject?.id ?? null) === owner.projectId
      && (get().currentBranch?.id ?? null) === owner.branchId;
    try {
      // Project-list rows are display data only. They never enter the mutation
      // revision cache: selected-project authority comes from its exact owned
      // selection/readback path, so a global list cannot compete with it.
      const projects = await api.listProjects(false);
      if (stillOwned()) set({ projects, error: null });
    } catch (e: unknown) {
      if (stillOwned()) set({ error: (e as Error).message });
    }
  },

  selectProject: async (project) => {
    const generation = ++projectSelectionGeneration;
    ++branchSelectionGeneration;
    ++treeRefreshGeneration;
    ++aiRequestGeneration;
    set({ loading: true, branchLoading: false, currentProject: project, selectedNodeId: null, selectedNode: null, undoStack: [], currentBranch: null, branches: [], branchComparison: null, error: null, conflict: null, expandSuggestions: null, expandTargetNodeId: null, deepenResult: null, aiLoading: false });
    // The explicitly selected row owns this generation. Global list refreshes
    // are intentionally never mutation-revision authorities.
    api.rememberResponse(project);
    // Branches are independent from the tree request, but both settlements are owned
    // by this exact project selection. This keeps switching responsive without
    // allowing an older project's response (or error) to repaint the new project.
    const branchesPromise = get().loadBranches(project.id);
    try {
      const rootNode = await api.getSubtree(project.root_node_id, false);
      if (generation !== projectSelectionGeneration || get().currentProject?.id !== project.id) return;
      api.rememberResponse(rootNode);
      set({ rootNode, loading: false });
    } catch (e: unknown) {
      if (generation !== projectSelectionGeneration || get().currentProject?.id !== project.id) return;
      set({ error: (e as Error).message, loading: false });
    }
    await branchesPromise;
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
    const { currentProject, currentBranch, rootNode } = get();
    if (!currentProject || !rootNode) return;
    const initiatingParent = findNode(rootNode, parentId);
    if (!initiatingParent || rootNode.project_id !== currentProject.id) return;
    const owner = captureOperationOwner(currentProject.id, currentBranch?.id ?? null);
    const stillOwned = () => ownsOperation(owner);
    const initiatingParentRevision = initiatingParent.revision;
    const outcome = await runMutationWithConflict(
      () => api.createNode(currentProject.id, {
        title,
        parent_id: parentId,
        branch_id: owner.branchId ?? undefined,
        node_type: nodeType,
      }),
      () => get().refreshTree(),
      { nodeDraft: title },
      stillOwned,
    );
    if (outcome.superseded) return;
    if (outcome.conflict) { set({ conflict: outcome.conflict, error: outcome.conflict.message }); return; }
    if (!stillOwned()) return;

    // The POST committed. Retire every older capability before any fallible
    // validation/readback; never let an in-flight old DELETE revive it.
    if (!retireUndoAfterOwnedCommit(set, owner)) return;
    const authority = snapshotCreateNodeAuthority(outcome.value);
    const settlementRoot = get().rootNode;
    const settlementParent = settlementRoot ? findNode(settlementRoot, parentId) : null;
    const responseAuthority = authority !== null
      && findNode(rootNode, authority.id) === null
      && settlementRoot?.project_id === currentProject.id
      && Boolean(settlementParent && settlementParent.revision === initiatingParentRevision)
      && Boolean(settlementRoot && findNode(settlementRoot, authority.id) === null)
      && authority.projectId === currentProject.id
      && authority.branchId === owner.branchId
      && authority.parentId === parentId;
    try {
      const refresh = await get().refreshTree();
      if (refresh !== "refreshed" || !stillOwned()) return;
      const authoritativeRoot = get().rootNode;
      const authoritativeParent = authoritativeRoot ? findNode(authoritativeRoot, parentId) : null;
      const authoritativeChild = authority && authoritativeRoot ? findNode(authoritativeRoot, authority.id) : null;
      const isDirectChild = Boolean(authority && authoritativeParent?.children?.some((child) => child.id === authority.id));
      const readbackProvesCreate = responseAuthority
        && authority !== null
        && authoritativeRoot?.project_id === currentProject.id
        && authoritativeChild?.project_id === currentProject.id
        && (authoritativeChild?.branch_id ?? null) === owner.branchId
        && isDirectChild;
      if (!readbackProvesCreate || !authority) {
        set({ toast: ui(
          '✅ 節點已建立，但無法驗證安全復原權限；請重新載入專案',
          '✅ 节点已创建，但无法验证安全恢复权限；请重新加载项目',
          '✅ Node created, but safe undo authority could not be verified; reload the project.',
        ) });
        return;
      }
      const inverse = { kind: "delete-created-node" as const, nodeId: authority.id,
        nodeRevision: authority.nodeRevision, projectRevision: authority.projectRevision };
      set({ undoStack: pushOwnedUndo(get().undoStack, authoritativeRoot!,
        ui(`新增子節點: ${title}`,`新增子节点: ${title}`,`Add child node: ${title}`), owner, inverse) });
    } catch {
      if (stillOwned()) set({ toast: ui(
        '✅ 節點已建立，但最新畫面載入失敗；請重新載入專案',
        '✅ 节点已创建，但最新画面加载失败；请重新加载项目',
        '✅ Node created, but the latest view could not load; reload the project.',
      ) });
    }
  },

  updateNode: async (nodeId, data) => {
    const { rootNode, currentProject, currentBranch } = get();
    const existing = rootNode ? findNode(rootNode, nodeId) : null;
    if (!currentProject || !existing) return;
    const owner = captureOperationOwner(currentProject.id, currentBranch?.id ?? null);
    if (!ownsOperation(owner)) return;
    try {
      const saved = await api.updateNode(nodeId, { ...data, expected_project_revision: currentProject.revision, expected_revision: existing.revision });
      if (!ownsOperation(owner) || !rootNode) return;
      const updated = patchNode(rootNode, nodeId, saved);
      advanceProjectRevision(set, currentProject);
      retireUndoAfterOwnedCommit(set, owner);
      set({ rootNode: updated });
      const { selectedNodeId } = get();
      if (selectedNodeId) set({ selectedNode: findNode(updated, selectedNodeId) });
    } catch (error) {
      if (ownsOperation(owner)) throw error;
    }
  },

  deleteNode: async (nodeId) => {
    const { rootNode, selectedNodeId, currentProject, currentBranch } = get();
    const existing = rootNode ? findNode(rootNode, nodeId) : null;
    if (!currentProject || !existing) return;
    const owner = captureOperationOwner(currentProject.id, currentBranch?.id ?? null);
    if (!ownsOperation(owner)) return;
    try {
      await api.deleteNode(nodeId, currentProject.revision, existing.revision);
      if (!ownsOperation(owner)) return;
      advanceProjectRevision(set, currentProject);
      if (!rootNode) return;
      const updated = removeNode(rootNode, nodeId);
      retireUndoAfterOwnedCommit(set, owner);
      set({ rootNode: updated });
      if (selectedNodeId === nodeId) set({ selectedNodeId: null, selectedNode: null });
      else if (selectedNodeId) set({ selectedNode: findNode(updated, selectedNodeId) });
    } catch (error) {
      if (ownsOperation(owner)) throw error;
    }
  },

  refreshTree: async () => {
    const { currentProject, currentBranch } = get();
    if (!currentProject) return "superseded";
    const projectId = currentProject.id;
    const rootNodeId = currentProject.root_node_id;
    const branchId = currentBranch?.id ?? null;
    const generation = ++treeRefreshGeneration;
    const stillOwned = () => generation === treeRefreshGeneration
      && get().currentProject?.id === projectId
      && (get().currentBranch?.id ?? null) === branchId;

    // A project read before and after the tree makes a bounded consistency fence:
    // if a writer lands while the tree is loading, retry once instead of publishing
    // a mixed project/tree snapshot. Responses are remembered only after ownership wins.
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const before = await api.getProject(projectId, false);
      const rootNode = branchId
        ? (await api.getBranchSubtree(branchId, false)).tree
        : await api.getSubtree(rootNodeId, false);
      const after = await api.getProject(projectId, false);
      if (!stillOwned()) return "superseded";
      if (!rootNode) throw new Error(ui('目前方案線沒有可顯示的根節點','当前方案线没有可显示的根节点','The current scenario has no displayable root node.'));
      if (before.revision !== after.revision) {
        if (attempt === 0) continue;
        throw new Error(ui('專案仍在更新，請稍後重新載入','项目仍在更新，请稍后重新加载','The project is still changing; reload again shortly.'));
      }
      api.rememberResponse(after);
      api.rememberResponse(rootNode);
      const latest = get();
      set({
        currentProject: after,
        projects: latest.projects.map((row) => row.id === projectId ? after : row),
        rootNode,
        selectedNode: latest.selectedNodeId ? findNode(rootNode, latest.selectedNodeId) : null,
      });
      return "refreshed";
    }
    return "superseded";
  },

  promoteMainlineChild: async (parentId, childId) => {
    const { rootNode, currentProject, currentBranch } = get();
    if (!rootNode || !currentProject) return;
    const owner = captureOperationOwner(currentProject.id, currentBranch?.id ?? null);
    const child = findNode(rootNode, childId);
    const edgeRevision = typeof child?.meta?.edge_revision === "number" ? child.meta.edge_revision : 1;
    if (!ownsOperation(owner)) return;
    try {
      await api.promoteChildMainline(parentId, childId, currentProject.revision, edgeRevision);
      if (!ownsOperation(owner)) return;
      advanceProjectRevision(set, currentProject);
      const updated = markMainlineChild(rootNode, parentId, childId);
      retireUndoAfterOwnedCommit(set, owner);
      set({ rootNode: updated });
      const { selectedNodeId } = get();
      if (selectedNodeId) set({ selectedNode: findNode(updated, selectedNodeId) });
    } catch (error) {
      if (ownsOperation(owner)) throw error;
    }
  },

  reparentNode: async (nodeId, newParentId) => {
    const { rootNode, currentProject, currentBranch } = get();
    if (!rootNode || !currentProject) return;
    const owner = captureOperationOwner(currentProject.id, currentBranch?.id ?? null);
    const node = findNode(rootNode, nodeId);
    const newParent = findNode(rootNode, newParentId);
    const oldParent = (() => {
      const walk = (candidate: GNode): GNode | null => candidate.children?.some((child) => child.id === nodeId)
        ? candidate : (candidate.children || []).map(walk).find(Boolean) || null;
      return walk(rootNode);
    })();
    if (!node || !newParent || !oldParent || !ownsOperation(owner)) return;
    try {
      const response = await fetch(`/api/nodes/${nodeId}/reparent`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_parent_id: newParentId, expected_project_revision: currentProject.revision,
          expected_revision: node.revision, expected_new_parent_revision: newParent.revision,
          expected_old_parent_revision: oldParent.revision }),
      });
      if (!response.ok) throw new Error(`API ${response.status}: ${await response.text()}`);
    } catch (e: unknown) {
      if (ownsOperation(owner)) set({ error: (e as Error).message });
      return;
    }
    if (!ownsOperation(owner)) return;
    advanceProjectRevision(set, currentProject);
    retireUndoAfterOwnedCommit(set, owner);
    try {
      const result = await get().refreshTree();
      if (result === "refreshed" && ownsOperation(owner)) set({ error: null, toast: ui('✅ 節點已移動','✅ 节点已移动','✅ Node moved') });
    } catch {
      if (ownsOperation(owner)) set({ error: null, toast: ui('✅ 節點已移動；最新畫面載入失敗，請重新載入專案','✅ 节点已移动；最新画面加载失败，请重新加载项目','✅ Node moved; the latest view could not load, so reload the project.') });
    }
  },

  undo: async () => {
    if (undoInFlight) return;
    const { undoStack } = get();
    if (undoStack.length === 0) return;
    const [entry, ...rest] = undoStack;
    const owner: StoreOperationOwner = { projectId: entry.projectId, branchId: entry.branchId,
      projectGeneration: entry.projectGeneration, branchGeneration: entry.branchGeneration };
    if (!ownsOperation(owner)) { set({ undoStack: [] }); return; }
    if (!entry.inverse || entry.inverse.kind !== "delete-created-node") {
      set({ undoStack: [], error: ui('這項操作無法安全地持久復原；畫面未變更','此操作无法安全地持久恢复；画面未更改','This operation cannot be durably undone; the view was not changed.') });
      return;
    }
    const operation = Object.freeze({ token: Symbol("undo"), generation: undoOperationGeneration });
    undoInFlight = operation;
    // Reserve the exact entry before the first await. New pushes may prepend to
    // `rest`, but no concurrent undo may consume this or the next entry.
    set({ undoStack: rest });
    const current = () => undoInFlight?.token === operation.token
      && operation.generation === undoOperationGeneration && ownsOperation(owner);
    const inverse = entry.inverse;
    try {
      try {
        await api.deleteNode(inverse.nodeId, inverse.projectRevision, inverse.nodeRevision);
      } catch (error) {
        if (!current()) return;
        try {
          const refreshed = await get().refreshTree();
          if (refreshed !== "refreshed" || !current()) return;
          const stack = get().undoStack;
          // Preserve pushes made while DELETE/readback was pending. Restore at
          // the old boundary, immediately before the still-present old suffix.
          const boundary = rest.length === 0 ? stack.length : stack.findIndex((candidate) => candidate === rest[0]);
          if (boundary < 0 || rest.some((candidate, index) => stack[boundary + index] !== candidate)) return;
          set({ undoStack: [...stack.slice(0, boundary), entry, ...stack.slice(boundary)],
            error: (error as Error).message,
            toast: ui('復原失敗；已重新載入目前資料，可再試一次','恢复失败；已重新加载当前数据，可以重试','Undo failed; current data was reloaded and you may retry.') });
        } catch {
          if (current()) set({ rootNode: null, selectedNodeId: null, selectedNode: null,
            error: (error as Error).message,
            toast: ui('復原失敗，且無法確認最新資料；請重新載入專案後再試','恢复失败，且无法确认最新数据；请重新加载项目后重试','Undo failed and current data could not be verified; reload the project before retrying.') });
        }
        return;
      }
      if (!current()) return;
      const localRoot = get().rootNode;
      const updated = localRoot ? removeNode(localRoot, inverse.nodeId) : null;
      const selectedNodeId = get().selectedNodeId === inverse.nodeId ? null : get().selectedNodeId;
      set({ rootNode: updated, selectedNodeId,
        selectedNode: selectedNodeId && updated ? findNode(updated, selectedNodeId) : null, error: null });
      try {
        const refreshed = await get().refreshTree();
        if (refreshed === "refreshed" && current()) set({ toast: ui(`已復原: ${entry.description}`,`已恢复: ${entry.description}`,`Restored: ${entry.description}`) });
      } catch {
        if (current()) set({ toast: ui(
          '節點已刪除，但最新畫面載入失敗；復原已退休，請重新載入專案',
          '节点已删除，但最新画面加载失败；恢复已退役，请重新加载项目',
          'Node deleted, but the latest view could not load; undo was retired. Reload the project.',
        ) });
      }
    } finally {
      if (undoInFlight?.token === operation.token) undoInFlight = null;
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
    const generation = ++branchLoadGeneration;
    const projectGeneration = projectSelectionGeneration;
    try {
      const branches = await api.listBranches(projectId, false, false);
      if (generation !== branchLoadGeneration || projectGeneration !== projectSelectionGeneration || get().currentProject?.id !== projectId) return;
      api.rememberResponse(branches);
      set({ branches });
    } catch (e: unknown) {
      if (generation !== branchLoadGeneration || projectGeneration !== projectSelectionGeneration || get().currentProject?.id !== projectId) return;
      console.error("Failed to load branches:", e);
    }
  },

  createBranch: async (sourceNodeId, name, description) => {
    const { currentProject, currentBranch } = get();
    if (!currentProject) return;
    const owner = captureOperationOwner(currentProject.id, currentBranch?.id ?? null);
    try {
      if (!ownsOperation(owner)) return;
      const branch = await api.createBranch(currentProject.id, { expected_project_revision: currentProject.revision, source_node_id: sourceNodeId, name, description });
      if (!ownsOperation(owner)) return;
      advanceProjectRevision(set, currentProject);
      const { branches } = get();
      set({ branches: [...branches, branch], toast: ui(`✅ 方案線「${name}」已建立`,`✅ 方案线“${name}”已创建`,`✅ Scenario “${name}” created`) });
      await get().selectBranch(branch);
    } catch (e: unknown) {
      if (ownsOperation(owner)) set({ error: (e as Error).message });
    }
  },

  selectBranch: async (branch) => {
    ++treeRefreshGeneration;
    const { currentProject } = get();
    if (!currentProject) return;
    const projectId = currentProject.id;
    const branchId = branch?.id ?? null;
    const generation = ++branchSelectionGeneration;
    ++aiRequestGeneration;
    const current = () => generation === branchSelectionGeneration && get().currentProject?.id === projectId;
    set({ loading: true, branchLoading: true, selectedNodeId: null, selectedNode: null, branchComparison: null, undoStack: [], conflict: null, error: null, toast: null, expandSuggestions: null, expandTargetNodeId: null, deepenResult: null, aiLoading: false });
    try {
      if (!branch) {
        const rootNode = await api.getSubtree(currentProject.root_node_id, false);
        if (!current()) return;
        api.rememberResponse(rootNode);
        set({ currentBranch: null, rootNode, loading: false, branchLoading: false });
        return;
      }
      const result = await api.getBranchSubtree(branchId!, false);
      if (!current()) return;
      api.rememberResponse(result);
      if (!result.tree) throw new Error(ui('方案線沒有可顯示的根節點','方案线没有可显示的根节点','This scenario has no displayable root node.'));
      set({ currentBranch: branch, rootNode: result.tree, loading: false, branchLoading: false });
    } catch (e: unknown) {
      if (!current()) return;
      set({ error: (e as Error).message, loading: false, branchLoading: false });
    }
  },

  compareBranch: async (branchId) => {
    const { currentProject, currentBranch, branches } = get();
    if (!currentProject || !branches.some((branch) => branch.id === branchId)) return null;
    const owner = captureOperationOwner(currentProject.id, currentBranch?.id ?? null);
    const generation = ++comparisonGeneration;
    const active = () => generation === comparisonGeneration && ownsOperation(owner);
    set({ branchLoading: true });
    try {
      const branchComparison = await api.compareBranch(branchId, false);
      if (!active()) return null;
      api.rememberResponse(branchComparison);
      set({ branchComparison, branchLoading: false });
      return branchComparison;
    } catch (e: unknown) {
      if (active()) set({ error: (e as Error).message, branchLoading: false });
      return null;
    }
  },

  archiveBranch: async (branchId) => {
    const { currentProject, branches, currentBranch } = get();
    const branch = branches.find((row) => row.id === branchId);
    if (!currentProject || !branch) return;
    const owner = captureOperationOwner(currentProject.id, currentBranch?.id ?? null);
    try {
      if (!ownsOperation(owner)) return;
      await api.archiveBranch(branchId, currentProject.revision, branch.revision);
      if (!ownsOperation(owner)) return;
      advanceProjectRevision(set, currentProject);
      const remaining = branches.filter((branch) => branch.id !== branchId);
      retireUndoAfterOwnedCommit(set, owner);
      set({ branches: remaining, branchComparison: null, toast: ui('🗃️ 方案線已封存','🗃️ 方案线已归档','🗃️ Scenario archived') });
      if (currentBranch?.id === branchId && currentProject) {
        await get().selectBranch(null);
      }
    } catch (e: unknown) {
      if (ownsOperation(owner)) set({ error: (e as Error).message });
    }
  },

  mergeBranch: async (branchId, targetNodeId) => {
    const { currentProject, currentBranch, branches } = get();
    const branch = branches.find((row) => row.id === branchId);
    const target = get().rootNode ? findNode(get().rootNode!, targetNodeId) : null;
    if (!currentProject || !branch || !target) return;
    const owner = captureOperationOwner(currentProject.id, currentBranch?.id ?? null);
    set({ branchLoading: true });
    try {
      if (!ownsOperation(owner)) return;
      await api.mergeBranch(branchId, targetNodeId, currentProject.revision, branch.revision, target.revision);
      if (!ownsOperation(owner)) return;
      retireUndoAfterOwnedCommit(set, owner);
      const rootNode = await api.getSubtree(currentProject.root_node_id, false);
      if (!ownsOperation(owner)) return;
      api.rememberResponse(rootNode);
      advanceProjectRevision(set, currentProject);
      set({
        branches: branches.filter((b) => b.id !== branchId),
        currentBranch: null,
        branchComparison: null,
        selectedNodeId: null,
        selectedNode: null,
        rootNode,
        branchLoading: false,
        toast: ui('✅ 方案線已合併回主線','✅ 方案线已合并回主线','✅ Scenario merged into main line'),
      });
    } catch (e: unknown) {
      if (ownsOperation(owner)) set({ error: (e as Error).message, branchLoading: false });
    }
  },

  expandNode: async (nodeId, identity, instruction, mode = "explore") => {
    const { currentProject, currentBranch, rootNode } = get();
    if (!currentProject || !rootNode || !findNode(rootNode, nodeId)) return;
    const owner = captureOperationOwner(currentProject.id, currentBranch?.id ?? null);
    const ownedRoot = rootNode;
    const started=Date.now();
    const generation = ++aiRequestGeneration;
    const active = () => generation === aiRequestGeneration && ownsOperation(owner)
      && ownedRoot.project_id === owner.projectId && Boolean(findNode(ownedRoot, nodeId))
      && Boolean(get().rootNode && findNode(get().rootNode!, nodeId));
    set({ aiLoading: true, aiError: null, expandSuggestions: null, expandTargetNodeId: nodeId, deepenResult: null, error: null });
    try {
      const result = await api.expand(nodeId, instruction, undefined, mode, identity.providerId, identity.revision, identity.selectionRevision);
      if (active()) set({ expandSuggestions: result.suggestions, aiLoading: false });
    } catch (e: unknown) {
      if (active()) { const x=e as ApiError; set({ aiError:{code:x.code,status:x.status,requestId:x.requestId,message:x.message,action:"expand",elapsedMs:Date.now()-started}, aiLoading:false }); }
    }
  },

  deepenNode: async (nodeId, identity, instruction) => {
    const { currentProject, currentBranch, rootNode } = get();
    if (!currentProject || !rootNode || !findNode(rootNode, nodeId)) return;
    const owner = captureOperationOwner(currentProject.id, currentBranch?.id ?? null);
    const ownedRoot = rootNode;
    const started=Date.now();
    const generation = ++aiRequestGeneration;
    const active = () => generation === aiRequestGeneration && ownsOperation(owner)
      && ownedRoot.project_id === owner.projectId && Boolean(findNode(ownedRoot, nodeId))
      && Boolean(get().rootNode && findNode(get().rootNode!, nodeId));
    set({ aiLoading: true, aiError: null, deepenResult: null, expandSuggestions: null, expandTargetNodeId: null, error: null });
    try {
      const result = await api.deepen(nodeId, instruction, identity.providerId, identity.revision, identity.selectionRevision);
      if (active()) set({ deepenResult: { ...result, target_node_id: nodeId }, aiLoading: false });
    } catch (e: unknown) {
      if (active()) { const x=e as ApiError; set({ aiError:{code:x.code,status:x.status,requestId:x.requestId,message:x.message,action:"deepen",elapsedMs:Date.now()-started}, aiLoading:false }); }
    }
  },

  acceptSuggestion: async (index) => {
    const { expandSuggestions, expandTargetNodeId, currentProject, currentBranch, rootNode } = get();
    if (!expandSuggestions || !expandTargetNodeId || !currentProject || !rootNode) return;
    const owner = captureOperationOwner(currentProject.id, currentBranch?.id ?? null);
    const ownedRoot = rootNode;
    const stillOwned = () => ownsOperation(owner) && ownedRoot.project_id === owner.projectId
      && Boolean(findNode(ownedRoot, expandTargetNodeId))
      && Boolean(get().rootNode && findNode(get().rootNode!, expandTargetNodeId));
    if (!stillOwned()) return;
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
      stillOwned,
    );
    if (outcome.superseded) return;
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
    retireUndoAfterOwnedCommit(set, owner);
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
    const { expandSuggestions, expandTargetNodeId, currentProject, currentBranch, rootNode } = get();
    if (!expandSuggestions || !expandTargetNodeId || !currentProject || !rootNode) return;
    const owner = captureOperationOwner(currentProject.id, currentBranch?.id ?? null);
    const ownedRoot = rootNode;
    const stillOwned = () => ownsOperation(owner) && ownedRoot.project_id === owner.projectId
      && Boolean(findNode(ownedRoot, expandTargetNodeId))
      && Boolean(get().rootNode && findNode(get().rootNode!, expandTargetNodeId));
    if (!stillOwned()) return;
    if (!confirm(ui(`確定採用全部 ${expandSuggestions.length} 個 AI 分支建議？`,`确定采用全部 ${expandSuggestions.length} 个 AI 分支建议吗？`,`Accept all ${expandSuggestions.length} AI branch suggestions?`))) return;
    let tree = rootNode;
    const pending = expandSuggestions.map((suggestion, token) => ({ suggestion, token }));
    let committed = 0;
    for (const item of pending) {
      let outcome: Awaited<ReturnType<typeof runMutationWithConflict<Awaited<ReturnType<typeof api.createNode>>>>>;
      try {
        outcome = await runMutationWithConflict(
          () => api.createNode(currentProject.id, {
            title: item.suggestion.title,
            summary: item.suggestion.summary,
            parent_id: expandTargetNodeId,
            branch_id: owner.branchId ?? undefined,
            node_type: item.suggestion.node_type,
          }),
          () => get().refreshTree(),
          { suggestionInput: item.suggestion.title },
          stillOwned,
        );
      } catch (error) {
        if (!stillOwned()) return;
        if (committed > 0) {
          set({ undoStack: [], error: null, toast: ui('✅ 部分 AI 建議已儲存；其餘項目未完成，請重新載入後再繼續','✅ 部分 AI 建议已保存；其余项目未完成，请重新加载后再继续','✅ Some AI suggestions were saved; remaining items were not completed. Reload before continuing.') });
          return;
        }
        throw error;
      }
      if (outcome.superseded) return;
      if (outcome.conflict) {
        if (committed > 0) set({ undoStack: [], conflict: outcome.conflict, error: outcome.conflict.message, toast: ui('✅ 部分 AI 建議已儲存；下一項發生衝突，已保留未完成項目','✅ 部分 AI 建议已保存；下一项发生冲突，已保留未完成项目','✅ Some AI suggestions were saved; the next item conflicted, and unfinished items were preserved.') });
        else set({ conflict: outcome.conflict, error: outcome.conflict.message });
        return;
      }
      committed += 1;
      if (!stillOwned()) return;
      retireUndoAfterOwnedCommit(set, owner);
      const remaining = pending.filter((candidate) => candidate.token > item.token).map((candidate) => candidate.suggestion);
      set({ expandSuggestions: remaining.length ? remaining : null });
      const newNode = outcome.value!;
      tree = applyCreateRevisions(set, get().currentProject!, tree, newNode);
      const child: GNode = {
        ...newNode,
        summary: newNode.summary || "",
        node_type: newNode.node_type || "idea",
        maturity: newNode.maturity || "seed",
        meta: {}, project_id: currentProject.id, content_blocks: [], children: [],
        created_at: newNode.created_at || "", updated_at: newNode.updated_at || "",
      };
      tree = insertChild(tree, expandTargetNodeId, child);
    }
    try {
      const refresh = await get().refreshTree();
      if (refresh === "superseded" || !stillOwned()) return;
    } catch {
      if (!stillOwned()) return;
      set({ expandSuggestions: null, undoStack: [], error: null, toast: ui('✅ AI 建議已儲存；最新畫面載入失敗，請重新載入專案','✅ AI 建议已保存；最新画面加载失败，请重新加载项目','✅ AI suggestions saved; the latest view could not load, so reload the project.') });
      return;
    }
    set({ expandSuggestions: null, toast: ui(`✅ 已建立 ${expandSuggestions.length} 個 AI 建議節點`,`✅ 已创建 ${expandSuggestions.length} 个 AI 建议节点`,`✅ Created ${expandSuggestions.length} AI-suggested nodes`) });
    const { selectedNodeId } = get();
    if (selectedNodeId) set({ selectedNode: findNode(tree, selectedNodeId) });
  },

  acceptDeepen: async () => {
    set({ conflict: null });
    const context = captureDeepenContext();
    if (!context) return;
    const summary = await get().acceptDeepenSummary(context);
    if (summary !== "completed" || !ownsDeepenContext(context)) return;
    let committedBlocks = 0;
    for (let i = context.blocks.length - 1; i >= 0; i--) {
      try {
        const block = await get().acceptDeepenBlock(i, context);
        if (block !== "completed" || !ownsDeepenContext(context)) {
          if (committedBlocks > 0 && ownsDeepenContext(context)) set({ undoStack: [], toast: ui('部分 AI 內容區塊已儲存；未儲存的區塊仍保留','部分 AI 内容区块已保存；未保存的区块仍保留','Some AI content blocks were saved; unsaved blocks remain available.') });
          return;
        }
        committedBlocks += 1;
      } catch (error) {
        if (committedBlocks === 0 || !ownsDeepenContext(context)) throw error;
        set({ undoStack: [], error: null, toast: ui('部分 AI 內容區塊已儲存；未儲存的區塊仍保留','部分 AI 内容区块已保存；未保存的区块仍保留','Some AI content blocks were saved; unsaved blocks remain available.') });
        return;
      }
    }
    if (ownsDeepenContext(context)) set({ deepenResult: null });
  },

  acceptDeepenSummary: async (providedContext) => {
    const context = providedContext ?? captureDeepenContext();
    if (!context || !ownsDeepenContext(context)) return "superseded";
    const { rootNode } = get();
    if (!rootNode) return "failed";
    const outcome = await runMutationWithConflict(
      () => api.updateNode(context.targetId, { summary: context.summary } as Partial<GNode>),
      () => get().refreshTree(),
      { suggestionInput: context.summary },
      () => ownsDeepenContext(context),
    );
    if (outcome.superseded) return "superseded";
    if (outcome.conflict) { set({ conflict: outcome.conflict, error: outcome.conflict.message }); return "conflict"; }
    if (!ownsDeepenContext(context)) return "superseded";
    const updated = patchNode(rootNode, context.targetId, outcome.value!);
    retireUndoAfterOwnedCommit(set, context.owner);
    set({ rootNode: updated, selectedNode: get().selectedNodeId ? findNode(updated, get().selectedNodeId!) : null });
    try {
      const refresh = await get().refreshTree();
      if (refresh === "superseded" || !ownsDeepenContext(context)) return "superseded";
      set({ toast: ui('✅ 已套用 AI 摘要建議','✅ 已应用 AI 摘要建议','✅ Applied AI summary suggestion') });
    } catch {
      if (!ownsDeepenContext(context)) return "superseded";
      set({ toast: ui('✅ 摘要已儲存；最新畫面載入失敗，請重新載入專案','✅ 摘要已保存；最新画面加载失败，请重新加载项目','✅ Summary saved; the latest view could not load, so reload the project.') });
    }
    return "completed";
  },

  acceptDeepenBlock: async (index, providedContext) => {
    const context = providedContext ?? captureDeepenContext();
    if (!context || !ownsDeepenContext(context)) return "superseded";
    const { deepenResult, rootNode } = get();
    if (!deepenResult || !rootNode) return "superseded";
    const block = providedContext ? context.blocks[index] : context.blocks[index];
    if (!block) return "failed";
    const retired = retiredDeepenTokens.get(context) ?? new Set<symbol>();
    retiredDeepenTokens.set(context, retired);
    if (retired.has(block.token)) return "superseded";
    const liveIndex = context.blocks
      .filter((candidate) => !retired.has(candidate.token))
      .findIndex((candidate) => candidate.token === block.token);
    if (liveIndex < 0 || !deepenResult.content_blocks[liveIndex]) return "superseded";
    const outcome = await runMutationWithConflict(
      () => api.createBlock(context.targetId, {
        block_type: block.block_type,
        content: { title: block.title, body: block.body },
      }) as Promise<{ id: string; node_id: string; block_type: string; content: Record<string, string>; order_index: number }>,
      () => get().refreshTree(),
      { suggestionInput: `${block.title}\n${block.body}` },
      () => ownsDeepenContext(context),
    );
    if (outcome.superseded) return "superseded";
    if (outcome.conflict) { set({ conflict: outcome.conflict, error: outcome.conflict.message }); return "conflict"; }
    if (!ownsDeepenContext(context)) return "superseded";
    const created = outcome.value!;
    const target = findNode(rootNode, context.targetId);
    const updated = patchNode(rootNode, context.targetId, { content_blocks: [...(target?.content_blocks || []), created] } as Partial<GNode>);
    const remainingBlocks = deepenResult.content_blocks.filter((_, candidateIndex) => candidateIndex !== liveIndex);
    retired.add(block.token);
    // The POST is committed. Retire exactly this positional capability before
    // the fallible readback; duplicate-valued drafts retain independent tokens.
    retireUndoAfterOwnedCommit(set, context.owner);
    set({
      rootNode: updated,
      selectedNode: get().selectedNodeId ? findNode(updated, get().selectedNodeId!) : null,
      deepenResult: remainingBlocks.length > 0 ? { ...deepenResult, content_blocks: remainingBlocks } : null,
    });
    try {
      const refresh = await get().refreshTree();
      if (refresh === "superseded" || !ownsDeepenContext(context)) return "superseded";
      set({ toast: ui('✅ 已寫入 AI 內容區塊','✅ 已写入 AI 内容区块','✅ Added AI content block') });
    } catch {
      if (!ownsDeepenContext(context)) return "superseded";
      set({ toast: ui('✅ 內容區塊已寫入；最新畫面載入失敗，請重新載入專案','✅ 内容区块已写入；最新画面加载失败，请重新加载项目','✅ Content block added; the latest view could not load, so reload the project.') });
    }
    return "completed";
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

  clearAIError: () => set({ aiError: null }),
  invalidateAISelection: () => { aiRequestGeneration++; set({ aiLoading:false, aiError:null, expandSuggestions:null, deepenResult:null }); },
  dismissAI: () => {
    set({ expandSuggestions: null, deepenResult: null, aiError: null });
  },
}));
