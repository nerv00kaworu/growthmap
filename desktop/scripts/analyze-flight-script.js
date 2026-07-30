'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const vm = require('node:vm');
const MAX_SCRIPT_BYTES = 16384, MAX_SEGMENTS = 64, MAX_CONTEXT = 24;
const MODULE_RE = /^[0-9a-f]{16}(?:-[1-9][0-9]*)?$/;
const EXPORT_RE = /^[A-Za-z0-9_$.-]{0,80}$/;
const CHUNK_RE = /^(?:|[A-Za-z0-9][A-Za-z0-9._~@+/-]*)$/;
function hex(value) { return crypto.createHash('sha256').update(value, 'utf8').digest('hex'); }
function csp(value) { return `sha256-${crypto.createHash('sha256').update(value, 'utf8').digest('base64')}`; }
function safe(value, pattern, label) { assert.equal(typeof value, 'string'); assert.ok(pattern.test(value), `unsafe ${label}`); return value; }
function inlineScripts(html) { return [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi)].map((match, index) => ({ index, external: /(?:^|\s)src\s*=/i.test(match[1]), content: match[2] })); }
function analyzeScript(content, scriptIndex = 9) {
  assert.ok(Buffer.byteLength(content, 'utf8') <= MAX_SCRIPT_BYTES, 'script exceeds diagnostic bound');
  const pushes = []; vm.runInNewContext(content, { self: { __next_f: { push(value) { pushes.push(value); } } } }, { timeout: 1000 });
  const segments = []; let rawLineIndex = 0;
  for (const push of pushes) {
    if (!Array.isArray(push) || typeof push[1] !== 'string') continue;
    for (const match of push[1].matchAll(/[^\n]*(?:\n|$)/g)) {
      const raw = match[0]; if (!raw) continue;
      assert.ok(segments.length < MAX_SEGMENTS, 'segment count exceeds diagnostic bound');
      const line = raw.endsWith('\n') ? raw.slice(0, -1) : raw;
      const imported = line.match(/^[^:]+:I(\[.*\])$/);
      if (!imported) segments.push({ order: segments.length, rawLineIndex, kind: 'non-I', bytes: Buffer.byteLength(raw), chars: raw.length, sha256: hex(raw) });
      else {
        const tuple = JSON.parse(imported[1]); assert.equal(tuple.length, 3, 'unsupported Flight I row');
        const moduleId = safe(tuple[0], MODULE_RE, 'module id');
        assert.ok(Array.isArray(tuple[1]) && tuple[1].length <= 64, 'unsupported chunks');
        const chunks = tuple[1].map((value) => safe(value, CHUNK_RE, 'chunk literal'));
        const exportName = safe(tuple[2], EXPORT_RE, 'export');
        segments.push({ order: segments.length, rawLineIndex, kind: 'I', bytes: Buffer.byteLength(raw), chars: raw.length, sha256: hex(raw), moduleId,
          chunks: chunks.map((value, index) => ({ index, value, sha256: hex(value) })), export: exportName,
          canonicalJsonSha256: hex(JSON.stringify([moduleId, chunks, exportName])) });
      }
      rawLineIndex += 1;
    }
  }
  return { version: 1, scriptIndex, sha256: csp(content), bytes: Buffer.byteLength(content), chars: content.length, segments };
}
function analyzeHtml(html, scriptIndex = 9) { const script = inlineScripts(html).find((item) => item.index === scriptIndex && !item.external); assert.ok(script); return analyzeScript(script.content, scriptIndex); }
function canonical(segment) { return JSON.stringify([segment.moduleId, segment.chunks.map((item) => item.value), segment.export]); }
function context(value, offset) { const start = Math.max(0, offset - MAX_CONTEXT), end = Math.min(value.length, offset + MAX_CONTEXT); return { start, escaped: JSON.stringify(value.slice(start, end)) }; }
function firstDifference(expected, actual) {
  const count = Math.max(expected.segments.length, actual.segments.length);
  for (let index = 0; index < count; index += 1) {
    const left = expected.segments[index], right = actual.segments[index];
    if (!left || !right) return { segmentOrder: index, field: 'segment-presence' };
    for (const field of ['rawLineIndex', 'kind']) if (left[field] !== right[field]) return { segmentOrder: index, field, expected: left[field], actual: right[field] };
    if (left.kind === 'I' && canonical(left) !== canonical(right)) { const a = canonical(left), b = canonical(right); let offset = 0; while (offset < a.length && offset < b.length && a[offset] === b[offset]) offset += 1; return { segmentOrder: index, rawLineIndex: right.rawLineIndex, field: 'canonical-I-row', byteOffset: offset, expectedContext: context(a, offset), actualContext: context(b, offset) }; }
    if (left.sha256 !== right.sha256 || left.bytes !== right.bytes) return { segmentOrder: index, rawLineIndex: right.rawLineIndex, field: left.kind === 'I' ? 'I-row-wire-encoding' : 'non-I-payload', expected: { bytes: left.bytes, sha256: left.sha256 }, actual: { bytes: right.bytes, sha256: right.sha256 } };
  }
  return expected.sha256 === actual.sha256 ? null : { field: 'script-envelope-or-escaping', expected: { bytes: expected.bytes, sha256: expected.sha256 }, actual: { bytes: actual.bytes, sha256: actual.sha256 } };
}
function main(argv = process.argv.slice(2)) { const options = Object.fromEntries(argv.reduce((pairs, value, index) => index % 2 ? pairs : [...pairs, [value, argv[index + 1]]], [])); const report = analyzeHtml(fs.readFileSync(options['--html'], 'utf8'), Number(options['--script-index'] || 9)); if (options['--baseline']) report.firstDifference = firstDifference(JSON.parse(fs.readFileSync(options['--baseline'], 'utf8')), report); process.stdout.write(`${JSON.stringify(report)}\n`); }
if (require.main === module) main();
module.exports = { analyzeHtml, analyzeScript, firstDifference, inlineScripts };
