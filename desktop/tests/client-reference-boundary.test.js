'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const { normalizeChunkPairs, verifyBoundary } = require('../scripts/verify-client-reference-boundary');

const id = 'c546470e5ca77f8d';
const chunks = [
  '1a258343', 'static/chunks/1a258343.js',
  '', 'static/chunks/app/page.js',
  'vendors', 'static/chunks/vendors.js',
];
function manifest(value) {
  return `globalThis.__RSC_MANIFEST=(globalThis.__RSC_MANIFEST||{});globalThis.__RSC_MANIFEST["/page"]=${JSON.stringify({ clientModules: { page: { id, name: '*', chunks: value, async: false } } })}`;
}
function html(value) {
  const flight = `5:I[${JSON.stringify(id)},${JSON.stringify(value)},"default"]\n`;
  const scripts = Array.from({ length: 9 }, () => '<script></script>').join('');
  return `${scripts}<script>self.__next_f.push(${JSON.stringify([1, flight])})</script>`;
}

test('strong contract requires the complete normalized chunk array', () => {
  assert.deepEqual(normalizeChunkPairs([
    'vendors', 'static/chunks/vendors.js',
    '', 'static/chunks/app/page.js',
    '1a258343', 'static/chunks/1a258343.js',
  ]), chunks);
  assert.deepEqual(verifyBoundary({ html: html(chunks), manifestSource: manifest(chunks), moduleId: id }), chunks);
});

test('strong contract rejects stale serialization even when one tuple matches', () => {
  const stale = [chunks[0], chunks[1], chunks[4], chunks[5], chunks[2], chunks[3]];
  assert.throws(
    () => verifyBoundary({ html: html(stale), manifestSource: manifest(chunks), moduleId: id }),
    /stale or non-normalized chunks/,
  );
});
