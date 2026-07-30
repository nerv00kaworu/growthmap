'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { scanPublicBundle, stableModuleIds, stageAppPageChunk } = require('../scripts/stage-app-page-chunk-diagnostic');

test('extracts only allowlisted stable module IDs in rendered order', () => {
  assert.deepEqual(stableModuleIds('x.push({c546470e5ca77f8d:1,"not-an-id":2,35a84c1952d2be21:3})'), [
    'c546470e5ca77f8d', '35a84c1952d2be21',
  ]);
});

test('scanner fails closed on paths, credentials, and source map disclosures', () => {
  for (const value of [
    '/home/runner/work/private/file.js', 'C:\\Users\\runner\\private.js',
    'github_pat_abcdefghijklmnopqrstuvwxyz', 'sk-proj-abcdefghijklmnopqrstuvwxyz',
    '//# sourceMappingURL=file.js.map',
  ]) assert.throws(() => scanPublicBundle(value), /diagnostic refused/);
});

test('stages exactly one scanned app/page public bundle with bounded metadata', (context) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'growthmap-app-page-diagnostic-'));
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const next = path.join(root, '.next'), chunks = path.join(next, 'static', 'chunks', 'app');
  const out = path.join(root, 'artifact');
  fs.mkdirSync(chunks, { recursive: true });
  const source = 'self.webpackChunk_N_E.push([["app/page"],{c546470e5ca77f8d:()=>{}}]);';
  fs.writeFileSync(path.join(chunks, 'page-a82e37eee192a225.js'), source);
  const metadata = stageAppPageChunk(next, out);
  assert.equal(metadata.size, Buffer.byteLength(source));
  assert.equal(metadata.stableModuleIds.count, 1);
  assert.deepEqual(fs.readdirSync(out).sort(), ['metadata.json', 'page-a82e37eee192a225.js']);
  assert.equal(fs.readFileSync(path.join(out, 'page-a82e37eee192a225.js'), 'utf8'), source);
});

test('refuses ambiguous chunk selection before staging anything', (context) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'growthmap-app-page-diagnostic-'));
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const chunks = path.join(root, '.next', 'static', 'chunks', 'app');
  fs.mkdirSync(chunks, { recursive: true });
  fs.writeFileSync(path.join(chunks, 'page-a.js'), 'a');
  fs.writeFileSync(path.join(chunks, 'page-b.js'), 'b');
  assert.throws(() => stageAppPageChunk(path.join(root, '.next'), path.join(root, 'out')), /exactly one/);
});
