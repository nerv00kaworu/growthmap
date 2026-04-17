// API client for GrowthMap backend
const BASE = typeof window !== "undefined" ? `${window.location.origin}/api` : "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

import type { Project, GNode, GrowthMode, Branch } from "./types";
import { loadLLMConfig, type LLMConfig } from "./llm-provider";

function getLLMPayload(): Record<string, unknown> | undefined {
  const config = loadLLMConfig();
  if (!config) return undefined;
  // Map frontend provider types to backend-compatible base_url
  const providerBaseUrls: Record<string, string> = {
    openai: "https://api.openai.com/v1",
    anthropic: "https://api.anthropic.com/v1", // backend uses OpenAI-compat, may not work for Anthropic native
  };
  return {
    provider: config.provider,
    api_key: config.apiKey,
    base_url: config.baseUrl || providerBaseUrls[config.provider] || undefined,
    model: config.model || undefined,
  };
}

export const api = {
  // Projects
  listProjects: () => request<Project[]>("/projects"),
  createProject: (data: { name: string; description?: string; goal?: string }) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(data) }),

  // Nodes
  getSubtree: (nodeId: string) => request<GNode>(`/nodes/${nodeId}/subtree`),
  getNode: (nodeId: string) => request<GNode>(`/nodes/${nodeId}`),
  createNode: (projectId: string, data: { title: string; parent_id?: string; node_type?: string; summary?: string }) =>
    request<GNode>(`/projects/${projectId}/nodes`, { method: "POST", body: JSON.stringify(data) }),
  updateNode: (nodeId: string, data: Partial<GNode>) =>
    request<GNode>(`/nodes/${nodeId}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteNode: (nodeId: string) =>
    request<void>(`/nodes/${nodeId}`, { method: "DELETE" }),

  // Edges
  createEdge: (data: { from_node_id: string; to_node_id: string; relation_type?: string; is_mainline?: boolean }) =>
    request(`/edges`, { method: "POST", body: JSON.stringify(data) }),
  promoteMainline: (edgeId: string) =>
    request(`/edges/${edgeId}/promote-mainline`, { method: "POST" }),
  promoteChildMainline: (parentId: string, childId: string) =>
    request(`/nodes/${parentId}/promote-child/${childId}`, { method: "POST" }),

  // Content blocks
  getBlocks: (nodeId: string) =>
    request<{ id: string; node_id: string; block_type: string; content: Record<string, string>; order_index: number }[]>(`/nodes/${nodeId}/blocks`),
  createBlock: (nodeId: string, data: { block_type: string; content: Record<string, string> }) =>
    request(`/nodes/${nodeId}/blocks`, { method: "POST", body: JSON.stringify(data) }),
  updateBlock: (blockId: string, data: { content?: Record<string, string>; block_type?: string }) =>
    request(`/blocks/${blockId}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteBlock: (blockId: string) =>
    request<void>(`/blocks/${blockId}`, { method: "DELETE" }),

  // History
  getHistory: (nodeId: string) =>
    request<{ id: string; action_type: string; actor_type: string; payload: Record<string, unknown>; created_at: string }[]>(`/nodes/${nodeId}/history`),

  // AI operations
  expand: (nodeId: string, instruction?: string, count?: number, mode: GrowthMode = "explore") =>
    request<{
      suggestions: { title: string; summary: string; node_type: string }[];
      context_used: Record<string, unknown>;
    }>("/ai/expand", {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId, instruction, count: count || 3, mode, llm_config: getLLMPayload() }),
    }),

  deepen: (nodeId: string, instruction?: string) =>
    request<{
      enriched_summary: string;
      content_blocks: { title: string; body: string; block_type: string }[];
      context_used: Record<string, unknown>;
    }>("/ai/deepen", {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId, instruction, llm_config: getLLMPayload() }),
    }),

  chat: (nodeId: string, message: string, history: { role: string; content: string }[]) =>
    request<{ reply: string; context_used: Record<string, unknown> }>("/ai/chat", {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId, message, history, llm_config: getLLMPayload() }),
    }),

  // Spec export (returns text)
  exportSpec: async (projectId: string): Promise<string> => {
    const res = await fetch(`${BASE}/projects/${projectId}/export-spec`);
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
    return res.text();
  },

  // Branches
  listBranches: (projectId: string) =>
    request<Branch[]>(`/projects/${projectId}/branches`),
  createBranch: (projectId: string, data: { source_node_id: string; name: string; description?: string }) =>
    request<Branch>(`/projects/${projectId}/branches`, { method: "POST", body: JSON.stringify(data) }),
  getBranch: (branchId: string) =>
    request<Branch>(`/branches/${branchId}`),
  getBranchSubtree: (branchId: string) =>
    request<{ branch: Branch; tree: GNode | null }>(`/branches/${branchId}/subtree`),
  mergeBranch: (branchId: string, targetNodeId: string) =>
    request<{ ok: boolean }>(`/branches/${branchId}/merge`, {
      method: "POST",
      body: JSON.stringify({ target_node_id: targetNodeId }),
    }),
  archiveBranch: (branchId: string) =>
    request<void>(`/branches/${branchId}`, { method: "DELETE" }),
};


