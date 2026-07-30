'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const EXPECTED_VERSION = '15.5.21';
const EXPECTED_INTEGRITY = 'sha512-/TsdBtkWLhkl+NVL3Uqws2UphNd6IPzOtzSk1fHaf+0P7GQKLZDUytyhns/Ykbzdy9+YRjwG7ONvrHaaTDdFqQ==';
const ORIGINAL_SHA256 = '0ba3db12307085b9eb3f942b2f5eadad9dca46fb98516d28cbfe2d561cf9240b';
const PATCHED_SHA256 = '685667b95b09488f8fcbfb19102569cb81c9e9e56419f9b8aa72b560f5ee4e74';
const ORIGINAL = `    return chunks;\n}\n// Normalize the entry names`;
const PATCHED = `    // Keep each chunk id/file tuple intact and order by emitted file first. The\n    // file is the stable identity when webpack exposes an empty chunk id.\n    const pairs = [];\n    for(let index = 0; index < chunks.length; index += 2)pairs.push([chunks[index], chunks[index + 1]]);\n    pairs.sort((a, b)=>a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0);\n    return pairs.flat();\n}\n// Normalize the entry names`;
function sha256(value) { return crypto.createHash('sha256').update(value).digest('hex'); }
function patchNext(root = __dirname) {
  const frontend = path.resolve(root, '..');
  const lock = JSON.parse(fs.readFileSync(path.join(frontend, 'package-lock.json'), 'utf8'));
  const locked = lock.packages?.['node_modules/next'];
  assert.equal(locked?.version, EXPECTED_VERSION, 'refusing to patch an unpinned Next version');
  assert.equal(locked?.integrity, EXPECTED_INTEGRITY, 'refusing to patch Next with unexpected npm provenance');
  const nextRoot = path.join(frontend, 'node_modules', 'next');
  assert.equal(JSON.parse(fs.readFileSync(path.join(nextRoot, 'package.json'), 'utf8')).version, EXPECTED_VERSION);
  const target = path.join(nextRoot, 'dist', 'build', 'webpack', 'plugins', 'flight-manifest-plugin.js');
  const source = fs.readFileSync(target, 'utf8');
  const before = sha256(source);
  if (before === PATCHED_SHA256) return target;
  assert.equal(before, ORIGINAL_SHA256, 'refusing to patch unexpected Next flight manifest source');
  assert.equal(source.split(ORIGINAL).length, 2, 'Next flight manifest patch anchor must be unique');
  const result = source.replace(ORIGINAL, PATCHED);
  assert.equal(sha256(result), PATCHED_SHA256, 'Next flight manifest patch output drifted');
  fs.writeFileSync(target, result, 'utf8');
  return target;
}
if (require.main === module) console.log(`Patched ${patchNext()}`);
module.exports = { patchNext, ORIGINAL, PATCHED, ORIGINAL_SHA256, PATCHED_SHA256 };
