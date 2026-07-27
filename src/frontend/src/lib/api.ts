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

import type { Project, GNode, GrowthMode, Branch, BranchComparison, ProviderConfig, AgentSession, AgentSessionStatus, AgentArtifact, Edge } from "./types";
import { loadLLMConfig } from "./llm-provider";

function getProviderId(): string | undefined {
  return loadLLMConfig()?.providerId || undefined;
}

export const api = {
  // Server-side provider profiles. API keys remain in local environment variables.
  listProviders: () => request<ProviderConfig[]>("/providers"),
  createProvider: (data: Omit<ProviderConfig, "id" | "auth_type" | "created_at" | "updated_at">) =>
    request<ProviderConfig>("/providers", { method: "POST", body: JSON.stringify(data) }),
  updateProvider: (providerId: string, data: Partial<Omit<ProviderConfig, "id" | "auth_type" | "created_at" | "updated_at">>) =>
    request<ProviderConfig>(`/providers/${providerId}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteProvider: (providerId: string) => request<void>(`/providers/${providerId}`, { method: "DELETE" }),
  writeProviderSecret: (providerId: string, apiKey: string) =>
    request<void>(`/providers/${providerId}/secret`, { method: "PUT", body: JSON.stringify({ api_key: apiKey }) }),

  // Manual agent-session workflow. This records work only; it never dispatches an LLM or external agent.
  listAgentSessions: (projectId: string, status?: AgentSessionStatus) =>
    request<AgentSession[]>(`/agent-sessions?project_id=${encodeURIComponent(projectId)}${status ? `&status=${status}` : ""}`),
  createAgentSession: (data: { project_id: string; assigned_node_id?: string; assigned_branch_root_id?: string; provider_id?: string; objective: string; mode: AgentSession["mode"]; handoff_context?: Record<string, unknown> }) =>
    request<AgentSession>("/agent-sessions", { method: "POST", body: JSON.stringify(data) }),
  updateAgentSession: (sessionId: string, data: { status?: AgentSessionStatus; result_summary?: string; handoff_context?: Record<string, unknown> }) =>
    request<AgentSession>(`/agent-sessions/${sessionId}`, { method: "PATCH", body: JSON.stringify(data) }),
  getAgentSessionHistory: (sessionId: string) =>
    request<{ id: string; action_type: string; actor_type: string; payload: Record<string, unknown>; created_at: string }[]>(`/agent-sessions/${sessionId}/history`),
  listAgentArtifacts: (sessionId: string) => request<AgentArtifact[]>(`/agent-sessions/${sessionId}/artifacts`),
  createAgentArtifact: (sessionId: string, data: { target_node_id: string; artifact_type: AgentArtifact["artifact_type"]; payload: Record<string, unknown> }) =>
    request<AgentArtifact>(`/agent-sessions/${sessionId}/artifacts`, { method: "POST", body: JSON.stringify(data) }),
  approveAgentArtifact: (artifactId: string, reviewNote = "") =>
    request<AgentArtifact>(`/agent-artifacts/${artifactId}/approve`, { method: "POST", body: JSON.stringify({ review_note: reviewNote }) }),
  rejectAgentArtifact: (artifactId: string, reviewNote = "") =>
    request<AgentArtifact>(`/agent-artifacts/${artifactId}/reject`, { method: "POST", body: JSON.stringify({ review_note: reviewNote }) }),

  // Projects
  listProjects: () => request<Project[]>("/projects"),
  createProject: (data: { name: string; description?: string; goal?: string }) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(data) }),

  // Nodes
  getSubtree: (nodeId: string) => request<GNode>(`/nodes/${nodeId}/subtree`),
  getNode: (nodeId: string) => request<GNode>(`/nodes/${nodeId}`),
  createNode: (projectId: string, data: { title: string; parent_id?: string; branch_id?: string; node_type?: string; summary?: string }) =>
    request<GNode>(`/projects/${projectId}/nodes`, { method: "POST", body: JSON.stringify(data) }),
  updateNode: (nodeId: string, data: Partial<GNode>) =>
    request<GNode>(`/nodes/${nodeId}`, { method: "PATCH", body: JSON.stringify(data) }),
  updateEdge: (edgeId: string, data: { weight?: number; note?: string }) =>
    request<{ id: string; project_id: string; from_node_id: string; to_node_id: string; relation_type: string; weight: number; note: string; is_mainline: boolean; created_at: string }>(`/edges/${edgeId}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteEdge: (edgeId: string) => request<void>(`/edges/${edgeId}`, { method: "DELETE" }),
  deleteNode: (nodeId: string) =>
    request<void>(`/nodes/${nodeId}`, { method: "DELETE" }),

  // Edges
  listEdges: (projectId: string, relationType?: string) =>
    request<Edge[]>(`/projects/${projectId}/edges${relationType ? `?relation_type=${encodeURIComponent(relationType)}` : ""}`),
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
  updateBlock: (blockId: string, data: { content?: Record<string, string>; block_type?: string; order_index?: number }) =>
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
      body: JSON.stringify({ node_id: nodeId, instruction, count: count || 3, mode, provider_id: getProviderId() }),
    }),

  deepen: (nodeId: string, instruction?: string) =>
    request<{
      enriched_summary: string;
      content_blocks: { title: string; body: string; block_type: string }[];
      context_used: Record<string, unknown>;
    }>("/ai/deepen", {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId, instruction, provider_id: getProviderId() }),
    }),

  chat: (nodeId: string, message: string, history: { role: string; content: string }[]) =>
    request<{ reply: string; context_used: Record<string, unknown> }>("/ai/chat", {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId, message, history, provider_id: getProviderId() }),
    }),

  // Test LLM connection
  testConnection: (providerId: string) =>
    request<{ ok: boolean; provider: string; model?: string; message: string }>("/ai/test-connection", {
      method: "POST",
      body: JSON.stringify({ provider_id: providerId }),
    }),

  // Spec export (returns text)
  exportSpec: async (projectId: string): Promise<string> => {
    const res = await fetch(`${BASE}/projects/${projectId}/export-spec`);
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
    return res.text();
  },

  // Branches
  listBranches: (projectId: string, includeInactive = false) =>
    request<Branch[]>(`/projects/${projectId}/branches${includeInactive ? "?include_inactive=true" : ""}`),
  createBranch: (projectId: string, data: { source_node_id: string; name: string; description?: string }) =>
    request<Branch>(`/projects/${projectId}/branches`, { method: "POST", body: JSON.stringify(data) }),
  getBranch: (branchId: string) =>
    request<Branch>(`/branches/${branchId}`),
  getBranchSubtree: (branchId: string) =>
    request<{ branch: Branch; tree: GNode | null }>(`/branches/${branchId}/subtree`),
  compareBranch: (branchId: string) =>
    request<BranchComparison>(`/branches/${branchId}/compare`),
  getBranchHistory: (branchId: string) =>
    request<{ id: string; action_type: string; actor_type: string; payload: Record<string, unknown>; created_at: string }[]>(`/branches/${branchId}/history`),
  mergeBranch: (branchId: string, targetNodeId: string) =>
    request<{ ok: boolean }>(`/branches/${branchId}/merge`, {
      method: "POST",
      body: JSON.stringify({ target_node_id: targetNodeId }),
    }),
  archiveBranch: (branchId: string) =>
    request<void>(`/branches/${branchId}`, { method: "DELETE" }),
};


