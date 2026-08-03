'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { hash } = require('./csp-manifest');

const SCRIPT_RE = /<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi;
const SRC_RE = /(?:^|\s)src\s*=/i;
const SHA_RE = /^sha256-[A-Za-z0-9+/]{43}=$/;
const MAX_FILES = 16;
const MAX_SCRIPTS = 32;
const MAX_TUPLES = 24;
const MAX_FIELDS = 8;
const MAX_ELEMENTS = 64;
const MAX_TOKEN = 240;
const MAX_LINE = 8192;

class DiagnosticError extends Error {}
function fail(message) { throw new DiagnosticError(message); }
function parseJson(text, label) {
  let value;
  try { value = JSON.parse(text); } catch { fail(`${label} is malformed JSON`); }
  if (!value || ![1, 2].includes(value.version) || value.algorithm !== 'sha256' || !value.files || typeof value.files !== 'object' || Array.isArray(value.files)) fail(`${label} has an unsupported schema`);
  for (const [file, hashes] of Object.entries(value.files)) {
    if (!safeRelative(file) || !Array.isArray(hashes) || hashes.some((item) => typeof item !== 'string' || !SHA_RE.test(item))) fail(`${label} contains an unsafe file or hash`);
  }
  return value;
}
function safeRelative(value) {
  return typeof value === 'string' && value.length > 0 && value.length <= MAX_TOKEN && !value.includes('\\') && !value.startsWith('/') && !value.split('/').includes('..') && !/[\u0000-\u001f\u007f]/.test(value);
}
function decodedForms(value) {
  const forms = [String(value)];
  for (let i = 0; i < 2; i += 1) {
    try { forms.push(decodeURIComponent(forms.at(-1))); } catch { break; }
  }
  return forms.flatMap((item) => [item, item.replace(/\\/g, '/')]);
}
function containsPrivatePath(value) {
  return decodedForms(value).some((item) => /(?:file:\/{2,}|(?:^|[\s"'])\/{1,2}(?:home|users|tmp|private|runner|github\/workspace)(?:\/|$)|(?:^|[\s"'])[a-z]:\/(?:users|runner|actions|workspace|home|tmp)(?:\/|$)|\/home\/runner\/work\/|\/__w\/)/i.test(item));
}
function digest(value) { return crypto.createHash('sha256').update(value, 'utf8').digest('hex'); }
function scalarText(value) {
  if (typeof value === 'string') return value;
  if (value === null || typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value))) return JSON.stringify(value);
  if (Array.isArray(value)) return JSON.stringify(value);
  fail('unsupported non-scalar RSC tuple field');
}
function scalarType(value) { return value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value; }
function safeChunkLiteral(value) {
  if (typeof value !== 'string' || value.length === 0 || value.length > MAX_TOKEN || /[\u0000-\u001f\u007f\\]/.test(value) || containsPrivatePath(value)) return false;
  if (/%(?:25)*2[ef]|%(?:25)*5c|file:/i.test(value)) return false;
  if (/^[0-9a-f]+$/i.test(value)) return true;
  if (/^static\/chunks\/(?!.*(?:^|\/)\.\.?\/(?:|$))[A-Za-z0-9._~@+/-]+\.js$/.test(value)) return true;
  return /^[A-Za-z0-9][A-Za-z0-9._~@+-]*$/.test(value);
}
function elementMetadata(value, index) {
  const text = scalarText(value);
  if (text.length > MAX_TOKEN) fail('chunk-list element exceeds diagnostic bound');
  if (/[\u0000-\u001f\u007f]/.test(text)) fail('control character in chunk-list element');
  const unsafePath = decodedForms(text).some((item) => /^(?:file:|\.{1,2}[\\/]|[\\/]|[a-z]:[\\/])/i.test(item));
  if (containsPrivatePath(text) || text.includes('\\') || unsafePath) fail('unsafe path in chunk-list element');
  const result = { index, type: scalarType(value), bytes: Buffer.byteLength(text, 'utf8'), chars: text.length, sha256: digest(text) };
  if (safeChunkLiteral(value)) result.value = value;
  return result;
}
function strictArrayMetadata(text) {
  let value;
  try { value = JSON.parse(text); } catch { fail('malformed JSON-array RSC tuple field'); }
  if (!Array.isArray(value)) fail('unsupported JSON RSC tuple field');
  if (value.length > MAX_ELEMENTS) fail('chunk-list element count exceeds diagnostic bound');
  return value.map((item, index) => {
    if (item !== null && typeof item === 'object') fail('nested chunk-list value is unsupported');
    return elementMetadata(item, index);
  });
}
function fieldMetadata(value, index) {
  const text = scalarText(value);
  if (/[\u0000-\u001f\u007f]/.test(text)) fail('control character in RSC tuple field');
  if (containsPrivatePath(text)) fail('private absolute path detected');
  const result = { index, type: scalarType(value), bytes: Buffer.byteLength(text, 'utf8'), chars: text.length, sha256: digest(text) };
  if (Array.isArray(value)) result.elements = strictArrayMetadata(text);
  else if (typeof value === 'string' && value.trimStart().startsWith('[')) result.elements = strictArrayMetadata(value);
  else if (safeChunkLiteral(value)) result.value = value;
  else if (typeof value !== 'string') result.value = value;
  return result;
}
function inlineScripts(html) {
  const scripts = [];
  let allIndex = 0;
  for (const match of html.matchAll(SCRIPT_RE)) {
    if (!SRC_RE.test(match[1])) scripts.push({ index: allIndex, content: match[2], sha256: hash(match[2]) });
    allIndex += 1;
  }
  return scripts;
}
function decodeJsStrings(script) {
  const parts = [];
  const literal = /"(?:\\.|[^"\\])*"/g;
  for (const match of script.matchAll(literal)) {
    try { parts.push(JSON.parse(match[0])); } catch { fail('malformed JavaScript string in changed inline script'); }
  }
  return parts.some((item) => item.includes('I[')) ? parts.join('\n') : script;
}
function balancedTuples(text) {
  const tuples = [];
  for (let cursor = 0; cursor < text.length;) {
    const marker = text.indexOf('I[', cursor);
    if (marker < 0) break;
    if (tuples.length >= MAX_TUPLES) fail('RSC tuple count exceeds diagnostic bound');
    let depth = 1; let quote = false; let escaped = false; let end = -1;
    for (let i = marker + 2; i < text.length && i - marker <= 4096; i += 1) {
      const char = text[i];
      if (quote) { if (escaped) escaped = false; else if (char === '\\') escaped = true; else if (char === '"') quote = false; continue; }
      if (char === '"') quote = true;
      else if (char === '[') depth += 1;
      else if (char === ']' && --depth === 0) { end = i; break; }
    }
    if (end < 0) fail('malformed RSC client-reference tuple');
    let tuple;
    try { tuple = JSON.parse(`[${text.slice(marker + 2, end)}]`); } catch { fail('malformed RSC client-reference tuple'); }
    if (!Array.isArray(tuple) || tuple.length < 1 || tuple.length > MAX_FIELDS) fail('unsupported RSC client-reference tuple');
    tuples.push(tuple.map((field, index) => fieldMetadata(field, index)));
    cursor = end + 1;
  }
  return tuples;
}
function compare(tracked, generated, outDirectory) {
  const records = [];
  const files = [...new Set([...Object.keys(tracked.files), ...Object.keys(generated.files)])].sort();
  if (files.length > 1000) fail('manifest file count exceeds diagnostic bound');
  for (const file of files) {
    const oldHashes = tracked.files[file] || [];
    const newHashes = generated.files[file] || [];
    const removed = oldHashes.filter((item) => !newHashes.includes(item));
    const added = newHashes.filter((item) => !oldHashes.includes(item));
    if (!removed.length && !added.length) continue;
    if (records.length >= MAX_FILES) fail('changed file count exceeds diagnostic bound');
    const absolute = path.resolve(outDirectory, ...file.split('/'));
    const root = `${path.resolve(outDirectory)}${path.sep}`;
    if (!absolute.startsWith(root) || !fs.statSync(absolute, { throwIfNoEntry: false })?.isFile()) fail('changed HTML file is missing or escapes output root');
    const html = fs.readFileSync(absolute, 'utf8');
    if (containsPrivatePath(html)) fail('private absolute path detected in changed HTML');
    const scripts = inlineScripts(html);
    const matches = scripts.filter((script) => added.includes(script.sha256));
    if (matches.length !== added.length || new Set(matches.map((item) => item.sha256)).size !== added.length) fail('changed hash does not uniquely identify an inline script');
    for (const script of matches) {
      if (records.length >= MAX_SCRIPTS) fail('changed script count exceeds diagnostic bound');
      records.push({ file, scriptIndex: script.index, sha256: script.sha256, bytes: Buffer.byteLength(script.content, 'utf8'), chars: script.content.length, removed, rscI: balancedTuples(decodeJsStrings(script.content)) });
    }
  }
  return records;
}
function outputLine(value, output) {
  const line = JSON.stringify(value);
  if (Buffer.byteLength(line, 'utf8') > MAX_LINE) fail('diagnostic line exceeds output bound');
  output(line);
}
function emit(records, output = console.log) {
  if (!records.length) return;
  outputLine({ type: 'csp-diagnostic', version: 2, changedScripts: records.length }, output);
  for (const record of records) {
    const { rscI, ...script } = record;
    outputLine({ type: 'csp-script', ...script, tuples: rscI.length }, output);
    rscI.forEach((fields, tupleIndex) => outputLine({ type: 'rsc-tuple', file: record.file, scriptIndex: record.scriptIndex, tupleIndex, fields }, output));
  }
}
function args(argv) {
  const result = {};
  for (let i = 0; i < argv.length; i += 2) { if (!argv[i]?.startsWith('--') || argv[i + 1] === undefined) fail('invalid arguments'); result[argv[i].slice(2)] = argv[i + 1]; }
  return result;
}
function main(argv = process.argv.slice(2), output = console.log) {
  const options = args(argv);
  if (!options.generated || !options.out || (!options.tracked && !options['tracked-git'])) fail('required arguments: --generated, --out, and --tracked or --tracked-git');
  let trackedText;
  if (options.tracked) trackedText = fs.readFileSync(options.tracked, 'utf8');
  else {
    if (!/^HEAD:[A-Za-z0-9._/-]+$/.test(options['tracked-git'])) fail('unsafe tracked git object');
    const result = spawnSync('git', ['show', options['tracked-git']], { encoding: 'utf8', maxBuffer: 1024 * 1024 });
    if (result.status !== 0) fail('could not read tracked manifest');
    trackedText = result.stdout;
  }
  const records = compare(parseJson(trackedText, 'tracked manifest'), parseJson(fs.readFileSync(options.generated, 'utf8'), 'generated manifest'), options.out);
  emit(records, output);
  return records.length;
}
if (require.main === module) {
  try { main(); } catch (error) { console.error(`CSP diagnostic refused output: ${error instanceof DiagnosticError ? error.message : 'unexpected input or I/O failure'}`); process.exitCode = 2; }
}
module.exports = { DiagnosticError, balancedTuples, compare, containsPrivatePath, emit, fieldMetadata, inlineScripts, main, parseJson, safeChunkLiteral, strictArrayMetadata };
