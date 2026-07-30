import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { api, resetRevisionCacheForTests } from "./api";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
const project = (revision: number) => ({ id: "block-p", revision, root_node_id: "owner" });
const node = (revision: number) => ({ id: "owner", project_id: "block-p", revision, node_type: "idea" });

test("createBlock sends owner/project CAS and consumes only authoritative revisions", async () => {
  resetRevisionCacheForTests(); const bodies: Record<string, unknown>[] = []; let writes = 0;
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    if (url.endsWith("/projects")) return json([project(7)]);
    if (url.endsWith("/nodes/owner")) return json(node(3));
    bodies.push(JSON.parse(String(init?.body))); writes++;
    if (writes === 1) return json({ id: "b1", node_id: "owner", block_type: "paragraph", content: { body: "x" }, order_index: 0, revision: 1, authoritative_project_revision: 8, authoritative_node_revision: 4, authoritative_block_revision: 1 }, 201);
    return json({ id: `b${writes}`, node_id: "owner", block_type: "paragraph", content: { body: "x" }, order_index: 0, revision: 1 }, 201);
  };
  await api.listProjects(); await api.getNode("owner");
  await api.createBlock("owner", { block_type: "paragraph", content: { body: "x" } });
  await api.createBlock("owner", { block_type: "paragraph", content: { body: "x" } });
  await api.createBlock("owner", { block_type: "paragraph", content: { body: "x" } });
  assert.deepEqual(bodies.map(x => [x.expected_project_revision, x.expected_node_revision]), [[7,3],[8,4],[8,4]]);
});

test("createBlock 409 never pollutes revision cache", async () => {
  resetRevisionCacheForTests(); const bodies: Record<string, unknown>[] = [];
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    if (url.endsWith("/projects")) return json([project(9)]);
    if (url.endsWith("/nodes/owner")) return json(node(6));
    bodies.push(JSON.parse(String(init?.body)));
    if (bodies.length === 1) return json({ detail: { code: "REVISION_CONFLICT", message: "stale" } }, 409);
    return json({ id: "b2", node_id: "owner", block_type: "paragraph", content: {}, order_index: 0, revision: 1 }, 201);
  };
  await api.listProjects(); await api.getNode("owner");
  await assert.rejects(api.createBlock("owner", { block_type: "paragraph", content: {} }), /stale/);
  await api.createBlock("owner", { block_type: "paragraph", content: {} });
  assert.deepEqual(bodies.map(x => [x.expected_project_revision, x.expected_node_revision]), [[9,6],[9,6]]);
});

test("consumer create paths rely on api-owned CAS and document fields remain canonical", async () => {
  const fs = await import("node:fs");
  const content = fs.readFileSync(new URL("../components/NodePanel/NodeContent.tsx", import.meta.url), "utf8");
  const store = fs.readFileSync(new URL("../stores/useStore.ts", import.meta.url), "utf8");
  assert.match(content, /handleAddDoc[\s\S]*api\.createBlock\(selectedNode\.id,[\s\S]*block_type: "resource"[\s\S]*title:[\s\S]*url:[\s\S]*summary:/);
  assert.match(content, /handleCreateBlock[\s\S]*api\.createBlock\(selectedNode\.id,[\s\S]*block_type: newBlockType/);
  const deepen = store.slice(store.indexOf("acceptDeepenBlock: async"), store.indexOf("ignoreDeepenBlock: async"));
  assert.match(deepen, /api\.createBlock\(targetId/);
  assert.doesNotMatch(deepen, /expected_(project|node)_revision/);
});
