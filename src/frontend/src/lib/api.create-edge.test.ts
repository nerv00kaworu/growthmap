import test from "node:test";
import assert from "node:assert/strict";
import { api } from "./api";

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "content-type": "application/json" },
});
const project = (id: string, revision: number) => ({ id, revision, root_node_id: `${id}-root` });
const node = (id: string, project_id: string, revision: number) => ({ id, project_id, revision, node_type: "idea" });

test("createEdge sends both endpoint CAS and consumes authoritative revisions", async () => {
  const calls: Array<{ url: string; body?: Record<string, unknown> }> = [];
  globalThis.fetch = async (input, init) => {
    const url = String(input); const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, body });
    if (url.endsWith("/projects")) return json([project("edge-p1", 7)]);
    if (url.endsWith("/nodes/edge-a")) return json(node("edge-a", "edge-p1", 3));
    if (url.endsWith("/nodes/edge-b")) return json(node("edge-b", "edge-p1", 5));
    if (url.endsWith("/edges")) return json({ id: "edge-1", project_id: "edge-p1", from_node_id: "edge-a", to_node_id: "edge-b", relation_type: "supports", weight: 1, note: "", is_mainline: false, created_at: "2026-01-01", revision: 1, authoritative_project_revision: 8, authoritative_from_revision: 4, authoritative_to_revision: 6 }, 201);
    throw new Error(url);
  };
  await api.listProjects(); await api.getNode("edge-a"); await api.getNode("edge-b");
  await api.createEdge({ from_node_id: "edge-a", to_node_id: "edge-b", relation_type: "supports" });
  const create = calls.at(-1)!.body!;
  assert.deepEqual({ project: create.expected_project_revision, from: create.expected_from_revision, to: create.expected_to_revision }, { project: 7, from: 3, to: 5 });
  await api.createEdge({ from_node_id: "edge-a", to_node_id: "edge-b", relation_type: "references" });
  const next = calls.at(-1)!.body!;
  assert.deepEqual({ project: next.expected_project_revision, from: next.expected_from_revision, to: next.expected_to_revision }, { project: 8, from: 4, to: 6 });
});

test("createEdge fails closed for missing endpoint cache and cross-project endpoints", async () => {
  let writes = 0;
  globalThis.fetch = async (input) => {
    const url = String(input);
    if (url.endsWith("/projects")) return json([project("edge-p2", 1), project("edge-p3", 1)]);
    if (url.endsWith("/nodes/edge-c")) return json(node("edge-c", "edge-p2", 1));
    if (url.endsWith("/nodes/edge-d")) return json(node("edge-d", "edge-p3", 1));
    writes++; return json({});
  };
  await api.listProjects(); await api.getNode("edge-c");
  assert.throws(() => api.createEdge({ from_node_id: "edge-c", to_node_id: "uncached" }), /Endpoint revision unavailable/);
  await api.getNode("edge-d");
  assert.throws(() => api.createEdge({ from_node_id: "edge-c", to_node_id: "edge-d" }), /same project/);
  assert.equal(writes, 0);
});
