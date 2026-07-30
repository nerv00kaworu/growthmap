'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { patchNext, PATCHED } = require('./patch-next-flight-manifest');

test('pinned patch sorts complete pairs by emitted file and keeps an empty id attached', () => {
  const body = PATCHED.slice(0, PATCHED.indexOf('\n}\n//')).replace('    return pairs.flat();', '    result = pairs.flat();');
  const context = { chunks: [
    'vendors', 'static/chunks/vendors.js',
    '', 'static/chunks/app/page.js',
    '1a258343', 'static/chunks/1a258343.js',
  ], result: null };
  vm.runInNewContext(`{\n${body}\n}`, context);
  assert.deepEqual([...context.result], [
    '1a258343', 'static/chunks/1a258343.js',
    '', 'static/chunks/app/page.js',
    'vendors', 'static/chunks/vendors.js',
  ]);
});

test('pinned patch fails closed before touching an unexpected Next version', (t) => {
  const frontend = fs.mkdtempSync(path.join(os.tmpdir(), 'growthmap-next-patch-'));
  t.after(() => fs.rmSync(frontend, { recursive: true, force: true }));
  fs.mkdirSync(path.join(frontend, 'scripts'));
  fs.writeFileSync(path.join(frontend, 'package-lock.json'), JSON.stringify({
    packages: { 'node_modules/next': { version: '15.5.22', integrity: 'unexpected' } },
  }));
  assert.throws(() => patchNext(path.join(frontend, 'scripts')), /unpinned Next version/);
});
