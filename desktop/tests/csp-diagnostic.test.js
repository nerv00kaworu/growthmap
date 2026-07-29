'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { hash } = require('../scripts/csp-manifest');
const { DiagnosticError, balancedTuples, compare, containsPrivatePath, emit, main, strictArrayMetadata } = require('../scripts/diagnose-csp-manifest');

function manifest(files) { return { version: 1, algorithm: 'sha256', files, hashes: [...new Set(Object.values(files).flat())].sort() }; }
function fixture(script = 'self.__next_f.push([1,"7:I[123,[\\"45\\",\\"static/chunks/app/page.js\\"],\\"default\\"]\\n"])') {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'csp-diagnostic-'));
  const out = path.join(root, 'out'); fs.mkdirSync(out);
  fs.writeFileSync(path.join(out, 'index.html'), `<script src="a.js"></script><script>${script}</script>`);
  return { root, out, script };
}

function assertMetadata(field, index, type, text) {
  assert.equal(field.index, index); assert.equal(field.type, type);
  assert.equal(field.bytes, Buffer.byteLength(text)); assert.equal(field.chars, text.length);
  assert.match(field.sha256, /^[0-9a-f]{64}$/);
}

test('extracts only the added inline script and emits scalar and chunk element metadata', () => {
  const f = fixture();
  const records = compare(manifest({ 'index.html': [hash('old')] }), manifest({ 'index.html': [hash(f.script)] }), f.out);
  assert.equal(records.length, 1); assert.equal(records[0].scriptIndex, 1); assert.equal(records[0].rscI.length, 1);
  const [id, chunks, exported] = records[0].rscI[0];
  assertMetadata(id, 0, 'number', '123'); assert.equal(id.value, 123);
  assertMetadata(chunks, 1, 'array', '["45","static/chunks/app/page.js"]');
  assert.deepEqual(chunks.elements.map((x) => x.value), ['45', 'static/chunks/app/page.js']);
  assertMetadata(exported, 2, 'string', 'default'); assert.equal(exported.value, 'default');
});

test('exact per-element hashes distinguish same-length single-element changes', () => {
  const left = strictArrayMetadata('["static/chunks/a.js","abcd"]');
  const right = strictArrayMetadata('["static/chunks/b.js","abcd"]');
  assert.equal(left[0].chars, right[0].chars); assert.equal(left[0].bytes, right[0].bytes);
  assert.notEqual(left[0].sha256, right[0].sha256); assert.equal(left[1].sha256, right[1].sha256);
});

test('scalar literals expose only strict public module and export tokens', () => {
  const [fields] = balancedTuples('I["ClientPageRoot","default","0123456789abcdef","","ordinary sentence here","https://example.com/?token=secret","api_key=secret-token"]');
  assert.deepEqual(fields.slice(0, 3).map((field) => field.value), ['ClientPageRoot', 'default', '0123456789abcdef']);
  for (const field of fields.slice(3)) {
    assert.equal(field.value, undefined);
    assert.match(field.sha256, /^[0-9a-f]{64}$/);
  }
});

test('allows only strict public chunk literals and retains metadata otherwise', () => {
  const values = strictArrayMetadata('["deadbeef","static/chunks/app/page-abc.js","webpack-token_1",42,true,null,"not a chunk/path.txt"]');
  assert.deepEqual(values.slice(0, 3).map((x) => x.value), ['deadbeef', 'static/chunks/app/page-abc.js', 'webpack-token_1']);
  assert.equal(values[3].value, undefined); assert.equal(values[4].value, undefined); assert.equal(values[5].value, undefined);
  assert.equal(values[6].value, undefined); assert.match(values[6].sha256, /^[0-9a-f]{64}$/);
});

test('refuses raw, backslash, file URI, single- and double-encoded private paths', () => {
  const unsafe = ['/home/runner/work/repo', '\\Users\\runneradmin\\work\\repo', 'C:/Users/runneradmin/work/repo', 'file:///C:/Users/runner/work/repo', 'C%3A%5CUsers%5Crunner%5Cwork', '%252Fhome%252Frunner%252Fwork'];
  for (const value of unsafe) {
    assert.equal(containsPrivatePath(value), true, value);
    assert.throws(() => strictArrayMetadata(JSON.stringify([value])), DiagnosticError, value);
  }
  assert.throws(() => strictArrayMetadata('["../private/chunk.js"]'), DiagnosticError);
  assert.equal(containsPrivatePath('static/chunks/app/page.js'), false);
});

test('refuses malformed, nested, unsupported JSON and bounded counts', () => {
  for (const value of ['[', '{"x":1}', '[["x"]]', '[{"x":1}]']) assert.throws(() => strictArrayMetadata(value), DiagnosticError, value);
  assert.throws(() => strictArrayMetadata(JSON.stringify(Array(65).fill('a'))), DiagnosticError);
  assert.throws(() => strictArrayMetadata(JSON.stringify(['x'.repeat(241)])), DiagnosticError);
  assert.throws(() => balancedTuples(`I[${JSON.stringify({ bad: true })}]`), DiagnosticError);
});

test('is quiet when manifests are unchanged', () => {
  const f = fixture('safe'); const m = manifest({ 'index.html': [hash('safe')] });
  assert.deepEqual(compare(m, m, f.out), []);
  const lines = []; emit([], (line) => lines.push(line)); assert.deepEqual(lines, []);
});

test('all v2 output lines are byte-bounded and tuples are separate records', () => {
  const f = fixture();
  const records = compare(manifest({ 'index.html': [hash('old')] }), manifest({ 'index.html': [hash(f.script)] }), f.out);
  const lines = []; emit(records, (line) => lines.push(line));
  assert.equal(JSON.parse(lines[0]).version, 2); assert.equal(JSON.parse(lines[1]).type, 'csp-script'); assert.equal(JSON.parse(lines[2]).type, 'rsc-tuple');
  assert.ok(lines.every((line) => Buffer.byteLength(line) <= 8192));
});

test('fails closed for private paths, malformed manifests and unmatched hashes', () => {
  const unsafe = fixture('self.__next_f.push([1,"I[\\"C:/Users/runner/secret\\"]"])');
  assert.throws(() => compare(manifest({ 'index.html': [] }), manifest({ 'index.html': [hash(unsafe.script)] }), unsafe.out), DiagnosticError);
  assert.throws(() => balancedTuples('I["unterminated"'), DiagnosticError);
  assert.throws(() => compare(manifest({ 'index.html': [] }), manifest({ 'index.html': [hash('missing')] }), unsafe.out), DiagnosticError);
});

test('CLI retains file invocation behavior and rejects malformed generated input', () => {
  const f = fixture(); const tracked = path.join(f.root, 'tracked.json'); const generated = path.join(f.root, 'generated.json');
  fs.writeFileSync(tracked, JSON.stringify(manifest({ 'index.html': [hash('old')] })));
  fs.writeFileSync(generated, JSON.stringify(manifest({ 'index.html': [hash(f.script)] })));
  const lines = []; assert.equal(main(['--tracked', tracked, '--generated', generated, '--out', f.out], (line) => lines.push(line)), 1); assert.equal(lines.length, 3);
  fs.writeFileSync(generated, '{'); assert.throws(() => main(['--tracked', tracked, '--generated', generated, '--out', f.out], () => {}), DiagnosticError);
});
