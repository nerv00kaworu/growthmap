'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

function fail(message) {
  throw new Error(`app/page diagnostic refused: ${message}`);
}
function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}
function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index], value = argv[index + 1];
    if (!key?.startsWith('--') || !value) fail('expected --next and --out arguments');
    values[key.slice(2)] = value;
  }
  if (!values.next || !values.out) fail('expected --next and --out arguments');
  return values;
}

// This intentionally recognizes only identifiers that webpack renders as
// GrowthMap's 16-hex stable module IDs. It never copies arbitrary strings into
// metadata, so paths, source text, and credentials cannot leak through it.
function stableModuleIds(source) {
  const ids = [];
  const expression = /(?:^|[,{])(?:"([a-f0-9]{16})"|([a-f0-9]{16}))(?=:)/g;
  for (const match of source.matchAll(expression)) ids.push(match[1] || match[2]);
  return ids;
}

function scanPublicBundle(source) {
  const denied = [
    ['POSIX user/build path', /\/(?:home|Users|private\/var|var\/folders|tmp|runner|github\/workspace)\//i],
    ['Windows absolute path', /(?:^|[^A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+[\\/])/],
    ['private key material', /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
    ['GitHub credential', /(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})/],
    ['AWS access key', /(?:AKIA|ASIA)[A-Z0-9]{16}/],
    ['OpenAI-style secret', /\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}/],
    ['generic assigned secret', /(?:api[_-]?key|client[_-]?secret|access[_-]?token|password)\s*[:=]\s*["'][^"']{12,}["']/i],
    ['source map reference', /\/\/[#@]\s*sourceMappingURL=/],
    ['eval source URL', /\/\/[#@]\s*sourceURL=/],
  ];
  for (const [label, expression] of denied) if (expression.test(source)) fail(label);
}

function stageAppPageChunk(nextRoot, outputRoot) {
  const chunks = path.join(nextRoot, 'static', 'chunks', 'app');
  if (!fs.statSync(chunks, { throwIfNoEntry: false })?.isDirectory()) fail('missing .next app chunk directory');
  const matches = fs.readdirSync(chunks).filter((name) => /^page-[a-f0-9]+\.js$/.test(name)).sort();
  if (matches.length !== 1) fail(`expected exactly one app/page chunk, found ${matches.length}`);
  const name = matches[0];
  const bytes = fs.readFileSync(path.join(chunks, name));
  const source = bytes.toString('utf8');
  if (!Buffer.from(source, 'utf8').equals(bytes)) fail('chunk is not canonical UTF-8');
  scanPublicBundle(source);

  const ids = stableModuleIds(source);
  const metadata = {
    schema: 1,
    emittedFile: `static/chunks/app/${name}`,
    sha256: sha256(bytes),
    size: bytes.length,
    stableModuleIds: {
      count: ids.length,
      orderedSha256: sha256(ids.join('\n')),
      first: ids.slice(0, 32),
      last: ids.slice(-32),
    },
  };

  fs.rmSync(outputRoot, { recursive: true, force: true });
  fs.mkdirSync(outputRoot, { recursive: true });
  fs.writeFileSync(path.join(outputRoot, name), bytes, { flag: 'wx' });
  fs.writeFileSync(path.join(outputRoot, 'metadata.json'), `${JSON.stringify(metadata, null, 2)}\n`, { flag: 'wx' });
  return metadata;
}

if (require.main === module) {
  try {
    const args = parseArgs(process.argv.slice(2));
    const metadata = stageAppPageChunk(path.resolve(args.next), path.resolve(args.out));
    console.log(`Staged scanned public app/page chunk: sha256=${metadata.sha256} size=${metadata.size}`);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}

module.exports = { scanPublicBundle, stableModuleIds, stageAppPageChunk };
