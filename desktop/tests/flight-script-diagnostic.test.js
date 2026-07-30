'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const { analyzeHtml, analyzeScript, firstDifference } = require('../scripts/analyze-flight-script');
function script(lines) { return `self.__next_f.push(${JSON.stringify([1, `${lines.join('\n')}\n`])})`; }
test('bounded report preserves segment order and hashes canonical I rows without payload disclosure', () => {
  const report = analyzeScript(script(['1:"$Sreact.fragment"', '2:I["0123456789abcdef",[],""]', '3:HL["/_next/static/a.css","style"]']));
  assert.deepEqual(report.segments.map((item) => [item.rawLineIndex, item.kind]), [[0, 'non-I'], [1, 'I'], [2, 'non-I']]);
  assert.equal(report.segments[0].raw, undefined); assert.equal(report.segments[2].raw, undefined);
  assert.equal(report.segments[1].moduleId, '0123456789abcdef'); assert.match(report.segments[1].canonicalJsonSha256, /^[0-9a-f]{64}$/);
});
test('first difference identifies a changed chunk filename before the script hash', () => {
  const left = analyzeScript(script(['5:I["0123456789abcdef",["app/page","static/chunks/app/page-aaaaaaaaaaaaaaaa.js"],"default"]']));
  const right = analyzeScript(script(['5:I["0123456789abcdef",["app/page","static/chunks/app/page-bbbbbbbbbbbbbbbb.js"],"default"]']));
  const difference = firstDifference(left, right);
  assert.equal(difference.segmentOrder, 0); assert.equal(difference.field, 'canonical-I-row');
  assert.ok(JSON.parse(difference.expectedContext.escaped).length <= 48);
  assert.doesNotMatch(JSON.stringify(difference), /[/\\](?:home|Users|runner)[/\\]/i);
});
test('analyzeHtml uses absolute HTML script indexes including external scripts', () => {
  const html = `<script src="safe.js"></script><script></script><script>${script(['2:I["0123456789abcdef",[],""]'])}</script>`;
  assert.equal(analyzeHtml(html, 2).segments[0].moduleId, '0123456789abcdef');
});
