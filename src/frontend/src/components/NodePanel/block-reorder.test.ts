import assert from "node:assert/strict";
import test from "node:test";
import { reorderBlockAuthoritatively } from "./block-reorder";

const rows = [{ id: "a", order_index: 0 }, { id: "b", order_index: 1 }];
const owner = { project: { id: "p", revision: 2 }, node: { id: "n", revision: 2 }, blocks: [{ id: "b", order_index: 0 }, { id: "a", order_index: 1 }] };

test("adjacent reorder sends one PATCH, reads complete owner, then publishes once", async () => {
  const calls: string[] = [];
  const result = await reorderBlockAuthoritatively(rows, 0, 1,
    async (id, index) => { calls.push(`PATCH:${id}:${index}`); },
    async () => { calls.push("GET:owner"); return owner; },
    value => { calls.push("PUBLISH"); assert.equal(value, owner); },
    () => calls.push("INVALIDATE"));
  assert.deepEqual(calls, ["PATCH:a:1", "GET:owner", "PUBLISH"]);
  assert.deepEqual(result, { moved: true, blocks: owner.blocks });
});

test("committed PATCH plus partial readback failure invalidates and never retries PATCH", async () => {
  const calls: string[] = [];
  await assert.rejects(() => reorderBlockAuthoritatively(rows, 0, 1,
    async (id, index) => { calls.push(`PATCH:${id}:${index}`); },
    async () => { calls.push("GET:owner"); throw new Error("node unavailable"); },
    () => calls.push("PUBLISH"), () => calls.push("INVALIDATE")),
  /CONTENT_REORDER_SAVED_REFRESH_FAILED/);
  assert.deepEqual(calls, ["PATCH:a:1", "GET:owner", "INVALIDATE"]);
});

test("failed PATCH neither reads nor publishes nor invalidates", async () => {
  const calls: string[] = [];
  await assert.rejects(() => reorderBlockAuthoritatively(rows, 0, 1,
    async () => { calls.push("PATCH"); throw new Error("conflict"); },
    async () => { calls.push("GET"); return owner; },
    () => calls.push("PUBLISH"), () => calls.push("INVALIDATE")), /conflict/);
  assert.deepEqual(calls, ["PATCH"]);
});
