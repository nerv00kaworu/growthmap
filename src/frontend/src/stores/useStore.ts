import { create } from "zustand";
import { api } from "@/lib/api";
import { getErrorDetails } from "@/lib/errors";
import type { GNode, GrowthMode, Project } from "@/lib/types";

interface ActionLoadingState {
  loadProjects: boolean;
  selectProject: boolean;
  expandNode: boolean;
  deepenNode: boolean;
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
  errorStatus: number | null;
  errorRetryable: boolean;
  actionLoading: ActionLoadingState;

  // Actions
  loadProjects: () => Promise<void>;
  selectProject: (project: Project) => Promise<void>;
  selectNode: (nodeId: string | null) => void;
  dismissError: () => void;
  createProject: (name: string, description?: string, goal?: string) => Promise<void>;
  addChildNode: (parentId: string, title: string, nodeType?: string) => Promise<void>;
  updateNode: (nodeId: string, data: Partial<GNode>) => Promise<void>;
  deleteNode: (nodeId: string) => Promise<void>;
  refreshTree: () => Promise<void>;
  promoteMainlineChild: (parentId: string, childId: string) => Promise<void>;

  // AI
  expandSuggestions: { title: string; summary: string; node_type: string }[] | null;
  expandTargetNodeId: string | null;
  deepenResult: { enriched_summary: string; content_blocks: { title: string; body: string; block_type: string }[]; target_node_id: string } | null;
  aiLoading: boolean;
  expandNode: (nodeId: string, instruction?: string, mode?: GrowthMode) => Promise<void>;
  deepenNode: (nodeId: string, instruction?: string) => Promise<void>;
  acceptSuggestion: (index: number) => Promise<void>;
  acceptAllSuggestions: () => Promise<void>;
  acceptDeepen: () => Promise<void>;
  dismissAI: () => void;
}

// Recursively find a node in the tree
function findNode(node: GNode, id: string): GNode | null {
  if (node.id === id) return node;
  for (const child of node.children || []) {
    const found = findNode(child, id);
    if (found) return found;
  }
  return null;
}

// Insert a child node into a tree (in-place returns new tree)
function insertChild(root: GNode, parentId: string, child: GNode): GNode {
  if (root.id === parentId) {
    return { ...root, children: [...(root.children || []), child] };
  }
  return {
    ...root,
    children: (root.children || []).map((c) => insertChild(c, parentId, child)),
  };
}

// Remove a node from the tree by id
function removeNode(root: GNode, nodeId: string): GNode {
  return {
    ...root,
    children: (root.children || [])
      .filter((c) => c.id !== nodeId)
      .map((c) => removeNode(c, nodeId)),
  };
}

// Update a node in the tree by id
function patchNode(root: GNode, nodeId: string, patch: Partial<GNode>): GNode {
  if (root.id === nodeId) {
    return { ...root, ...patch };
  }
  return {
    ...root,
    children: (root.children || []).map((c) => patchNode(c, nodeId, patch)),
  };
}

function markMainlineChild(root: GNode, parentId: string, childId: string): GNode {
  if (root.id === parentId) {
    return {
      ...root,
      children: (root.children || []).map((child) => ({
        ...child,
        is_mainline: child.id === childId,
      })),
    };
  }
  return {
    ...root,
    children: (root.children || []).map((c) => markMainlineChild(c, parentId, childId)),
  };
}

function clearErrorState() {
  return {
    error: null,
    errorStatus: null,
    errorRetryable: false,
  };
}

function getStoreErrorState(error: unknown) {
  const details = getErrorDetails(error);
  return {
    error: details.message,
    errorStatus: details.status,
    errorRetryable: details.retryable,
  };
}

export const useStore = create<GrowthMapStore>((set, get) => ({
  projects: [],
  currentProject: null,
  rootNode: null,
  selectedNodeId: null,
  selectedNode: null,
  loading: false,
  error: null,
  errorStatus: null,
  errorRetryable: false,
  actionLoading: {
    loadProjects: false,
    selectProject: false,
    expandNode: false,
    deepenNode: false,
  },
  expandSuggestions: null,
  expandTargetNodeId: null,
  deepenResult: null,
  aiLoading: false,

  loadProjects: async () => {
    set((state) => ({
      ...clearErrorState(),
      loading: true,
      actionLoading: { ...state.actionLoading, loadProjects: true },
    }));
    try {
      const projects = await api.listProjects();
      set((state) => ({
        projects,
        ...clearErrorState(),
        loading: state.actionLoading.selectProject,
        actionLoading: { ...state.actionLoading, loadProjects: false },
      }));
    } catch (error: unknown) {
      set((state) => ({
        ...getStoreErrorState(error),
        loading: state.actionLoading.selectProject,
        actionLoading: { ...state.actionLoading, loadProjects: false },
      }));
    }
  },

  selectProject: async (project) => {
    set((state) => ({
      ...clearErrorState(),
      loading: true,
      currentProject: project,
      selectedNodeId: null,
      selectedNode: null,
      actionLoading: { ...state.actionLoading, selectProject: true },
    }));
    try {
      const rootNode = await api.getSubtree(project.root_node_id);
      set((state) => ({
        rootNode,
        ...clearErrorState(),
        loading: state.actionLoading.loadProjects,
        actionLoading: { ...state.actionLoading, selectProject: false },
      }));
    } catch (error: unknown) {
      set((state) => ({
        ...getStoreErrorState(error),
        loading: state.actionLoading.loadProjects,
        actionLoading: { ...state.actionLoading, selectProject: false },
      }));
    }
  },

  selectNode: (nodeId) => {
    const { rootNode } = get();
    const selectedNode = nodeId && rootNode ? findNode(rootNode, nodeId) : null;
    set({ selectedNodeId: nodeId, selectedNode });
  },

  dismissError: () => {
    set(clearErrorState());
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
    const newNode = await api.createNode(currentProject.id, { title, parent_id: parentId, node_type: nodeType });
    const child: GNode = {
      id: newNode.id,
      title: newNode.title,
      summary: newNode.summary || "",
      node_type: newNode.node_type || "idea",
      maturity: newNode.maturity || "seed",
      tags: newNode.tags || [],
      meta: {},
      project_id: currentProject.id,
      status: "active",
      content_blocks: [],
      children: [],
      created_at: newNode.created_at || "",
      updated_at: newNode.updated_at || "",
    };
    const updated = insertChild(rootNode, parentId, child);
    set({ rootNode: updated });
    // Re-sync selectedNode if viewing the parent
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  updateNode: async (nodeId, data) => {
    await api.updateNode(nodeId, data);
    const { rootNode } = get();
    if (!rootNode) return;
    const updated = patchNode(rootNode, nodeId, data);
    set({ rootNode: updated });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  deleteNode: async (nodeId) => {
    await api.deleteNode(nodeId);
    const { rootNode, selectedNodeId } = get();
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
    const rootNode = await api.getSubtree(currentProject.root_node_id);
    set({ rootNode });
    const { selectedNodeId } = get();
    if (selectedNodeId && rootNode) {
      set({ selectedNode: findNode(rootNode, selectedNodeId) });
    }
  },

  promoteMainlineChild: async (parentId, childId) => {
    const { rootNode } = get();
    if (!rootNode) return;
    await api.promoteChildMainline(parentId, childId);
    const updated = markMainlineChild(rootNode, parentId, childId);
    set({ rootNode: updated });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  expandNode: async (nodeId, instruction, mode = "explore") => {
    set((state) => ({
      ...clearErrorState(),
      aiLoading: true,
      expandSuggestions: null,
      expandTargetNodeId: nodeId,
      deepenResult: null,
      actionLoading: { ...state.actionLoading, expandNode: true },
    }));
    try {
      const result = await api.expand(nodeId, instruction, undefined, mode);
      set((state) => ({
        expandSuggestions: result.suggestions,
        aiLoading: state.actionLoading.deepenNode,
        actionLoading: { ...state.actionLoading, expandNode: false },
      }));
    } catch (error: unknown) {
      set((state) => ({
        ...getStoreErrorState(error),
        aiLoading: state.actionLoading.deepenNode,
        actionLoading: { ...state.actionLoading, expandNode: false },
      }));
    }
  },

  deepenNode: async (nodeId, instruction) => {
    set((state) => ({
      ...clearErrorState(),
      aiLoading: true,
      deepenResult: null,
      expandSuggestions: null,
      actionLoading: { ...state.actionLoading, deepenNode: true },
    }));
    try {
      const result = await api.deepen(nodeId, instruction);
      set((state) => ({
        deepenResult: { ...result, target_node_id: nodeId },
        aiLoading: state.actionLoading.expandNode,
        actionLoading: { ...state.actionLoading, deepenNode: false },
      }));
    } catch (error: unknown) {
      set((state) => ({
        ...getStoreErrorState(error),
        aiLoading: state.actionLoading.expandNode,
        actionLoading: { ...state.actionLoading, deepenNode: false },
      }));
    }
  },

  acceptSuggestion: async (index) => {
    const { expandSuggestions, expandTargetNodeId, currentProject, rootNode } = get();
    if (!expandSuggestions || !expandTargetNodeId || !currentProject || !rootNode) return;
    const s = expandSuggestions[index];
    const newNode = await api.createNode(currentProject.id, {
      title: s.title,
      summary: s.summary,
      parent_id: expandTargetNodeId,
      node_type: s.node_type,
    });
    const child: GNode = {
      id: newNode.id,
      title: newNode.title,
      summary: newNode.summary || "",
      node_type: newNode.node_type || "idea",
      maturity: newNode.maturity || "seed",
      tags: newNode.tags || [],
      meta: {},
      project_id: currentProject.id,
      status: "active",
      content_blocks: [],
      children: [],
      created_at: newNode.created_at || "",
      updated_at: newNode.updated_at || "",
    };
    const updated = insertChild(rootNode, expandTargetNodeId, child);
    const remaining = expandSuggestions.filter((_, i) => i !== index);
    set({
      rootNode: updated,
      expandSuggestions: remaining.length > 0 ? remaining : null,
    });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  acceptAllSuggestions: async () => {
    const { expandSuggestions, expandTargetNodeId, currentProject, rootNode } = get();
    if (!expandSuggestions || !expandTargetNodeId || !currentProject || !rootNode) return;

    const results = await Promise.allSettled(
      expandSuggestions.map((s) =>
        api.createNode(currentProject.id, {
          title: s.title,
          summary: s.summary,
          parent_id: expandTargetNodeId,
          node_type: s.node_type,
        })
      )
    );

    const failed = results.filter((r) => r.status === "rejected");
    if (failed.length === expandSuggestions.length) {
      set({ error: `${failed.length} of ${expandSuggestions.length} suggestions failed to create` });
    }

    set({ expandSuggestions: null });
    // Refresh tree from server to get accurate state regardless of partial failures
    await get().refreshTree();
  },

  acceptDeepen: async () => {
    const { deepenResult, rootNode } = get();
    if (!deepenResult || !rootNode) return;
    const targetId = deepenResult.target_node_id;
    await api.updateNode(targetId, { summary: deepenResult.enriched_summary } as Partial<GNode>);
    for (const block of deepenResult.content_blocks) {
      await api.createBlock(targetId, {
        block_type: block.block_type,
        content: { title: block.title, body: block.body },
      });
    }
    // Patch locally: update summary + append blocks
    const newBlocks = deepenResult.content_blocks.map((b, i) => ({
      id: `temp-${Date.now()}-${i}`,
      block_type: b.block_type,
      content: { title: b.title, body: b.body },
      order_index: i,
    }));
    const target = findNode(rootNode, targetId);
    const existingBlocks = target?.content_blocks || [];
    const updated = patchNode(rootNode, targetId, {
      summary: deepenResult.enriched_summary,
      content_blocks: [...existingBlocks, ...newBlocks],
    } as Partial<GNode>);
    set({ rootNode: updated, deepenResult: null });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  dismissAI: () => {
    set({ expandSuggestions: null, deepenResult: null });
  },
}));
