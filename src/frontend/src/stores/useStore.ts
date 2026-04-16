import { create } from "zustand";
import type { GNode, GrowthMode, Project } from "@/lib/types";
import { api } from "@/lib/api";

interface UndoEntry {
  rootNode: GNode;
  description: string;
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

  // Undo
  undoStack: UndoEntry[];
  toast: string | null;

  // Search
  searchQuery: string;
  highlightedNodeIds: string[];

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

function searchNodes(node: GNode, query: string): string[] {
  const results: string[] = [];
  if (query && node.title.toLowerCase().includes(query.toLowerCase())) {
    results.push(node.id);
  }
  for (const child of node.children || []) {
    results.push(...searchNodes(child, query));
  }
  return results;
}

const MAX_UNDO = 10;

function pushUndo(stack: UndoEntry[], rootNode: GNode, description: string): UndoEntry[] {
  const newStack = [{ rootNode, description }, ...stack];
  return newStack.slice(0, MAX_UNDO);
}

export const useStore = create<GrowthMapStore>((set, get) => ({
  projects: [],
  currentProject: null,
  rootNode: null,
  selectedNodeId: null,
  selectedNode: null,
  loading: false,
  error: null,
  expandSuggestions: null,
  expandTargetNodeId: null,
  deepenResult: null,
  aiLoading: false,
  undoStack: [],
  toast: null,
  searchQuery: "",
  highlightedNodeIds: [],

  loadProjects: async () => {
    try {
      const projects = await api.listProjects();
      set({ projects });
    } catch (e: unknown) {
      set({ error: (e as Error).message });
    }
  },

  selectProject: async (project) => {
    set({ loading: true, currentProject: project, selectedNodeId: null, selectedNode: null, undoStack: [] });
    try {
      const rootNode = await api.getSubtree(project.root_node_id);
      set({ rootNode, loading: false });
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
    const newUndoStack = pushUndo(undoStack, rootNode, `新增子節點: ${title}`);
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
    set({ rootNode: updated, undoStack: newUndoStack });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  updateNode: async (nodeId, data) => {
    const { rootNode, undoStack } = get();
    if (rootNode) {
      const newUndoStack = pushUndo(undoStack, rootNode, `更新節點`);
      set({ undoStack: newUndoStack });
    }
    await api.updateNode(nodeId, data);
    if (!rootNode) return;
    const updated = patchNode(rootNode, nodeId, data);
    set({ rootNode: updated });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  deleteNode: async (nodeId) => {
    const { rootNode, undoStack, selectedNodeId } = get();
    if (rootNode) {
      const node = findNode(rootNode, nodeId);
      const newUndoStack = pushUndo(undoStack, rootNode, `刪除節點: ${node?.title || nodeId}`);
      set({ undoStack: newUndoStack });
    }
    await api.deleteNode(nodeId);
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

  reparentNode: async (nodeId, newParentId) => {
    const { rootNode, undoStack } = get();
    if (!rootNode) return;
    const node = findNode(rootNode, nodeId);
    const newUndoStack = pushUndo(undoStack, rootNode, `移動節點: ${node?.title || nodeId}`);
    set({ undoStack: newUndoStack });
    try {
      await fetch(`/api/nodes/${nodeId}/reparent`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_parent_id: newParentId }),
      });
      await get().refreshTree();
    } catch (e: unknown) {
      set({ error: (e as Error).message });
    }
  },

  undo: () => {
    const { undoStack } = get();
    if (undoStack.length === 0) return;
    const [entry, ...rest] = undoStack;
    set({ rootNode: entry.rootNode, undoStack: rest, toast: `已復原: ${entry.description}` });
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
    const newUndoStack = pushUndo(undoStack, rootNode, `接受 AI 建議`);
    set({ undoStack: newUndoStack });
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
    const { expandSuggestions, expandTargetNodeId, currentProject, rootNode, undoStack } = get();
    if (!expandSuggestions || !expandTargetNodeId || !currentProject || !rootNode) return;
    const newUndoStack = pushUndo(undoStack, rootNode, `接受全部 AI 建議`);
    set({ undoStack: newUndoStack });
    let tree = rootNode;
    for (const s of expandSuggestions) {
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
      tree = insertChild(tree, expandTargetNodeId, child);
    }
    set({ rootNode: tree, expandSuggestions: null });
    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(tree, selectedNodeId) });
    }
  },

  acceptDeepen: async () => {
    const { deepenResult, rootNode, undoStack } = get();
    if (!deepenResult || !rootNode) return;
    const newUndoStack = pushUndo(undoStack, rootNode, `接受 AI 深化`);
    set({ undoStack: newUndoStack });
    const targetId = deepenResult.target_node_id;
    await api.updateNode(targetId, { summary: deepenResult.enriched_summary } as Partial<GNode>);
    for (const block of deepenResult.content_blocks) {
      await api.createBlock(targetId, {
        block_type: block.block_type,
        content: { title: block.title, body: block.body },
      });
    }
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
