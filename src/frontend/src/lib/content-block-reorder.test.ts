import test from "node:test";
import assert from "node:assert/strict";
import { ContentBlockReorderError, persistSequentialBlockReorder } from "./api";

test("first PATCH 200 then second 409 renders authoritative partial state and discloses it", async () => {
  const calls: string[] = [];
  const stale = [{ id: "a", order_index: 0 }, { id: "b", order_index: 1 }];
  const authoritative = [{ id: "a", order_index: 1 }, { id: "b", order_index: 1 }];
  let rendered = stale;

  await assert.rejects(
    persistSequentialBlockReorder({
      nodeId: "n",
      currentId: "a",
      currentOrder: 1,
      targetId: "b",
      targetOrder: 0,
      updateBlock: async (id, order) => {
        calls.push(`patch:${id}:${order}`);
        if (id === "b") throw new Error("409 conflict");
      },
      getBlocks: async (nodeId) => {
        calls.push(`get:${nodeId}`);
        return authoritative;
      },
      applyAuthoritativeBlocks: (rows) => { rendered = rows; },
    }),
    (error: unknown) => {
      assert.ok(error instanceof ContentBlockReorderError);
      assert.equal(error.partialSuccess, true);
      assert.match(error.message, /只完成部分/);
      return true;
    },
  );

  assert.deepEqual(calls, ["patch:a:1", "patch:b:0", "get:n"]);
  assert.equal(rendered, authoritative);
  assert.notEqual(rendered, stale);
});

test("first PATCH failure still refreshes authoritative state without claiming partial success", async () => {
  let rendered: { id: string; order_index: number }[] = [];
  await assert.rejects(
    persistSequentialBlockReorder({
      nodeId: "n",
      currentId: "a",
      currentOrder: 1,
      targetId: "b",
      targetOrder: 0,
      updateBlock: async () => { throw new Error("409 conflict"); },
      getBlocks: async () => [{ id: "a", order_index: 0 }, { id: "b", order_index: 1 }],
      applyAuthoritativeBlocks: (rows) => { rendered = rows; },
    }),
    (error: unknown) => error instanceof ContentBlockReorderError && !error.partialSuccess,
  );
  assert.deepEqual(rendered.map((row) => row.order_index), [0, 1]);
});
