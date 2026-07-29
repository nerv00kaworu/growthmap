'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { hash } = require('../scripts/csp-manifest');
const { DiagnosticError, balancedTuples, compare, containsPrivatePath, emit, main } = require('../scripts/diagnose-csp-manifest');

function manifest(files) { return { version: 1, algorithm: 'sha256', files, hashes: [...new Set(Object.values(files).flat())].sort() }; }
function fixture(script = 'self.__next_f.push([1,"7:I[123,[\\"45\\",\\"static/chunks/app/page.js\\"],\\"default\\"]\\n"])') {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'csp-diagnostic-'));
  const out = path.join(root, 'out'); fs.mkdirSync(out);
  fs.writeFileSync(path.join(out, 'index.html'), `<script src="a.js"></script><script>${script}</script>`);
  return { root, out, script };
}

test('extracts only the added inline script and parses RSC I tuples', () => {
  const f = fixture();
  const records = compare(manifest({ 'index.html': [hash('old')] }), manifest({ 'index.html': [hash(f.script)] }), f.out);
  assert.deepEqual(records, [{ file: 'index.html', scriptIndex: 1, sha256: hash(f.script), bytes: Buffer.byteLength(f.script), chars: f.script.length, removed: [hash('old')], rscI: [['123', '["45","static/chunks/app/page.js"]', 'default']] }]);
});

test('parses direct RSC tuples', () => assert.deepEqual(balancedTuples('7:I[321,["9","chunk.js"],"*"]'), [['321', '["9","chunk.js"]', '*']]));

test('detects raw, slash, backslash, file URI, and encoded private paths', () => {
  for (const value of ['/home/runner/work/repo', '\\Users\\runneradmin\\work\\repo', 'C:/Users/runneradmin/work/repo', 'file:///C:/Users/runner/work/repo', 'C%3A%5CUsers%5Crunner%5Cwork', '%252Fhome%252Frunner%252Fwork']) assert.equal(containsPrivatePath(value), true, value);
  assert.equal(containsPrivatePath('static/chunks/app/page.js'), false);
});

test('is quiet when manifests are unchanged', () => {
  const f = fixture('safe'); const m = manifest({ 'index.html': [hash('safe')] });
  assert.deepEqual(compare(m, m, f.out), []);
  const lines = []; emit([], (line) => lines.push(line)); assert.deepEqual(lines, []);
});

test('bounds tuple fields and emitted lines', () => {
  const tuples = balancedTuples(`I["${'x'.repeat(500)}"]`);
  assert.ok(tuples[0][0].length <= 160); assert.match(tuples[0][0], /truncated/);
  const lines = []; emit([{ file: 'index.html', scriptIndex: 1, sha256: hash('x'), bytes: 1, chars: 1, removed: [], rscI: tuples }], (line) => lines.push(line));
  assert.ok(lines.every((line) => line.length <= 2048));
});

test('fails closed for private paths, malformed manifests and unmatched hashes', () => {
  const unsafe = fixture('self.__next_f.push([1,"I[\\"C:/Users/runner/secret\\"]"])');
  assert.throws(() => compare(manifest({ 'index.html': [] }), manifest({ 'index.html': [hash(unsafe.script)] }), unsafe.out), DiagnosticError);
  assert.throws(() => balancedTuples('I["unterminated"'), DiagnosticError);
  assert.throws(() => compare(manifest({ 'index.html': [] }), manifest({ 'index.html': [hash('missing')] }), unsafe.out), DiagnosticError);
});

test('CLI returns diagnostics for files and rejects malformed generated input', () => {
  const f = fixture(); const tracked = path.join(f.root, 'tracked.json'); const generated = path.join(f.root, 'generated.json');
  fs.writeFileSync(tracked, JSON.stringify(manifest({ 'index.html': [hash('old')] })));
  fs.writeFileSync(generated, JSON.stringify(manifest({ 'index.html': [hash(f.script)] })));
  const lines = []; assert.equal(main(['--tracked', tracked, '--generated', generated, '--out', f.out], (line) => lines.push(line)), 1); assert.equal(lines.length, 2);
  fs.writeFileSync(generated, '{'); assert.throws(() => main(['--tracked', tracked, '--generated', generated, '--out', f.out], () => {}), DiagnosticError);
});
