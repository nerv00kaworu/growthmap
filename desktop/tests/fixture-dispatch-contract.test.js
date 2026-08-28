const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const testsDir = __dirname;
const constructorNames = ['createLineageAuthority', 'createReplacementJournal', 'createSecretStore'];

function blanks(value) {
  return value.replace(/[^\n]/g, ' ');
}

function regexCanStart(source, index) {
  let i = index - 1;
  while (i >= 0 && /\s/.test(source[i])) i--;
  if (i < 0 || /[({[=,:;!?&|+\-*%^~<>]/.test(source[i])) return true;
  const word = source.slice(0, i + 1).match(/([A-Za-z_$][\w$]*)$/)?.[1];
  return ['return', 'throw', 'case', 'delete', 'typeof', 'void', 'new', 'in', 'of', 'yield', 'await'].includes(word);
}

function skipQuoted(source, start, quote) {
  let i = start + 1;
  while (i < source.length) {
    if (source[i] === '\\') i += 2;
    else if (source[i++] === quote) break;
  }
  return i;
}

function skipRegex(source, start) {
  let i = start + 1, inClass = false;
  while (i < source.length) {
    const c = source[i];
    if (c === '\\') i += 2;
    else if (c === '[') { inClass = true; i++; }
    else if (c === ']' && inClass) { inClass = false; i++; }
    else if (c === '/' && !inClass) { i++; while (/[A-Za-z]/.test(source[i] || '')) i++; break; }
    else i++;
  }
  return i;
}

function skipLineComment(source, start) {
  const end = source.indexOf('\n', start + 2);
  return end < 0 ? source.length : end;
}

function skipBlockComment(source, start) {
  const end = source.indexOf('*/', start + 2);
  return end < 0 ? source.length : end + 2;
}

function consumeExpression(source, start, context, templates) {
  let i = start, depth = 1, templateOrdinal = 0;
  while (i < source.length && depth) {
    const c = source[i], n = source[i + 1];
    if (c === '"' || c === "'") i = skipQuoted(source, i, c);
    else if (c === '`') {
      const nestedContext = `${context}/template#${++templateOrdinal}`;
      i = consumeTemplate(source, i, nestedContext, templates).end;
    } else if (c === '/' && n === '/') i = skipLineComment(source, i);
    else if (c === '/' && n === '*') i = skipBlockComment(source, i);
    else if (c === '/' && regexCanStart(source, i)) i = skipRegex(source, i);
    else { if (c === '{') depth++; else if (c === '}') depth--; i++; }
  }
  return i;
}

function consumeTemplate(source, start, context, templates) {
  let i = start + 1, raw = '', expressionOrdinal = 0;
  while (i < source.length) {
    const c = source[i], n = source[i + 1];
    if (c === '\\') {
      raw += source.slice(i, Math.min(i + 2, source.length));
      i += 2;
    } else if (c === '`') {
      templates.push({context, source: raw});
      return {end: i + 1, raw};
    } else if (c === '$' && n === '{') {
      const expressionContext = `${context}/expression#${++expressionOrdinal}`;
      const end = consumeExpression(source, i + 2, expressionContext, templates);
      raw += blanks(source.slice(i, end));
      i = end;
    } else {
      raw += c;
      i++;
    }
  }
  templates.push({context, source: raw});
  return {end: i, raw};
}

// Mask strings, comments, regexes, and templates while preserving offsets/newlines.
// Every template raw body is returned once, including templates nested in expressions.
function lexicalViews(source) {
  let clean = '', i = 0, templateOrdinal = 0;
  const templates = [];
  while (i < source.length) {
    const c = source[i], n = source[i + 1];
    let end = i + 1;
    if (c === '"' || c === "'") end = skipQuoted(source, i, c);
    else if (c === '`') {
      end = consumeTemplate(source, i, `template#${++templateOrdinal}`, templates).end;
    } else if (c === '/' && n === '/') end = skipLineComment(source, i);
    else if (c === '/' && n === '*') end = skipBlockComment(source, i);
    else if (c === '/' && regexCanStart(source, i)) end = skipRegex(source, i);
    else if (c === '\\') end = Math.min(i + 2, source.length);
    if (end === i + 1) clean += c;
    else clean += blanks(source.slice(i, end));
    i = end;
  }
  return {clean, templates};
}

function scanView(source, context) {
  const clean = lexicalViews(source).clean;
  const found = [];
  for (const name of constructorNames) {
    const re = new RegExp(`\\b${name}\\s*\\(\\s*\\{`, 'g');
    for (let match; (match = re.exec(clean));) {
      const open = clean.indexOf('{', match.index);
      let depth = 0, end = -1;
      for (let i = open; i < clean.length; i++) {
        if (clean[i] === '{') depth++;
        else if (clean[i] === '}' && !--depth) { end = i + 1; break; }
      }
      assert(end > open, `${context} ${name} has unbalanced constructor options`);
      found.push({name, context, start: match.index, end, options: source.slice(open, end), viewSource: source, clean});
    }
  }
  return found.sort((a, b) => a.start - b.start);
}

function scanSource(source) {
  const views = lexicalViews(source);
  const found = scanView(source, 'normal');
  for (const template of views.templates) found.push(...scanView(template.source, template.context));
  const ordinals = new Map();
  for (const call of found) {
    const key = `${call.context}:${call.name}`;
    call.ordinal = (ordinals.get(key) || 0) + 1;
    ordinals.set(key, call.ordinal);
  }
  return found;
}

function hasProperty(options, name) {
  return new RegExp(`(?:^|[,\\n]\\s*)${name}(?:\\s*:|(?=\\s*[,}]))`).test(options);
}

function callKey(base, call) {
  return `${base}:${call.context}:${call.name}#${call.ordinal}`;
}

const rejectionAllowlist = new Set([
  'windows-async-credential-journal.test.js:normal:createReplacementJournal#1',
]);

function matchingDelimiter(clean, open, left, right) {
  let depth = 0;
  for (let i = open; i < clean.length; i++) {
    if (clean[i] === left) depth++;
    else if (clean[i] === right && !--depth) return i;
  }
  return -1;
}

function argumentSpans(clean, open, close) {
  const spans = [];
  let start = open + 1;
  const stack = [];
  const pairs = {')': '(', ']': '[', '}': '{'};
  for (let i = start; i < close; i++) {
    const c = clean[i];
    if ('([{'.includes(c)) stack.push(c);
    else if (')]}'.includes(c)) {
      if (stack.at(-1) === pairs[c]) stack.pop();
    } else if (c === ',' && stack.length === 0) {
      spans.push({start, end: i});
      start = i + 1;
    }
  }
  spans.push({start, end: close});
  return spans;
}

function trimSpan(source, span) {
  let {start, end} = span;
  while (start < end && /\s/.test(source[start])) start++;
  while (end > start && /\s/.test(source[end - 1])) end--;
  return {start, end};
}

function callbackBodySpan(clean, span) {
  const trimmed = trimSpan(clean, span);
  const text = clean.slice(trimmed.start, trimmed.end);
  if (/^(?:async\s+)?function(?:\s+[A-Za-z_$][\w$]*)?\s*\(/.test(text)) {
    const bodyOpen = clean.indexOf('{', trimmed.start);
    const bodyClose = bodyOpen < trimmed.end ? matchingDelimiter(clean, bodyOpen, '{', '}') : -1;
    return bodyClose >= 0 && bodyClose < trimmed.end ? {start: bodyOpen + 1, end: bodyClose} : null;
  }
  const stack = [];
  const pairs = {')': '(', ']': '[', '}': '{'};
  let arrow = -1;
  for (let i = trimmed.start; i + 1 < trimmed.end; i++) {
    const c = clean[i];
    if ('([{'.includes(c)) stack.push(c);
    else if (')]}'.includes(c) && stack.at(-1) === pairs[c]) stack.pop();
    else if (c === '=' && clean[i + 1] === '>' && stack.length === 0) { arrow = i; break; }
  }
  if (arrow < 0) return null;
  let bodyStart = arrow + 2;
  while (bodyStart < trimmed.end && /\s/.test(clean[bodyStart])) bodyStart++;
  if (clean[bodyStart] === '{') {
    const bodyClose = matchingDelimiter(clean, bodyStart, '{', '}');
    return bodyClose >= 0 && bodyClose < trimmed.end ? {start: bodyStart + 1, end: bodyClose} : null;
  }
  return {start: bodyStart, end: trimmed.end};
}

const sharedAdapterMessage = 'requires shared native broker adapter';

function matcherAssertsSharedAdapter(source, clean, span) {
  const {start, end} = trimSpan(source, span);
  const matcher = source.slice(start, end);
  // The sole allowlisted rejection contract uses a RegExp literal. Do not accept
  // predicate matchers: proving that an arbitrary callback actually checks and
  // returns on the expected message requires evaluating test code and previously
  // allowed the phrase to hide in an unused/default parameter.
  if (matcher[0] !== '/') return false;
  const regexEnd = skipRegex(source, start);
  if (regexEnd !== end) return false;
  try {
    const lastSlash = matcher.lastIndexOf('/');
    return new RegExp(matcher.slice(1, lastSlash), matcher.slice(lastSlash + 1)).test(sharedAdapterMessage);
  } catch { return false; }
}

function enclosingAssertThrows(call) {
  if (call.context !== 'normal') return null;
  const re = /\bassert\.throws\s*\(/g;
  for (let match; (match = re.exec(call.clean));) {
    const open = call.clean.indexOf('(', match.index);
    const close = matchingDelimiter(call.clean, open, '(', ')');
    if (close < 0) continue;
    const args = argumentSpans(call.clean, open, close);
    if (args.length < 2) continue;
    const body = callbackBodySpan(call.clean, args[0]);
    if (!body || call.start < body.start || call.end > body.end) continue;
    if (!matcherAssertsSharedAdapter(call.viewSource, call.clean, args[1])) continue;
    return {start: match.index, end: close + 1, args, body};
  }
  return null;
}

function validateCall(base, call) {
  const label = callKey(base, call);
  const win = /platform\s*:\s*['"]win32['"]/.test(call.options);
  const nonwin = /platform\s*:\s*['"](?:linux|darwin|freebsd)['"]/.test(call.options);
  const asyncSeam = ['windowsAdapter', 'files', 'filesFactory'].some(name => hasProperty(call.options, name));
  assert(win || nonwin, `${label} must explicitly select a platform`);
  if(nonwin)assert(hasProperty(call.options,'ownerUid'),`${label} explicit non-Windows fixture requires an ownerUid seam`);
  if (win && !asyncSeam) {
    assert(rejectionAllowlist.has(label), `${label} win32 constructor requires an async seam`);
    assert(enclosingAssertThrows(call), `${label} rejection must use a throwing callback and assert the shared-adapter error in assert.throws second argument`);
  } else {
    assert(!rejectionAllowlist.has(label), `${label} allowlist entry is stale because it now has an async seam`);
  }
}

// Exact, checked-in inventory. Context and per-constructor ordinal are line-independent;
// any constructor addition/removal requires deliberate review of this list.
const expectedInventory = [
  'credential-lineage.test.js:normal:createLineageAuthority#1',
  'credential-lineage.test.js:normal:createLineageAuthority#2',
  'credential-lineage.test.js:normal:createLineageAuthority#3',
  'credential-lineage.test.js:normal:createLineageAuthority#4',
  'database-manager-snapshot-drift.test.js:normal:createReplacementJournal#1',
  'database-manager.test.js:normal:createReplacementJournal#1',
  'replacement-committed-residue.test.js:normal:createReplacementJournal#1',
  'replacement-crash-subprocess.test.js:normal:createReplacementJournal#1',
  'replacement-crash-subprocess.test.js:template#2:createReplacementJournal#1',
  'replacement-install-crash.test.js:normal:createReplacementJournal#1',
  'replacement-install-crash.test.js:normal:createReplacementJournal#2',
  'replacement-malicious-residue.test.js:normal:createReplacementJournal#1',
  'replacement-recovery-reentry.test.js:normal:createReplacementJournal#1',
  'replacement-recovery-reentry.test.js:template#1:createReplacementJournal#1',
  'replacement-recovery-windows-handle-barrier.test.js:normal:createReplacementJournal#1',
  'replacement-recovery.test.js:normal:createReplacementJournal#1',
  'replacement-rollback-toctou.test.js:normal:createReplacementJournal#1',
  'replacement-supersession.test.js:normal:createReplacementJournal#1',
  'replacement-supersession.test.js:normal:createReplacementJournal#2',
  'replacement-supersession.test.js:normal:createReplacementJournal#3',
  'replacement-supersession.test.js:normal:createReplacementJournal#4',
  'replacement-terminal-cas.test.js:normal:createReplacementJournal#1',
  'replacement-toctou.test.js:normal:createReplacementJournal#1',
  'secret-store.test.js:normal:createSecretStore#1',
  'windows-async-credential-journal.test.js:normal:createReplacementJournal#1',
  'windows-async-credential-journal.test.js:normal:createReplacementJournal#2',
  'windows-async-credential-journal.test.js:normal:createReplacementJournal#3',
  'windows-async-credential-journal.test.js:normal:createReplacementJournal#4',
  'windows-async-lineage-matrix.test.js:normal:createLineageAuthority#1',
];

test('scanner sees normal and template-child constructors without lexical false positives', () => {
  const valid = scanSource([
    'createSecretStore({',
    " platform: 'linux',",
    ' ownerUid,',
    ' root',
    '});',
    'const child = `const tick = \\`ignored \\${host}\\`;',
    'const re = /createSecretStore\\\\({ platform: "win32" }/;',
    'createReplacementJournal({platform:"linux", ownerUid, userData:${JSON.stringify(root)}});`;',
  ].join('\n'));
  assert.deepEqual(valid.map(call => `${call.context}:${call.name}`), [
    'normal:createSecretStore',
    'template#1:createReplacementJournal',
  ]);
  for (const call of valid) validateCall('self-valid.test.js', call);

  const missingPlatform = scanSource('const child = `createReplacementJournal({userData:"/tmp"})`;');
  assert.throws(() => validateCall('self-missing.test.js', missingPlatform[0]), /explicitly select a platform/);

  const missingOwner = scanSource('const child = `createReplacementJournal({platform:"linux",userData:"/tmp"})`;');
  assert.throws(() => validateCall('self-owner.test.js', missingOwner[0]), /requires an ownerUid seam/);

  const missingAdapter = scanSource('const child = `createReplacementJournal({platform:"win32",userData:"C:\\\\u"})`;');
  assert.throws(() => validateCall('self-win.test.js', missingAdapter[0]), /requires an async seam/);

  const nestedValid = scanSource('const child = `outer ${`createReplacementJournal({platform:"linux",ownerUid})`}`;');
  assert.deepEqual(nestedValid.map(call => `${call.context}:${call.name}`), [
    'template#1/expression#1/template#1:createReplacementJournal',
  ]);
  validateCall('self-nested-valid.test.js', nestedValid[0]);

  const nestedMissing = scanSource('const child = `outer ${`createReplacementJournal({})`}`;');
  assert.throws(() => validateCall('self-nested-missing.test.js', nestedMissing[0]), /explicitly select a platform/);

  const nestedWin = scanSource('const child = `outer ${`createReplacementJournal({platform:"win32"})`}`;');
  assert.throws(() => validateCall('self-nested-win.test.js', nestedWin[0]), /requires an async seam/);

  const nestedWinValid = scanSource('const child = `outer ${`createReplacementJournal({platform:"win32",windowsAdapter})`}`;');
  validateCall('self-nested-win-valid.test.js', nestedWinValid[0]);

  const difficultExpression = scanSource('const child = `outer ${JSON.stringify({brace:"}",nested:`escaped \\` ${/}/.test("}")}`)} ${`createReplacementJournal({platform:"linux",ownerUid,userData:${JSON.stringify({x:"}"})}})`}`;');
  assert.deepEqual(difficultExpression.map(call => `${call.context}:${call.name}`), [
    'template#1/expression#1/template#2:createReplacementJournal',
  ]);

});


test('allowlisted assert.throws binding is structural and matcher-local', () => {
  function rejected(source) {
    const call = scanSource(source)[0];
    assert(call, 'self-test must contain a constructor');
    assert.throws(() => validateCall('windows-async-credential-journal.test.js', call));
  }
  rejected('assert.throws(/requires shared native broker adapter/, createReplacementJournal({platform:"win32"}))');
  rejected('assert.throws(() => 1, createReplacementJournal({platform:"win32"}), /requires shared native broker adapter/)');
  rejected('assert.throws(() => 1, /requires shared native broker adapter/); createReplacementJournal({platform:"win32"})');
  rejected('/* requires shared native broker adapter */ assert.throws(() => createReplacementJournal({platform:"win32"}), /other/)');
  rejected('assert.throws(() => createReplacementJournal({platform:"win32"}), (error = "requires shared native broker adapter") => false)');
  rejected('assert.throws(() => createReplacementJournal({platform:"win32"}), error => { const expected = "requires shared native broker adapter"; return false; })');

  const valid = scanSource('assert.throws(() => createReplacementJournal({platform:"win32"}), /requires shared native broker adapter/)')[0];
  validateCall('windows-async-credential-journal.test.js', valid);
});

test('credential, replacement-journal, and secret-store fixtures declare host-independent dispatch', () => {
  const files = fs.readdirSync(testsDir).filter(base => base.endsWith('.test.js') && base !== path.basename(__filename)).sort();
  const inventory = [];
  const seenAllowlist = new Set();
  for (const base of files) {
    const source = fs.readFileSync(path.join(testsDir, base), 'utf8');
    for (const call of scanSource(source)) {
      const key = callKey(base, call);
      inventory.push(key);
      validateCall(base, call);
      if (rejectionAllowlist.has(key)) seenAllowlist.add(key);
    }
  }
  assert.deepEqual([...seenAllowlist].sort(), [...rejectionAllowlist].sort(), 'rejection allowlist must contain exactly one live explicit contract');
  assert.deepEqual(inventory.sort(), expectedInventory, 'constructor inventory changed; review dispatch for every added/removed call and update the explicit inventory');
});

test('Windows async fixture suites await journal/store/authority operations', () => {
  for (const base of ['windows-async-credential-journal.test.js', 'windows-async-lineage-matrix.test.js']) {
    const source = fs.readFileSync(path.join(testsDir, base), 'utf8');
    assert.match(source, /\basync\b/, base);
    assert.match(source, /\bawait\b/, base);
  }
  const journal = fs.readFileSync(path.join(testsDir, 'windows-async-credential-journal.test.js'), 'utf8');
  for (const method of ['begin', 'update', 'read', 'markTerminalVerified', 'clear']) {
    assert.match(journal, new RegExp(`await\\s+(?:[^;\\n]+\\.)?${method}\\s*\\(`), `${method} must be awaited`);
  }
});
