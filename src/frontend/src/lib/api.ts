// API client for GrowthMap backend
const BASE = typeof window !== "undefined" ? `${window.location.origin}/api` : "/api";

import type { Project, GNode, GrowthMode, Branch, BranchComparison, ProviderConfig, AgentSession, AgentSessionStatus, AgentArtifact, Edge } from "./types";
import type { Entitlement } from "./entitlement";


export class ApiError extends Error {
  constructor(public readonly status: number, public readonly code: string | undefined, message: string, public readonly detail?: unknown, public readonly requestId?: string) {
    super(message);
    this.name = "ApiError";
  }
}

export const AI_DIAGNOSTIC_STATUS = {
  LLM_PROFILE_CHANGED: 409,
  LLM_CONFIGURATION_ERROR: 400,
  LLM_AUTH_FAILED: 401,
  LLM_RATE_LIMITED: 429,
  LLM_UPSTREAM_ERROR: 502,
  LLM_INVALID_RESPONSE: 502,
  LLM_TIMEOUT: 504,
} as const;
export type AIDiagnosticCode = keyof typeof AI_DIAGNOSTIC_STATUS;
const REQUEST_ID = /^[0-9a-f]{16}$/;
const MAX_AI_ERROR_BODY = 2048;
const SAFE_AI_FALLBACK_CODE = "LLM_INVALID_RESPONSE";
const SAFE_AI_FALLBACK_STATUS = 502;
const SAFE_AI_FALLBACK = "The AI diagnostic response could not be validated.";

export function parseAIError(status: number, text: string): ApiError {
  if (new TextEncoder().encode(text).byteLength > MAX_AI_ERROR_BODY) return new ApiError(SAFE_AI_FALLBACK_STATUS, SAFE_AI_FALLBACK_CODE, SAFE_AI_FALLBACK);
  try {
    const outer = JSON.parse(text) as unknown;
    if (!outer || typeof outer !== "object" || Array.isArray(outer) || Object.keys(outer).length !== 1 || !("detail" in outer)) throw new Error();
    const detail = (outer as {detail: unknown}).detail;
    if (!detail || typeof detail !== "object" || Array.isArray(detail)) throw new Error();
    const row = detail as Record<string, unknown>;
    if (Object.keys(row).length !== 3 || !Object.hasOwn(row,"code") || !Object.hasOwn(row,"message") || !Object.hasOwn(row,"request_id")) throw new Error();
    if (typeof row.code !== "string" || !(row.code in AI_DIAGNOSTIC_STATUS)) throw new Error();
    const code = row.code as AIDiagnosticCode;
    if (AI_DIAGNOSTIC_STATUS[code] !== status || typeof row.message !== "string" || row.message.length > 512 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(row.message)) throw new Error();
    if (typeof row.request_id !== "string" || !REQUEST_ID.test(row.request_id)) throw new Error();
    return new ApiError(status, code, SAFE_AI_FALLBACK, undefined, row.request_id);
  } catch {
    return new ApiError(SAFE_AI_FALLBACK_STATUS, SAFE_AI_FALLBACK_CODE, SAFE_AI_FALLBACK);
  }
}

function activeLocale(): "zh-TW" | "zh-CN" | "en" {
  if (typeof window === "undefined") return "en";
  try { const value=window.localStorage.getItem("growthmap.locale"); return value === "zh-TW" || value === "zh-CN" ? value : "en"; } catch { return "en"; }
}


export interface AgentPortRecord {
  name: string;
  status?: string;
  detail?: string;
}

export interface AgentPortReadback {
  id: string;
  target_node_id: string | null;
  source?: string;
  agent?: string;
  revision?: string | number;
  summary: string;
  commit_refs: string[];
  files: string[];
  tests: AgentPortRecord[];
  decisions: string[];
  risks: string[];
  todos: string[];
  evidence: AgentPortRecord[];
  created_at: string;
}

export interface AgentPortActivity {
  proposals: Record<string, unknown>[];
  events: Record<string, unknown>[];
  readbacks: AgentPortReadback[];
}

export function createApiClient() {
const revisionCache = {
  projects: new Map<string, number>(),
  nodes: new Map<string, { projectId: string; revision: number }>(),
  edges: new Map<string, { projectId: string; revision: number }>(),
  blocks: new Map<string, { nodeId: string; revision: number }>(),
  branches: new Map<string, { projectId: string; revision: number }>(),
};

function setProjectRevision(id: string, revision: number): void {
  const current = revisionCache.projects.get(id);
  if (current === undefined || revision > current) revisionCache.projects.set(id, revision);
}

function setEntityRevision<T extends { revision: number }>(cache: Map<string, T>, id: string, value: T): void {
  const current = cache.get(id);
  if (!current || value.revision > current.revision) cache.set(id, value);
}

function remember(value: unknown): void {
  if (Array.isArray(value)) { value.forEach(remember); return; }
  if (!value || typeof value !== "object") return;
  const row = value as Record<string, unknown>;
  const id = typeof row.id === "string" ? row.id : undefined;
  const revision = typeof row.revision === "number" ? row.revision : undefined;
  if (id && revision) {
    if (typeof row.authoritative_project_revision === "number" && typeof row.project_id === "string") {
      setProjectRevision(row.project_id, row.authoritative_project_revision);
    }
    if (typeof row.authoritative_parent_revision === "number" && typeof row.authoritative_parent_id === "string") {
      const cachedParent = revisionCache.nodes.get(row.authoritative_parent_id);
      if (cachedParent) setEntityRevision(revisionCache.nodes, row.authoritative_parent_id, { ...cachedParent, revision: row.authoritative_parent_revision });
    }
    if (typeof row.root_node_id === "string") setProjectRevision(id, revision);
    else if (typeof row.from_node_id === "string" && typeof row.project_id === "string") setEntityRevision(revisionCache.edges, id, { projectId: row.project_id, revision });
    else if (typeof row.node_id === "string" && typeof row.block_type === "string") setEntityRevision(revisionCache.blocks, id, { nodeId: row.node_id, revision });
    else if (typeof row.source_node_id === "string" && typeof row.project_id === "string") setEntityRevision(revisionCache.branches, id, { projectId: row.project_id, revision });
    else if (typeof row.project_id === "string" && typeof row.node_type === "string") setEntityRevision(revisionCache.nodes, id, { projectId: row.project_id, revision });
  }
  Object.values(row).forEach(remember);
}


async function request<T>(path: string, options?: RequestInit, rememberResponse = true, aiEnvelope = false): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    if (aiEnvelope) throw parseAIError(res.status, text);
    let detail: unknown = text;
    let code: string | undefined;
    let message = `API ${res.status}`;
    let requestId: string | undefined;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      detail = parsed.detail ?? parsed;
      if (detail && typeof detail === "object") {
        const row = detail as Record<string, unknown>;
        code = typeof row.code === "string" ? row.code : undefined;
        if (typeof row.message === "string") message = row.message;
        requestId = typeof row.request_id === "string" ? row.request_id : undefined;
      }
    } catch { /* retain plain-text response */ }
    throw new ApiError(res.status, code, message || `API ${res.status}`, detail, requestId);
  }
  if (res.status === 204) return undefined as T;
  const value = await res.json() as T;
  if (rememberResponse) remember(value);
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



  return {
  listAgentGrants: (projectId: string) => request<Record<string, unknown>[]>(`/agent-port/grants?project_id=${encodeURIComponent(projectId)}`),
  createAgentGrant: (data: Record<string, unknown>) => request<Record<string, unknown>>("/agent-port/grants", {method:"POST",body:JSON.stringify(data)}),
  revokeAgentGrant: (id: string) => request<Record<string, unknown>>(`/agent-port/grants/${id}/revoke`, {method:"POST"}),
  getAgentPortActivity: (projectId: string, targetNodeId?: string) => request<AgentPortActivity>(`/agent-port/activity?project_id=${encodeURIComponent(projectId)}${targetNodeId ? `&target_node_id=${encodeURIComponent(targetNodeId)}` : ""}`),
  reviewAgentProposal: (id:string, decision:"approve"|"reject", review_note="") => request<Record<string, unknown>>(`/agent-port/proposals/${id}/${decision}`, {method:"POST",body:JSON.stringify({review_note})}),
  // Server-side provider profiles. API keys remain in local environment variables.
  listProviders: () => request<ProviderConfig[]>("/providers"),
  getProvider: (providerId: string) => request<ProviderConfig>(`/providers/${providerId}`),
  setProviderSelection: (providerId: string | null, expectedSelectionRevision: number) => request<{provider_id:string|null;selection_revision:number;updated_at:string}>(`/providers/selection`, { method: "PUT", body:JSON.stringify({provider_id:providerId,expected_selection_revision:expectedSelectionRevision}) }),
  createProvider: (data: Omit<ProviderConfig, "id" | "auth_type" | "created_at" | "updated_at" | "revision" | "secret_change_pending" | "credential_status">) =>
    request<ProviderConfig>("/providers", { method: "POST", body: JSON.stringify(data) }),
  updateProvider: (providerId: string, data: Partial<Omit<ProviderConfig, "id" | "auth_type" | "created_at" | "updated_at" | "revision" | "secret_change_pending" | "credential_status">>) =>
    request<ProviderConfig>(`/providers/${providerId}`, { method: "PATCH", body: JSON.stringify(data) }),
  updateProviderModel: (providerId: string, modelName: string) =>
    request<ProviderConfig>(`/providers/${providerId}/model`, { method: "PATCH", body: JSON.stringify({model_name:modelName}) }),
  deleteProvider: (providerId: string) => request<void>(`/providers/${providerId}`, { method: "DELETE" }),
  writeProviderSecret: (providerId: string, apiKey: string) =>
    request<void>(`/providers/${providerId}/secret`, { method: "PUT", body: JSON.stringify({ api_key: apiKey }) }),
  recoverProviderSecret: (providerId:string, revision:number, operation:"set"|"delete", apiKey?:string) =>
    request<void>(`/providers/${providerId}/secret/recover`, {method:"POST",body:JSON.stringify({revision,operation,...(apiKey===undefined?{}:{api_key:apiKey})})}),
  recoverDesktopSecret: (providerId:string, revision:number, operation:"set"|"delete", apiKey?:string) =>
    request<void>(`/desktop/secrets/${providerId}/recover`, {method:"POST",body:JSON.stringify({revision,operation,...(apiKey===undefined?{}:{api_key:apiKey})})}),

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
  listProjects: (rememberResponse = true) => request<Project[]>("/projects", undefined, rememberResponse),
  getProject: (projectId: string, rememberResponse = true) => request<Project>(`/projects/${projectId}`, undefined, rememberResponse),
  rememberResponse: (value: unknown) => remember(value),
  createProject: (data: { name: string; description?: string; goal?: string }) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(data) }),
  updateProject: (projectId: string, data: Partial<Pick<Project, "status">> & { expected_project_revision?: number }) =>
    request<Project>(`/projects/${projectId}`, { method: "PATCH", body: JSON.stringify({ ...data, expected_project_revision: data.expected_project_revision ?? projectExpected(projectId) }) }),
  getEntitlement: () => request<Entitlement>("/desktop/entitlement", { cache: "no-store" }),

  // Nodes
  getSubtree: (nodeId: string, rememberResponse = true) => request<GNode>(`/nodes/${nodeId}/subtree`, undefined, rememberResponse),
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
    const node = revisionCache.nodes.get(data.from_node_id); if (!node) throw new Error("Node revision unavailable; refresh and retry");
    return request<Edge>(`/edges`, { method: "POST", body: JSON.stringify({ ...data, expected_project_revision: data.expected_project_revision ?? projectExpected(node.projectId) }) });
  },
  promoteMainline: (edgeId: string, expectedProjectRevision: number, expectedRevision: number) =>
    request<Edge>(`/edges/${edgeId}/promote-mainline`, { method: "POST", body: JSON.stringify({ expected_project_revision: expectedProjectRevision, expected_revision: expectedRevision }) }),
  promoteChildMainline: (parentId: string, childId: string, expectedProjectRevision: number, expectedRevision: number) =>
    request(`/nodes/${parentId}/promote-child/${childId}`, { method: "POST", body: JSON.stringify({ expected_project_revision: expectedProjectRevision, expected_revision: expectedRevision }) }),

  // Content blocks
  getBlocks: (nodeId: string) =>
    request<{ id: string; node_id: string; block_type: string; content: Record<string, string>; order_index: number; revision: number }[]>(`/nodes/${nodeId}/blocks`),
  createBlock: (nodeId: string, data: { expected_project_revision?: number; expected_node_revision?: number; block_type: string; content: Record<string, string> }) => {
    const node = nodeExpected(nodeId);
    return request(`/nodes/${nodeId}/blocks`, { method: "POST", body: JSON.stringify({ expected_project_revision: node.expected_project_revision, expected_node_revision: node.expected_revision, ...data }) });
  },
  updateBlock: (blockId: string, data: { expected_project_revision?: number; expected_node_revision?: number; expected_revision?: number; content?: Record<string, string>; block_type?: string; order_index?: number }) =>
    request(`/blocks/${blockId}`, { method: "PATCH", body: JSON.stringify({ ...blockExpected(blockId), ...data }) }),
  deleteBlock: (blockId: string, expectedProjectRevision?: number, expectedNodeRevision?: number, expectedRevision?: number) => {
    const expected = blockExpected(blockId);
    return request<void>(`/blocks/${blockId}`, { method: "DELETE", body: JSON.stringify({ ...expected, expected_project_revision: expectedProjectRevision ?? expected.expected_project_revision, expected_node_revision: expectedNodeRevision ?? expected.expected_node_revision, expected_revision: expectedRevision ?? expected.expected_revision }) });
  },

  // History
  getHistory: (nodeId: string) =>
    request<{ id: string; action_type: string; actor_type: string; payload: Record<string, unknown>; created_at: string }[]>(`/nodes/${nodeId}/history`),

  // AI operations
  expand: (nodeId: string, instruction: string | undefined, count: number | undefined, mode: GrowthMode, providerId: string, providerRevision: number, selectionRevision: number) =>
    request<{
      suggestions: { title: string; summary: string; node_type: string }[];
      context_used: Record<string, unknown>;
    }>("/ai/expand", {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId, instruction, count: count || 3, mode, provider_id: providerId, provider_revision: providerRevision, selection_revision: selectionRevision, locale: activeLocale() }),
    }, true, true),

  deepen: (nodeId: string, instruction: string | undefined, providerId: string, providerRevision: number, selectionRevision: number) =>
    request<{
      enriched_summary: string;
      content_blocks: { title: string; body: string; block_type: string }[];
      context_used: Record<string, unknown>;
    }>("/ai/deepen", {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId, instruction, provider_id: providerId, provider_revision: providerRevision, selection_revision: selectionRevision, locale: activeLocale() }),
    }, true, true),

  chat: (nodeId: string, message: string, history: { role: string; content: string }[], providerId: string, providerRevision: number, selectionRevision: number) =>
    request<{ reply: string; context_used: Record<string, unknown> }>("/ai/chat", {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId, message, history, provider_id: providerId, provider_revision: providerRevision, selection_revision: selectionRevision, locale: activeLocale() }),
    }, true, true),

  // Test LLM connection
  testConnection: (providerId: string, providerRevision: number, selectionRevision: number) =>
    request<{ ok: true; provider: string; model?: string; message: string; code: string; request_id: string; elapsed_ms: number }>("/ai/test-connection", {
      method: "POST",
      body: JSON.stringify({ provider_id: providerId, provider_revision: providerRevision, selection_revision: selectionRevision }),
    }, true, true),

  // Spec export (returns text)
  exportSpec: async (projectId: string): Promise<string> => {
    const res = await fetch(`${BASE}/projects/${projectId}/export-spec?locale=${encodeURIComponent(activeLocale())}`);
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
    return res.text();
  },

  // Branches
  listBranches: (projectId: string, includeInactive = false, rememberResponse = true) =>
    request<Branch[]>(`/projects/${projectId}/branches${includeInactive ? "?include_inactive=true" : ""}`, undefined, rememberResponse),
  createBranch: (projectId: string, data: { expected_project_revision: number; source_node_id: string; name: string; description?: string }) =>
    request<Branch>(`/projects/${projectId}/branches`, { method: "POST", body: JSON.stringify(data) }),
  getBranch: (branchId: string) =>
    request<Branch>(`/branches/${branchId}`),
  getBranchSubtree: (branchId: string, rememberResponse = true) =>
    request<{ branch: Branch; tree: GNode | null }>(`/branches/${branchId}/subtree`, undefined, rememberResponse),
  compareBranch: (branchId: string, rememberResponse = true) =>
    request<BranchComparison>(`/branches/${branchId}/compare`, undefined, rememberResponse),
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
}

export const api = createApiClient();
