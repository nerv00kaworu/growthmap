// API client for GrowthMap backend
const BASE = typeof window !== "undefined" ? `${window.location.origin}/api` : "/api";

const revisionCache = {
  projects: new Map<string, number>(),
  nodes: new Map<string, { projectId: string; revision: number }>(),
  edges: new Map<string, { projectId: string; revision: number }>(),
  blocks: new Map<string, { nodeId: string; revision: number }>(),
  branches: new Map<string, { projectId: string; revision: number }>(),
};

/** Test fixture boundary; production callers must populate cache via API reads. */
export function resetRevisionCacheForTests(): void {
  revisionCache.projects.clear(); revisionCache.nodes.clear(); revisionCache.edges.clear();
  revisionCache.blocks.clear(); revisionCache.branches.clear();
}

function remember(value: unknown): void {
  if (Array.isArray(value)) { value.forEach(remember); return; }
  if (!value || typeof value !== "object") return;
  const row = value as Record<string, unknown>;
  const id = typeof row.id === "string" ? row.id : undefined;
  const revision = typeof row.revision === "number" ? row.revision : undefined;
  if (id && revision) {
    if (typeof row.authoritative_project_revision === "number" && typeof row.project_id === "string") {
      revisionCache.projects.set(row.project_id, row.authoritative_project_revision);
    }
    if (typeof row.authoritative_parent_revision === "number" && typeof row.authoritative_parent_id === "string") {
      const cachedParent = revisionCache.nodes.get(row.authoritative_parent_id);
      if (cachedParent) revisionCache.nodes.set(row.authoritative_parent_id, { ...cachedParent, revision: row.authoritative_parent_revision });
    }
    if (typeof row.authoritative_from_revision === "number" && typeof row.from_node_id === "string") {
      const cached = revisionCache.nodes.get(row.from_node_id);
      if (cached) revisionCache.nodes.set(row.from_node_id, { ...cached, revision: row.authoritative_from_revision });
    }
    if (typeof row.authoritative_to_revision === "number" && typeof row.to_node_id === "string") {
      const cached = revisionCache.nodes.get(row.to_node_id);
      if (cached) revisionCache.nodes.set(row.to_node_id, { ...cached, revision: row.authoritative_to_revision });
    }
    if (typeof row.node_id === "string" && typeof row.block_type === "string") {
      const owner = revisionCache.nodes.get(row.node_id);
      if (owner && typeof row.authoritative_project_revision === "number")
        revisionCache.projects.set(owner.projectId, row.authoritative_project_revision);
      if (owner && typeof row.authoritative_node_revision === "number")
        revisionCache.nodes.set(row.node_id, { ...owner, revision: row.authoritative_node_revision });
    }
    if (typeof row.root_node_id === "string") revisionCache.projects.set(id, revision);
    else if (typeof row.from_node_id === "string" && typeof row.project_id === "string") revisionCache.edges.set(id, { projectId: row.project_id, revision });
    else if (typeof row.node_id === "string" && typeof row.block_type === "string") revisionCache.blocks.set(id, { nodeId: row.node_id, revision });
    else if (typeof row.source_node_id === "string" && typeof row.project_id === "string") revisionCache.branches.set(id, { projectId: row.project_id, revision });
    else if (typeof row.project_id === "string" && typeof row.node_type === "string") revisionCache.nodes.set(id, { projectId: row.project_id, revision });
  }
  Object.values(row).forEach(remember);
}

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly code: string | undefined, message: string, public readonly detail?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

export class ContentBlockReorderError extends Error {
  constructor(message: string, public readonly partialSuccess: boolean, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "ContentBlockReorderError";
  }
}

export async function persistSequentialBlockReorder<T>({
  nodeId, currentId, currentOrder, targetId, targetOrder, updateBlock, getBlocks, applyAuthoritativeBlocks,
}: {
  nodeId: string; currentId: string; currentOrder: number; targetId: string; targetOrder: number;
  updateBlock: (blockId: string, orderIndex: number) => Promise<unknown>;
  getBlocks: (nodeId: string) => Promise<T[]>;
  applyAuthoritativeBlocks: (blocks: T[]) => void;
}): Promise<void> {
  let firstCommitted = false;
  try {
    await updateBlock(currentId, currentOrder);
    firstCommitted = true;
    await updateBlock(targetId, targetOrder);
  } catch (patchError) {
    // Two PATCHes cannot be atomic. Never pretend to roll both back after the
    // first commit: read the server truth and render that partial state.
    try {
      const authoritative = await getBlocks(nodeId);
      applyAuthoritativeBlocks(authoritative);
      throw new ContentBlockReorderError(
        firstCommitted ? "排序只完成部分，已重新載入伺服器狀態" : "排序未完成，已重新載入伺服器狀態",
        firstCommitted,
        { cause: patchError },
      );
    } catch (refreshError) {
      if (refreshError instanceof ContentBlockReorderError) throw refreshError;
      throw new ContentBlockReorderError(
        firstCommitted
          ? "排序可能只完成部分，且無法重新載入伺服器狀態，請重新整理"
          : "排序未完成，且無法重新載入伺服器狀態，請重新整理",
        firstCommitted,
        { cause: new AggregateError([patchError, refreshError], "block reorder and authoritative refresh failed") },
      );
    }
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    let detail: unknown = text;
    let code: string | undefined;
    let message = text;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      detail = parsed.detail ?? parsed;
      if (detail && typeof detail === "object") {
        const row = detail as Record<string, unknown>;
        code = typeof row.code === "string" ? row.code : undefined;
        if (typeof row.message === "string") message = row.message;
      }
    } catch { /* retain plain-text response */ }
    throw new ApiError(res.status, code, message || `API ${res.status}`, detail);
  }
  if (res.status === 204) return undefined as T;
  const value = await res.json() as T;
  const row = value && typeof value === "object" ? value as Record<string, unknown> : undefined;
  const isBlockPatch = options?.method === "PATCH" && path.startsWith("/blocks/");
  if (!isBlockPatch || (typeof row?.authoritative_project_revision === "number" &&
      typeof row?.authoritative_node_revision === "number" &&
      typeof row?.authoritative_block_revision === "number")) remember(value);
  return value;
}

function projectExpected(projectId: string): number {
  const revision = revisionCache.projects.get(projectId);
  if (!revision) throw new Error("Revision state unavailable; refresh the project and retry");
  return revision;
}

function nodeExpected(nodeId: string) {
  const row = revisionCache.nodes.get(nodeId);
  if (!row) throw new Error("Node revision unavailable; refresh and retry");
  return { expected_project_revision: projectExpected(row.projectId), expected_revision: row.revision };
}

function blockExpected(blockId: string) {
  const block = revisionCache.blocks.get(blockId);
  if (!block) throw new Error("Block revision unavailable; refresh and retry");
  const node = revisionCache.nodes.get(block.nodeId);
  if (!node) throw new Error("Node revision unavailable; refresh and retry");
  return { expected_project_revision: projectExpected(node.projectId), expected_node_revision: node.revision, expected_revision: block.revision };
}


import type { Project, GNode, GrowthMode, Branch, BranchComparison, ProviderConfig, AgentSession, AgentSessionStatus, AgentArtifact, Edge } from "./types";
import type { Entitlement } from "./entitlement";

export type AgentPortRecord={name:string;status:string;detail:string};
export type AgentPortReadback={id:string;target_node_id:string|null;summary:string;based_on_project_revision:number;context_snapshot_digest:string;objective:string;current_project_revision:number;context_stale:boolean;commit_refs:string[];files:string[];tests:AgentPortRecord[];decisions:string[];risks:string[];todos:string[];evidence:AgentPortRecord[];created_at:string};
export type AgentPortActivity={proposals:Record<string,unknown>[];events:Record<string,unknown>[];readbacks:AgentPortReadback[]};
import { loadLLMConfig } from "./llm-provider";

function getProviderId(): string | undefined {
  return loadLLMConfig()?.providerId || undefined;
}

export const api = {
  listAgentGrants: (projectId: string) => request<Record<string, unknown>[]>(`/agent-port/grants?project_id=${encodeURIComponent(projectId)}`),
  createAgentGrant: (data: Record<string, unknown>) => request<Record<string, unknown>>("/agent-port/grants", {method:"POST",body:JSON.stringify(data)}),
  revokeAgentGrant: (id: string) => request<Record<string, unknown>>(`/agent-port/grants/${id}/revoke`, {method:"POST"}),
  getAgentPortActivity: (projectId: string) => request<AgentPortActivity>(`/agent-port/activity?project_id=${encodeURIComponent(projectId)}`),
  reviewAgentProposal: (id:string, decision:"approve"|"reject", review_note="") => request<Record<string, unknown>>(`/agent-port/proposals/${id}/${decision}`, {method:"POST",body:JSON.stringify({review_note})}),
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
  approveAgentArtifact: (artifactId: string, targetNodeId: string, reviewNote = "") => {
    const expected = nodeExpected(targetNodeId);
    return request<AgentArtifact>(`/agent-artifacts/${artifactId}/approve`, { method: "POST", body: JSON.stringify({ review_note: reviewNote, expected_project_revision: expected.expected_project_revision, expected_node_revision: expected.expected_revision }) });
  },
  rejectAgentArtifact: (artifactId: string, reviewNote = "") =>
    request<AgentArtifact>(`/agent-artifacts/${artifactId}/reject`, { method: "POST", body: JSON.stringify({ review_note: reviewNote }) }),

  // Projects
  listProjects: () => request<Project[]>("/projects"),
  createProject: (data: { name: string; description?: string; goal?: string }) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(data) }),
  updateProject: (projectId: string, data: Partial<Pick<Project, "status">> & { expected_project_revision?: number }) =>
    request<Project>(`/projects/${projectId}`, { method: "PATCH", body: JSON.stringify({ ...data, expected_project_revision: data.expected_project_revision ?? projectExpected(projectId) }) }),
  getEntitlement: () => request<Entitlement>("/desktop/entitlement", { cache: "no-store" }),

  // Nodes
  getSubtree: (nodeId: string) => request<GNode>(`/nodes/${nodeId}/subtree`),
  getNode: (nodeId: string) => request<GNode>(`/nodes/${nodeId}`),
  createNode: (projectId: string, data: { expected_project_revision?: number; expected_parent_revision?: number; title: string; parent_id?: string; branch_id?: string; node_type?: string; summary?: string }) => {
    const parent = data.parent_id ? revisionCache.nodes.get(data.parent_id) : undefined;
    if (data.parent_id && !parent) throw new Error("Parent revision unavailable; refresh and retry");
    return request<GNode>(`/projects/${projectId}/nodes`, { method: "POST", body: JSON.stringify({
      ...data,
      expected_project_revision: data.expected_project_revision ?? projectExpected(projectId),
      ...(data.parent_id ? { expected_parent_revision: data.expected_parent_revision ?? parent!.revision } : {}),
    }) });
  },
  updateNode: (nodeId: string, data: Partial<GNode> & { expected_project_revision?: number; expected_revision?: number }) =>
    request<GNode>(`/nodes/${nodeId}`, { method: "PATCH", body: JSON.stringify({ ...nodeExpected(nodeId), ...data }) }),
  updateEdge: (edgeId: string, data: { expected_project_revision?: number; expected_revision?: number; weight?: number; note?: string }) => {
    const edge = revisionCache.edges.get(edgeId); if (!edge) throw new Error("Edge revision unavailable; refresh and retry");
    return request<Edge>(`/edges/${edgeId}`, { method: "PATCH", body: JSON.stringify({ expected_project_revision: projectExpected(edge.projectId), expected_revision: edge.revision, ...data }) });
  },
  deleteEdge: (edgeId: string, expectedProjectRevision?: number, expectedRevision?: number) => {
    const edge = revisionCache.edges.get(edgeId); if (!edge) throw new Error("Edge revision unavailable; refresh and retry");
    return request<void>(`/edges/${edgeId}`, { method: "DELETE", body: JSON.stringify({ expected_project_revision: expectedProjectRevision ?? projectExpected(edge.projectId), expected_revision: expectedRevision ?? edge.revision }) });
  },
  deleteNode: (nodeId: string, expectedProjectRevision: number, expectedRevision: number) =>
    request<void>(`/nodes/${nodeId}`, { method: "DELETE", body: JSON.stringify({ expected_project_revision: expectedProjectRevision, expected_revision: expectedRevision }) }),

  // Edges
  listEdges: (projectId: string, relationType?: string) =>
    request<Edge[]>(`/projects/${projectId}/edges${relationType ? `?relation_type=${encodeURIComponent(relationType)}` : ""}`),
  createEdge: (data: { expected_project_revision?: number; from_node_id: string; to_node_id: string; relation_type?: string; is_mainline?: boolean }) => {
    const from = revisionCache.nodes.get(data.from_node_id);
    const to = revisionCache.nodes.get(data.to_node_id);
    if (!from || !to) throw new Error("Endpoint revision unavailable; refresh and retry");
    if (from.projectId !== to.projectId) throw new Error("Edge endpoints must belong to the same project");
    return request<Edge>(`/edges`, { method: "POST", body: JSON.stringify({
      ...data,
      expected_project_revision: data.expected_project_revision ?? projectExpected(from.projectId),
      expected_from_revision: from.revision,
      expected_to_revision: to.revision,
    }) });
  },
  promoteMainline: (edgeId: string, expectedProjectRevision: number, expectedRevision: number) =>
    request<Edge>(`/edges/${edgeId}/promote-mainline`, { method: "POST", body: JSON.stringify({ expected_project_revision: expectedProjectRevision, expected_revision: expectedRevision }) }),
  promoteChildMainline: (parentId: string, childId: string, expectedProjectRevision: number, expectedRevision: number) =>
    request(`/nodes/${parentId}/promote-child/${childId}`, { method: "POST", body: JSON.stringify({ expected_project_revision: expectedProjectRevision, expected_revision: expectedRevision }) }),

  // Content blocks
  getBlocks: (nodeId: string) =>
    request<{ id: string; node_id: string; block_type: string; content: Record<string, string>; order_index: number; revision: number }[]>(`/nodes/${nodeId}/blocks`),
  createBlock: (nodeId: string, data: { block_type: string; content: Record<string, string>; order_index?: number }) => {
    const node = nodeExpected(nodeId);
    return request<{ id: string; node_id: string; block_type: string; content: Record<string, string>; order_index: number; revision: number; authoritative_project_revision?: number; authoritative_node_revision?: number; authoritative_block_revision?: number }>(`/nodes/${nodeId}/blocks`, { method: "POST", body: JSON.stringify({ ...data, expected_project_revision: node.expected_project_revision, expected_node_revision: node.expected_revision }) });
  },
  updateBlock: (blockId: string, data: { content?: unknown; block_type?: string; order_index?: number }) =>
    request(`/blocks/${blockId}`, { method: "PATCH", body: JSON.stringify({ ...data, ...blockExpected(blockId) }) }),
  deleteBlock: (blockId: string, expectedProjectRevision?: number, expectedNodeRevision?: number, expectedRevision?: number) => {
    const expected = blockExpected(blockId);
    return request<void>(`/blocks/${blockId}`, { method: "DELETE", body: JSON.stringify({ ...expected, expected_project_revision: expectedProjectRevision ?? expected.expected_project_revision, expected_node_revision: expectedNodeRevision ?? expected.expected_node_revision, expected_revision: expectedRevision ?? expected.expected_revision }) });
  },

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
  createBranch: (projectId: string, data: { expected_project_revision: number; source_node_id: string; name: string; description?: string }) =>
    request<Branch>(`/projects/${projectId}/branches`, { method: "POST", body: JSON.stringify(data) }),
  getBranch: (branchId: string) =>
    request<Branch>(`/branches/${branchId}`),
  getBranchSubtree: (branchId: string) =>
    request<{ branch: Branch; tree: GNode | null }>(`/branches/${branchId}/subtree`),
  compareBranch: (branchId: string) =>
    request<BranchComparison>(`/branches/${branchId}/compare`),
  getBranchHistory: (branchId: string) =>
    request<{ id: string; action_type: string; actor_type: string; payload: Record<string, unknown>; created_at: string }[]>(`/branches/${branchId}/history`),
  mergeBranch: (branchId: string, targetNodeId: string, expectedProjectRevision: number, expectedRevision: number, expectedTargetRevision: number) =>
    request<{ ok: boolean }>(`/branches/${branchId}/merge`, {
      method: "POST",
      body: JSON.stringify({ target_node_id: targetNodeId, expected_project_revision: expectedProjectRevision, expected_revision: expectedRevision, expected_target_revision: expectedTargetRevision }),
    }),
  archiveBranch: (branchId: string, expectedProjectRevision: number, expectedRevision: number) =>
    request<void>(`/branches/${branchId}`, { method: "DELETE", body: JSON.stringify({ expected_project_revision: expectedProjectRevision, expected_revision: expectedRevision }) }),
};


