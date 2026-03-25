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

import type { Project, GNode, GrowthMode, ContentBlock } from "./types";

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

  // Content blocks
  getBlocks: (nodeId: string) =>
    request<ContentBlock[]>(`/nodes/${nodeId}/blocks`),
  createBlock: (nodeId: string, data: { block_type: string; content: Record<string, string> }) =>
    request<ContentBlock>(`/nodes/${nodeId}/blocks`, { method: "POST", body: JSON.stringify(data) }),
  updateBlock: (blockId: string, data: { content?: Record<string, string>; block_type?: string }) =>
    request<ContentBlock>(`/blocks/${blockId}`, { method: "PATCH", body: JSON.stringify(data) }),
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
      body: JSON.stringify({ node_id: nodeId, instruction, count: count || 3, mode }),
    }),

  deepen: (nodeId: string, instruction?: string) =>
    request<{
      enriched_summary: string;
      content_blocks: { title: string; body: string; block_type: string }[];
      context_used: Record<string, unknown>;
    }>("/ai/deepen", {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId, instruction }),
    }),
};
