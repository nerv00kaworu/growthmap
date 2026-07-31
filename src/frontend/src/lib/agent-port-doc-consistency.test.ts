import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("content-block update/delete capabilities and shared/deferred documentation agree", async () => {
  const [capabilities, docs] = await Promise.all([
    readFile(new URL("../../../backend/agent_port/routes.py", import.meta.url), "utf8"),
    readFile(new URL("../../../../docs/AGENT-PORT-v1.md", import.meta.url), "utf8"),
  ]);
  assert.match(capabilities, /"operations":\[[^\]]*"update_content_block"[^\]]*"delete_content_block"/);
  assert.match(docs, /`update_content_block`/);
  assert.match(docs, /`delete_content_block`/);
  assert.match(docs, /update-content-block, and delete-content-block are shared/);
  assert.doesNotMatch(docs, /update\/delete edge\/block/);
  assert.match(docs, /`update_edge`, `delete_edge`/);
});
