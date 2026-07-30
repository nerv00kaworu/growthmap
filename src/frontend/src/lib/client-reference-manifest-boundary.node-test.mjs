import assert from "node:assert/strict";
import test from "node:test";
import { normalizeChunkPairs, normalizeClientReferenceManifest } from "./client-reference-manifest-boundary.mjs";

test("normalizes complete chunk id/file pairs with ordinal ordering", () => {
  const vendors = ["vendors-z", "static/chunks/vendors-z.js"];
  const shared = ["1a258343", "static/chunks/1a258343.js"];
  const page = ["app/page", "static/chunks/app/page.js"];
  assert.deepEqual(normalizeChunkPairs([...vendors, ...shared, ...page]), normalizeChunkPairs([...shared, ...vendors, ...page]));
  assert.throws(() => normalizeChunkPairs(["orphan"]), /id\/file pairs/);
});

test("normalizes the emitted Next assignment without changing pair membership", () => {
  const wrap = (chunks) => `globalThis.__RSC_MANIFEST=(globalThis.__RSC_MANIFEST||{});globalThis.__RSC_MANIFEST["/page"]=${JSON.stringify({ clientModules: { x: { id: "x", chunks } } })}`;
  const left = wrap(["z", "z.js", "a", "a.js"]);
  const right = wrap(["a", "a.js", "z", "z.js"]);
  assert.equal(normalizeClientReferenceManifest(left), normalizeClientReferenceManifest(right));
});
