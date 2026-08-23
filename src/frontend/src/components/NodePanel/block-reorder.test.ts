import assert from "node:assert/strict";
import test from "node:test";
import { reorderBlockAuthoritatively } from "./block-reorder";

const rows = [{ id: "a", order_index: 0 }, { id: "b", order_index: 1 }];

test("adjacent reorder sends exactly one PATCH then authoritative GET", async () => {
  const calls: string[] = [];
  const authoritative = [{ id: "b", order_index: 0 }, { id: "a", order_index: 1 }];
  const result = await reorderBlockAuthoritatively(
    rows, 0, 1,
    async (id, index) => { calls.push(`PATCH:${id}:${index}`); },
    async () => { calls.push("GET"); return authoritative; },
  );
  assert.deepEqual(calls, ["PATCH:a:1", "GET"]);
  assert.equal(result, authoritative);
});

test("failed PATCH never sends a second PATCH or GET; caller can reload coherently", async () => {
  const calls: string[] = [];
  await assert.rejects(() => reorderBlockAuthoritatively(
    rows, 0, 1,
    async (id, index) => { calls.push(`PATCH:${id}:${index}`); throw new Error("conflict"); },
    async () => { calls.push("GET"); return rows; },
  ), /conflict/);
  assert.deepEqual(calls, ["PATCH:a:1"]);
  // NodeContent's error path performs one authoritative reload, not another PATCH.
  calls.push("GET:error-reload");
  assert.deepEqual(calls, ["PATCH:a:1", "GET:error-reload"]);
});

test("boundary move is a local no-op with no request", async () => {
  let calls = 0;
  const result = await reorderBlockAuthoritatively(rows, 0, -1,
    async () => { calls += 1; }, async () => { calls += 1; return rows; });
  assert.equal(calls, 0);
  assert.equal(result, rows);
});
