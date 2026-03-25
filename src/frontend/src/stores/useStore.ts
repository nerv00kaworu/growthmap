import { create } from "zustand";
import type { ContentBlock, GNode, GrowthMode, Project } from "@/lib/types";
import { api } from "@/lib/api";

interface GrowthMapStore {
  // State
  projects: Project[];
  currentProject: Project | null;
  rootNode: GNode | null;
  selectedNodeId: string | null;
  selectedNode: GNode | null;
  loading: boolean;
  error: string | null;

  // Actions
  loadProjects: () => Promise<void>;
  selectProject: (project: Project) => Promise<void>;
  selectNode: (nodeId: string | null) => void;
  createProject: (name: string, description?: string, goal?: string) => Promise<void>;
  addChildNode: (parentId: string, title: string, nodeType?: string) => Promise<void>;
  updateNode: (nodeId: string, data: Partial<GNode>) => Promise<void>;
  deleteNode: (nodeId: string) => Promise<void>;
  refreshTree: () => Promise<void>;
  updateContentBlock: (nodeId: string, blockId: string, data: { content?: Record<string, string>; block_type?: string }) => Promise<void>;
  deleteContentBlock: (nodeId: string, blockId: string) => Promise<void>;

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

function appendContentBlocks(root: GNode, nodeId: string, blocks: ContentBlock[]): GNode {
  if (root.id === nodeId) {
    return {
      ...root,
      content_blocks: [...(root.content_blocks || []), ...blocks],
    };
  }

  return {
    ...root,
    children: (root.children || []).map((c) => appendContentBlocks(c, nodeId, blocks)),
  };
}

function patchContentBlock(
  root: GNode,
  nodeId: string,
  blockId: string,
  patch: Partial<ContentBlock>
): GNode {
  if (root.id === nodeId) {
    return {
      ...root,
      content_blocks: (root.content_blocks || []).map((block) =>
        block.id === blockId ? { ...block, ...patch } : block
      ),
    };
  }

  return {
    ...root,
    children: (root.children || []).map((c) => patchContentBlock(c, nodeId, blockId, patch)),
  };
}

function removeContentBlock(root: GNode, nodeId: string, blockId: string): GNode {
  if (root.id === nodeId) {
    return {
      ...root,
      content_blocks: (root.content_blocks || []).filter((block) => block.id !== blockId),
    };
  }

  return {
    ...root,
    children: (root.children || []).map((c) => removeContentBlock(c, nodeId, blockId)),
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
  expandSuggestions: null,
  expandTargetNodeId: null,
  deepenResult: null,
  aiLoading: false,

  loadProjects: async () => {
    try {
      const projects = await api.listProjects();
      set({ projects });
    } catch (e: unknown) {
      set({ error: (e as Error).message });
    }
  },

  selectProject: async (project) => {
    set({ loading: true, currentProject: project, selectedNodeId: null, selectedNode: null });
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

  updateContentBlock: async (nodeId, blockId, data) => {
    const updatedBlock = await api.updateBlock(blockId, data);
    const { rootNode } = get();
    if (!rootNode) return;

    const updated = patchContentBlock(rootNode, nodeId, blockId, updatedBlock);
    set({ rootNode: updated });

    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
    }
  },

  deleteContentBlock: async (nodeId, blockId) => {
    await api.deleteBlock(blockId);
    const { rootNode } = get();
    if (!rootNode) return;

    const updated = removeContentBlock(rootNode, nodeId, blockId);
    set({ rootNode: updated });

    const { selectedNodeId } = get();
    if (selectedNodeId) {
      set({ selectedNode: findNode(updated, selectedNodeId) });
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
    const { deepenResult, rootNode } = get();
    if (!deepenResult || !rootNode) return;
    const targetId = deepenResult.target_node_id;
    await api.updateNode(targetId, { summary: deepenResult.enriched_summary } as Partial<GNode>);
    const createdBlocks: ContentBlock[] = [];
    for (const block of deepenResult.content_blocks) {
      const createdBlock = await api.createBlock(targetId, {
        block_type: block.block_type,
        content: { title: block.title, body: block.body },
      });
      createdBlocks.push(createdBlock);
    }

    const updatedSummary = patchNode(rootNode, targetId, {
      summary: deepenResult.enriched_summary,
    } as Partial<GNode>);
    const updated = appendContentBlocks(updatedSummary, targetId, createdBlocks);
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
