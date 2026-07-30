'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(process.env.GROWTHMAP_PREFLIGHT_ROOT || path.resolve(__dirname, '..', '..'));
const next = path.join(root, 'src', 'frontend', '.next');
const contractPath = path.join(next, 'growthmap-client-reference-boundary.json');
const contract = JSON.parse(fs.readFileSync(contractPath, 'utf8'));
assert.equal(contract.version, 1);
assert.equal(contract.compiler, 'client');
assert.ok(Array.isArray(contract.files) && contract.files.length > 0, 'client manifest boundary did not record an emitted artifact');
for (const record of contract.files) {
  assert.match(record.asset, /^server\/app\/.+_client-reference-manifest\.js$/);
  const absolute = path.join(next, ...record.asset.split('/'));
  const source = fs.readFileSync(absolute, 'utf8');
  assert.equal(crypto.createHash('sha256').update(source).digest('hex'), record.sha256, `export manifest changed after the durable boundary: ${record.asset}`);
}
const html = fs.readFileSync(path.join(root, 'src', 'frontend', 'out', 'index.html'), 'utf8');
const manifest = fs.readFileSync(path.join(next, 'server', 'app', 'page_client-reference-manifest.js'), 'utf8');
const marker = ']=', offset = manifest.indexOf(marker);
assert.ok(offset >= 0);
const value = JSON.parse(manifest.slice(offset + marker.length));
const nonEmptyChunks = [...new Set(Object.values(value.clientModules).map((entry) => JSON.stringify(entry.chunks)).filter((chunks) => chunks !== '[]'))];
assert.ok(nonEmptyChunks.length > 0, 'page manifest has no non-empty client chunks');
const embedded = nonEmptyChunks.filter((chunks) => html.includes(chunks) || html.includes(chunks.replaceAll('"', '\\"')));
assert.ok(embedded.length > 0, 'static export did not embed any chunk tuple from its page client-reference manifest');
// The page need not render every client reference in the merged route manifest,
// but every matching tuple is byte-for-byte evidence that export consumed this
// normalized durable artifact rather than a helper-only representation.
console.log(`Verified static export embedded ${embedded.length} tuple(s) from ${contract.files.length} normalized client-reference manifest artifact(s).`);
