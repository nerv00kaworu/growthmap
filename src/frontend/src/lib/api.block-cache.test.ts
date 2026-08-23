import assert from "node:assert/strict";
import test from "node:test";
import { createApiClient } from "./api";

const jsonResponse = (value: unknown) => ({ ok: true, status: 200, json: async () => value }) as Response;
const project = (revision: number) => ({ id: "p", root_node_id: "n", revision });
const node = (revision: number) => ({ id: "n", project_id: "p", node_type: "concept", revision });
const block = (revision: number) => ({ id: "b", node_id: "n", block_type: "note", order_index: 0, revision });

test("failed coherent owner readback invalidation blocks the next stale PATCH", async () => {
  const api = createApiClient();
  api.rememberResponse([project(1), node(1), block(1)]);
  let fetches = 0;
  globalThis.fetch = (async () => { fetches++; return jsonResponse(block(2)); }) as typeof fetch;
  await api.updateBlock("b", { order_index: 0 });
  assert.equal(fetches, 1);
  api.invalidateBlockOwner("n");
  assert.throws(() => api.updateBlock("b", { order_index: 0 }), /Block revision unavailable/);
  assert.equal(fetches, 1, "no stale owner CAS request may leave the client");
});

test("coherent publish makes the next PATCH use latest project/node/block revisions", async () => {
  const api = createApiClient();
  api.rememberResponse([project(1), node(1), block(1)]);
  const bodies: unknown[] = [];
  globalThis.fetch = (async (_url, init) => {
    bodies.push(JSON.parse(String(init?.body)));
    return jsonResponse(block(bodies.length + 1));
  }) as typeof fetch;
  await api.updateBlock("b", { order_index: 0 });
  api.rememberResponse([project(2), node(2), block(2)]);
  await api.updateBlock("b", { order_index: 0 });
  assert.deepEqual(bodies[1], { expected_project_revision: 2, expected_node_revision: 2, expected_revision: 2, order_index: 0 });
});
