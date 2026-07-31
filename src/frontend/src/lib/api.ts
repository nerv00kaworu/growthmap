// API client for GrowthMap backend
const BASE = typeof window !== "undefined" ? `${window.location.origin}/api` : "/api";

const revisionCache = {
  projects: new Map<string, number>(),
  nodes: new Map<string, { projectId: string; revision: number }>(),
  edges: new Map<string, { projectId: string; revision: number; fromNodeId: string; toNodeId: string; relationType: string; isMainline: boolean }>(),
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
    else if (typeof row.from_node_id === "string" && typeof row.project_id === "string")
      revisionCache.edges.set(id, { projectId: row.project_id, revision, fromNodeId: row.from_node_id,
        toNodeId: typeof row.to_node_id === "string" ? row.to_node_id : "",
        relationType: typeof row.relation_type === "string" ? row.relation_type : "",
        isMainline: row.is_mainline === true });
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

export class MalformedAuthoritativeResponseError extends Error {
  readonly code = "MALFORMED_AUTHORITATIVE_RESPONSE";
  constructor(public readonly operation: string) {
    super(`Malformed authoritative response for ${operation}`);
    this.name = "MalformedAuthoritativeResponseError";
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
  const isEdgePatch = options?.method === "PATCH" && path.startsWith("/edges/");
  if (!isEdgePatch && (!isBlockPatch || (typeof row?.authoritative_project_revision === "number" &&
      typeof row?.authoritative_node_revision === "number" &&
      typeof row?.authoritative_block_revision === "number"))) remember(value);
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

function applySuccessfulEdgeDelete(edgeId: string, projectId: string, expectedProjectRevision: number, expectedRevision: number): void {
  const edge = revisionCache.edges.get(edgeId);
  if (revisionCache.projects.get(projectId) === expectedProjectRevision &&
      edge?.projectId === projectId && edge.revision === expectedRevision) {
    revisionCache.projects.set(projectId, expectedProjectRevision + 1);
    revisionCache.edges.delete(edgeId);
    return;
  }
  revisionCache.projects.delete(projectId);
  revisionCache.edges.delete(edgeId);
}

type PromoteResult = { ok: boolean; project_id: string; edge_id: string; parent_node_id: string;
  child_node_id: string; project_revision: number; target_revision: number;
  touched_sibling_revisions: Record<string, number>; touched_node_revisions: Record<string, number> };

async function promoteMainlineRequest(path: string, edgeId: string): Promise<PromoteResult> {
  const target = revisionCache.edges.get(edgeId);
  if (!target || target.relationType !== "child_of") throw new Error("Target edge revision unavailable; refresh edges and retry");
  const siblingUnion = [...revisionCache.edges.entries()].filter(([, edge]) => edge.projectId === target.projectId &&
    edge.fromNodeId === target.fromNodeId && edge.relationType === "child_of");
  const demotedSiblings = siblingUnion.filter(([id, edge]) => id !== edgeId && edge.isMainline);
  const coupledEdges = [[edgeId, target] as const, ...demotedSiblings];
  const endpointIds = new Set(coupledEdges.flatMap(([, edge]) => [edge.fromNodeId, edge.toNodeId]));
  const invalidate = () => {
    revisionCache.projects.delete(target.projectId);
    coupledEdges.forEach(([id]) => revisionCache.edges.delete(id));
    endpointIds.forEach(id => revisionCache.nodes.delete(id));
  };
  const malformed = (): never => { invalidate(); throw new MalformedAuthoritativeResponseError("promote_mainline"); };
  const expectedNodes = new Map<string, number>();
  for (const id of endpointIds) {
    const node = revisionCache.nodes.get(id);
    if (!node || node.projectId !== target.projectId) malformed();
    expectedNodes.set(id, node!.revision);
  }
  let expectedProject: number;
  try { expectedProject = projectExpected(target.projectId); } catch { return malformed(); }
  const siblings = Object.fromEntries(demotedSiblings.map(([id, edge]) => [id, edge.revision]));
  const expectedEdges = new Map(coupledEdges.map(([id, edge]) => [id, edge.revision]));
  const value = await request<PromoteResult>(path, { method: "POST", body: JSON.stringify({
    expected_project_revision: expectedProject, expected_revision: target.revision,
    expected_sibling_revisions: siblings,
  }) });
  const snapshotUnchanged = revisionCache.projects.get(target.projectId) === expectedProject &&
    [...expectedEdges].every(([id, revision]) => revisionCache.edges.get(id)?.revision === revision) &&
    [...expectedNodes].every(([id, revision]) => {
      const node = revisionCache.nodes.get(id);
      return node?.projectId === target.projectId && node.revision === revision;
    });
  const expectedTouched = new Set(Object.keys(siblings));
  const responseTouched = value?.touched_sibling_revisions;
  const validTouched = responseTouched && Object.keys(responseTouched).length === expectedTouched.size &&
    Object.entries(responseTouched).every(([id, revision]) => expectedTouched.has(id) && revision === (expectedEdges.get(id) ?? 0) + 1);
  const responseNodes = value?.touched_node_revisions;
  const validNodes = responseNodes && Object.keys(responseNodes).length === endpointIds.size &&
    Object.entries(responseNodes).every(([id, revision]) => endpointIds.has(id) && revision === expectedNodes.get(id));
  const valid = value?.ok === true && value.project_id === target.projectId && value.edge_id === edgeId &&
    value.parent_node_id === target.fromNodeId && value.child_node_id === target.toNodeId &&
    value.project_revision === expectedProject + 1 && value.target_revision === target.revision + 1 && validTouched && validNodes;
  if (!valid || !snapshotUnchanged) malformed();
  revisionCache.projects.set(target.projectId, value.project_revision);
  coupledEdges.forEach(([id, edge]) => revisionCache.edges.set(id, { ...edge,
    revision: id === edgeId ? value.target_revision : responseTouched[id],
    isMainline: id === edgeId }));
  return value;
}

function applySuccessfulBlockDelete(blockId: string, nodeId: string, projectId: string, expected: {
  expected_project_revision: number; expected_node_revision: number; expected_revision: number;
}): void {
  const projectRevision = revisionCache.projects.get(projectId);
  const node = revisionCache.nodes.get(nodeId);
  const block = revisionCache.blocks.get(blockId);
  if (projectRevision === expected.expected_project_revision &&
      node?.projectId === projectId && node.revision === expected.expected_node_revision &&
      block?.nodeId === nodeId && block.revision === expected.expected_revision) {
    revisionCache.projects.set(projectId, expected.expected_project_revision + 1);
    revisionCache.nodes.set(nodeId, { projectId, revision: expected.expected_node_revision + 1 });
    revisionCache.blocks.delete(blockId);
    return;
  }
  // A concurrent read/write changed the snapshot while DELETE was in flight.
  // Invalidate the coupled entries instead of overwriting newer truth.
  revisionCache.projects.delete(projectId);
  revisionCache.nodes.delete(nodeId);
  revisionCache.blocks.delete(blockId);
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
  updateEdge: async (edgeId: string, data: { expected_project_revision?: number; expected_revision?: number; weight?: number; note?: string }) => {
    const edge = revisionCache.edges.get(edgeId); if (!edge) throw new Error("Edge revision unavailable; refresh and retry");
    const expectedProject = projectExpected(edge.projectId);
    const fields: { weight?: number; note?: string } = {};
    if (data.weight !== undefined) fields.weight = data.weight;
    if (data.note !== undefined) fields.note = data.note;
    const value = await request<Edge>(`/edges/${edgeId}`, { method: "PATCH", body: JSON.stringify({
      ...fields, expected_project_revision: expectedProject, expected_revision: edge.revision,
    }) });
    const projectRevision = value.authoritative_project_revision;
    const edgeRevision = value.authoritative_edge_revision;
    const currentEdge = revisionCache.edges.get(edgeId);
    const snapshotUnchanged = revisionCache.projects.get(edge.projectId) === expectedProject &&
      currentEdge?.projectId === edge.projectId && currentEdge.revision === edge.revision;
    const valid = projectRevision === expectedProject + 1 && edgeRevision === edge.revision + 1 &&
      value.id === edgeId && value.project_id === edge.projectId && value.revision === edgeRevision;
    if (!valid) {
      if (!snapshotUnchanged) {
        revisionCache.projects.delete(edge.projectId); revisionCache.edges.delete(edgeId);
      }
      throw new MalformedAuthoritativeResponseError("update_edge");
    }
    if (snapshotUnchanged) {
      revisionCache.projects.set(edge.projectId, projectRevision);
      revisionCache.edges.set(edgeId, { ...edge, revision: edgeRevision });
    } else {
      revisionCache.projects.delete(edge.projectId); revisionCache.edges.delete(edgeId);
    }
    return value;
  },
  deleteEdge: async (edgeId: string, expectedProjectRevision?: number, expectedRevision?: number) => {
    const edge = revisionCache.edges.get(edgeId); if (!edge) throw new Error("Edge revision unavailable; refresh and retry");
    const projectRevision = expectedProjectRevision ?? projectExpected(edge.projectId);
    const edgeRevision = expectedRevision ?? edge.revision;
    await request<void>(`/edges/${edgeId}`, { method: "DELETE", body: JSON.stringify({ expected_project_revision: projectRevision, expected_revision: edgeRevision }) });
    applySuccessfulEdgeDelete(edgeId, edge.projectId, projectRevision, edgeRevision);
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
  promoteMainline: (edgeId: string) => promoteMainlineRequest(`/edges/${edgeId}/promote-mainline`, edgeId),
  promoteChildMainline: (parentId: string, childId: string) => {
    const edgeId = [...revisionCache.edges.entries()].find(([, edge]) => edge.fromNodeId === parentId &&
      edge.toNodeId === childId && edge.relationType === "child_of")?.[0];
    if (!edgeId) throw new Error("Complete child edge revision union unavailable; refresh edges and retry");
    return promoteMainlineRequest(`/nodes/${parentId}/promote-child/${childId}`, edgeId);
  },

  // Content blocks
  getBlocks: (nodeId: string) =>
    request<{ id: string; node_id: string; block_type: string; content: Record<string, string>; order_index: number; revision: number }[]>(`/nodes/${nodeId}/blocks`),
  createBlock: (nodeId: string, data: { block_type: string; content: Record<string, string>; order_index?: number }) => {
    const node = nodeExpected(nodeId);
    return request<{ id: string; node_id: string; block_type: string; content: Record<string, string>; order_index: number; revision: number; authoritative_project_revision?: number; authoritative_node_revision?: number; authoritative_block_revision?: number }>(`/nodes/${nodeId}/blocks`, { method: "POST", body: JSON.stringify({ ...data, expected_project_revision: node.expected_project_revision, expected_node_revision: node.expected_revision }) });
  },
  updateBlock: (blockId: string, data: { content?: unknown; block_type?: string; order_index?: number }) =>
    request(`/blocks/${blockId}`, { method: "PATCH", body: JSON.stringify({ ...data, ...blockExpected(blockId) }) }),
  deleteBlock: async (blockId: string, expectedProjectRevision?: number, expectedNodeRevision?: number, expectedRevision?: number) => {
    const cachedBlock = revisionCache.blocks.get(blockId);
    if (!cachedBlock) throw new Error("Block revision unavailable; refresh and retry");
    const cachedNode = revisionCache.nodes.get(cachedBlock.nodeId);
    if (!cachedNode) throw new Error("Node revision unavailable; refresh and retry");
    const cached = blockExpected(blockId);
    const expected = {
      expected_project_revision: expectedProjectRevision ?? cached.expected_project_revision,
      expected_node_revision: expectedNodeRevision ?? cached.expected_node_revision,
      expected_revision: expectedRevision ?? cached.expected_revision,
    };
    await request<void>(`/blocks/${blockId}`, { method: "DELETE", body: JSON.stringify(expected) });
    applySuccessfulBlockDelete(blockId, cachedBlock.nodeId, cachedNode.projectId, expected);
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


