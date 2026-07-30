'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const TARGET_MODULE_ID = 'c546470e5ca77f8d';

function compareTotal(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
function normalizeChunkPairs(chunks) {
  assert.ok(Array.isArray(chunks) && chunks.length % 2 === 0, 'chunks must be complete id/file pairs');
  const pairs = [];
  for (let index = 0; index < chunks.length; index += 2) {
    assert.equal(typeof chunks[index], 'string');
    assert.equal(typeof chunks[index + 1], 'string');
    pairs.push([chunks[index], chunks[index + 1]]);
  }
  // File-first ordering is deliberate: an empty webpack chunk id is valid, while
  // its emitted app/page file remains a stable and meaningful ordering key.
  pairs.sort((a, b) => compareTotal(a[1], b[1]) || compareTotal(a[0], b[0]));
  return pairs.flat();
}

function parsePageManifest(source) {
  const context = {};
  vm.runInNewContext(source, context, { timeout: 1000 });
  const manifest = context.__RSC_MANIFEST?.['/page'];
  assert.ok(manifest, 'page client-reference manifest assignment is missing');
  return manifest;
}

function parseFlightImports(html) {
  const imports = [];
  const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
  assert.ok(scripts.length > 9, 'static export has no script #9');
  const pushes = [];
  const self = { __next_f: { push(value) { pushes.push(value); } } };
  vm.runInNewContext(scripts[9][1], { self }, { timeout: 1000 });
  for (const value of pushes) {
    if (!Array.isArray(value) || typeof value[1] !== 'string') continue;
    for (const line of value[1].split('\n')) {
      const match = line.match(/^[^:]+:I\[(.*)]$/);
      if (!match) continue;
      const tuple = JSON.parse(`[${match[1]}]`);
      imports.push({ id: tuple[0], chunks: tuple[1], exportName: tuple[2] });
    }
  }
  return imports;
}

function verifyBoundary({ html, manifestSource, moduleId = TARGET_MODULE_ID }) {
  const manifest = parsePageManifest(manifestSource);
  const entries = Object.values(manifest.clientModules).filter((entry) => entry.id === moduleId);
  assert.equal(entries.length, 1, `expected one page manifest entry for module ${moduleId}`);
  const flight = parseFlightImports(html).filter((entry) => entry.id === moduleId && entry.exportName === 'default');
  assert.equal(flight.length, 1, `expected one script #9 default import for module ${moduleId}`);
  const expected = normalizeChunkPairs(entries[0].chunks);
  assert.deepEqual(flight[0].chunks, expected, `script #9 serialized stale or non-normalized chunks for module ${moduleId}`);
  return expected;
}

function main() {
  const root = path.resolve(process.env.GROWTHMAP_PREFLIGHT_ROOT || path.resolve(__dirname, '..', '..'));
  const frontend = path.join(root, 'src', 'frontend');
  const chunks = verifyBoundary({
    html: fs.readFileSync(path.join(frontend, 'out', 'index.html'), 'utf8'),
    manifestSource: fs.readFileSync(path.join(frontend, '.next', 'server', 'app', 'page_client-reference-manifest.js'), 'utf8'),
  });
  console.log(`Verified script #9 default import exactly matches all ${chunks.length / 2} normalized page-manifest chunk pair(s).`);
}

if (require.main === module) main();
module.exports = { normalizeChunkPairs, parseFlightImports, parsePageManifest, verifyBoundary };
