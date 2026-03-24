import { create } from "zustand";
import type { GNode, Project } from "@/lib/types";
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

  // AI
  expandSuggestions: { title: string; summary: string; node_type: string }[] | null;
  expandTargetNodeId: string | null;
  deepenResult: { enriched_summary: string; content_blocks: { title: string; body: string; block_type: string }[]; target_node_id: string } | null;
  aiLoading: boolean;
  expandNode: (nodeId: string, instruction?: string) => Promise<void>;
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
    const { currentProject } = get();
    if (!currentProject) return;
    await api.createNode(currentProject.id, { title, parent_id: parentId, node_type: nodeType });
    await get().refreshTree();
  },

  updateNode: async (nodeId, data) => {
    await api.updateNode(nodeId, data);
    await get().refreshTree();
  },

  deleteNode: async (nodeId) => {
    await api.deleteNode(nodeId);
    const { selectedNodeId } = get();
    if (selectedNodeId === nodeId) set({ selectedNodeId: null, selectedNode: null });
    await get().refreshTree();
  },

  refreshTree: async () => {
    const { currentProject } = get();
    if (!currentProject) return;
    const rootNode = await api.getSubtree(currentProject.root_node_id);
    set({ rootNode });
    // Re-select current node
    const { selectedNodeId } = get();
    if (selectedNodeId && rootNode) {
      set({ selectedNode: findNode(rootNode, selectedNodeId) });
    }
  },

  expandNode: async (nodeId, instruction) => {
    set({ aiLoading: true, expandSuggestions: null, expandTargetNodeId: nodeId, deepenResult: null });
    try {
      const result = await api.expand(nodeId, instruction);
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
    const { expandSuggestions, expandTargetNodeId, currentProject } = get();
    if (!expandSuggestions || !expandTargetNodeId || !currentProject) return;
    const s = expandSuggestions[index];
    await api.createNode(currentProject.id, {
      title: s.title,
      summary: s.summary,
      parent_id: expandTargetNodeId,
      node_type: s.node_type,
    });
    const remaining = expandSuggestions.filter((_, i) => i !== index);
    set({ expandSuggestions: remaining.length > 0 ? remaining : null });
    await get().refreshTree();
  },

  acceptAllSuggestions: async () => {
    const { expandSuggestions, expandTargetNodeId, currentProject } = get();
    if (!expandSuggestions || !expandTargetNodeId || !currentProject) return;
    // Create all nodes sequentially to avoid race conditions
    for (const s of expandSuggestions) {
      await api.createNode(currentProject.id, {
        title: s.title,
        summary: s.summary,
        parent_id: expandTargetNodeId,
        node_type: s.node_type,
      });
    }
    set({ expandSuggestions: null });
    await get().refreshTree();
  },

  acceptDeepen: async () => {
    const { deepenResult } = get();
    if (!deepenResult) return;
    const targetId = deepenResult.target_node_id;
    await api.updateNode(targetId, { summary: deepenResult.enriched_summary } as Partial<GNode>);
    // Create content blocks
    for (const block of deepenResult.content_blocks) {
      await api.createBlock(targetId, {
        block_type: block.block_type,
        content: { title: block.title, body: block.body },
      });
    }
    set({ deepenResult: null });
    await get().refreshTree();
  },

  dismissAI: () => {
    set({ expandSuggestions: null, deepenResult: null });
  },
}));
