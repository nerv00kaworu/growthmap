import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

function slash(value) { return String(value).replaceAll("\\", "/").replace(/%5c/gi, "%2F"); }
function windowsRoot(root) { return /^[A-Za-z]:\//.test(root); }
function regexEscape(value) { return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
function encodedEscape(value) {
  return regexEscape(value).replace(/%([0-9A-F])([0-9A-F])/g, (_, a, b) => `%[${a.toLowerCase()}${a.toUpperCase()}][${b.toLowerCase()}${b.toUpperCase()}]`);
}
function compareTotal(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
function rootPatterns(root) {
  // Do not decode caller-controlled identifiers. Match only the exact raw root
  // and its single, standard URI encodings. The component-encoded spelling may
  // mix literal and encoded path separators, as emitted by loader composition.
  const variants = [root, encodeURI(root), encodeURIComponent(root)];
  const component = root.split("/").map((part) => encodedEscape(encodeURIComponent(part)))
    .join("(?:/|%[2][fF]|%[5][cC])");
  return [...new Set([...variants.map(encodedEscape), component])]
    .sort((a, b) => b.length - a.length || compareTotal(a, b));
}
function replaceFilesystemRoot(value) {
  return slash(value).replace(/(^|!)(?:\/|%2f)/gi, (match, prefix, offset, input) =>
    `${prefix}<PROJECT_ROOT>${offset + match.length < input.length ? "/" : ""}`);
}
function replaceRoot(value, root) {
  let out = slash(value);
  for (const source of rootPatterns(root)) {
    const pattern = new RegExp(`${source}(?:\/|%2[fF])|${source}(?=!|$)`, windowsRoot(root) ? "gi" : "g");
    out = out.replace(pattern, (match) => `<PROJECT_ROOT>${/(?:\/|%2f|%5c)$/i.test(match) ? "/" : ""}`);
  }
  return out;
}
export function normalizeModuleIdentifier(identifier, root) {
  const normalizedRoot = slash(root).replace(/\/+$/, "") || "/";
  return normalizedRoot === "/" ? replaceFilesystemRoot(identifier) : replaceRoot(identifier, normalizedRoot);
}
function sha(value) { return crypto.createHash("sha256").update(String(value)).digest("hex"); }
function stableTie(module, normalized, root) {
  const values = [normalized, module.constructor?.name || "", module.type || "", module.layer || "",
    module.resource || "", module.userRequest || "", module.request || "", module.rawRequest || ""];
  return values.map((value) => normalizeModuleIdentifier(value, root)).join("\u0000");
}
function structuralTokens(value) {
  const text = String(value);
  const loaderBasenames = [...text.matchAll(/(?:^|!|[\\/])([A-Za-z0-9_.-]+(?:loader|entry-loader)\.js)(?=[?!|]|$)/gi)]
    .map((match) => match[1].toLowerCase()).sort(compareTotal);
  const queryKeys = [...text.matchAll(/[?&]([A-Za-z][A-Za-z0-9_.-]*)=/g)].map((match) => match[1]).sort(compareTotal);
  let current = text, encodingLevels = 0;
  for (; encodingLevels < 4 && /%25[0-9a-f]{2}/i.test(current); encodingLevels += 1) current = current.replace(/%25/gi, "%");
  return {
    loaderBasenames: [...new Set(loaderBasenames)], queryKeys: [...new Set(queryKeys)], encodingLevels,
    separators: { slash: (text.match(/\//g) || []).length, backslash: (text.match(/\\/g) || []).length,
      encodedSlash: (text.match(/%2f/gi) || []).length, encodedBackslash: (text.match(/%5c/gi) || []).length,
      encodedPercent: (text.match(/%25/gi) || []).length, loaderBoundary: (text.match(/!/g) || []).length },
  };
}
function assertRedacted(normalized, root, field) {
  const lower = normalized.toLowerCase();
  const rootVariants = [slash(root), encodeURI(slash(root)), encodeURIComponent(slash(root))].map((value) => value.toLowerCase());
  const denied = [/[a-z]:[\\/]/i, /[a-z]%3a(?:%2f|%5c)/i,
    /(?:^|[!|"'])\/(?:home|users|runner|a)\//i, /(?:^|%2f)(?:home|users|runner|a)%2f/i];
  // Product and package names are valid module metadata. Privacy is a path
  // property, so reject exact roots and absolute-path forms rather than any
  // occurrence of the word "growthmap".
  if (rootVariants.some((value) => value && lower.includes(value)) || denied.some((pattern) => pattern.test(normalized))) {
    throw new Error(`GrowthMap module identity diagnostic refused: ${field} normalized value retained a private root marker`);
  }
}
export function moduleIdentityReport(module, root, chunkIdentity = "") {
  const fields = {
    identifier: module.identifier?.() || "", readableIdentifier: module.readableIdentifier?.({ shorten: (value) => value }) || "",
    resource: module.resource || "", userRequest: module.userRequest || "", rawRequest: module.rawRequest || "",
    request: module.request || "", context: module.context || "", layer: module.layer || "", type: module.type || "",
    constructor: module.constructor?.name || "", chunkIdentity,
  };
  const report = {};
  for (const [name, raw] of Object.entries(fields)) {
    const normalized = normalizeModuleIdentifier(raw, root);
    assertRedacted(normalized, root, name);
    report[name] = { rawSha256: sha(raw), normalizedSha256: sha(normalized), rawLength: String(raw).length,
      normalizedLength: normalized.length, rootRedactionCount: (normalized.match(/<PROJECT_ROOT>/g) || []).length,
      structure: structuralTokens(raw) };
  }
  report.hashInput = { normalizedIdentifierSha256: sha(normalizeModuleIdentifier(fields.identifier, root)),
    stableIdPrefix: sha(normalizeModuleIdentifier(fields.identifier, root)).slice(0, 16) };
  return report;
}
function writeDiagnostics(rows, root, destination) {
  const selected = rows.filter(({ module, useIdentity }) => /next-flight-client-entry-loader\.js/i.test(module.identifier?.() || "")
    && useIdentity.split("\u0000").includes("app/page"));
  if (selected.length !== 1) throw new Error(`GrowthMap module identity diagnostic refused: expected one app/page entry, found ${selected.length}`);
  const payload = { schema: 1, modules: selected.map(({ module, useIdentity }) => moduleIdentityReport(module, root, useIdentity)) };
  const resolved = path.resolve(destination);
  fs.mkdirSync(path.dirname(resolved), { recursive: true });
  fs.writeFileSync(resolved, `${JSON.stringify(payload, null, 2)}\n`);
}
export function assignStableModuleIds(modules, root, access = {}) {
  const get = access.get || ((module) => module.id);
  const set = access.set || ((module, id) => { module.id = id; });
  const identity = access.identity || (() => "");
  const all = [...modules];
  const used = new Set(all.map(get).filter((id) => id != null).map(String));
  const rows = all.filter((module) => get(module) == null && module.type !== "runtime" && !module.identifier().startsWith("webpack/runtime/")).map((module) => {
    const normalized = normalizeModuleIdentifier(module.identifier(), root);
    const tie = stableTie(module, normalized, root);
    const useIdentity = normalizeModuleIdentifier(identity(module), root);
    return { module, normalized, tie, useIdentity };
  }).sort((a, b) => compareTotal(a.normalized, b.normalized) || compareTotal(a.tie, b.tie) || compareTotal(a.useIdentity, b.useIdentity));
  for (let index = 1; index < rows.length; index += 1) {
    const a = rows[index - 1], b = rows[index];
    if (a.normalized === b.normalized && a.tie === b.tie && a.useIdentity === b.useIdentity)
      throw new Error(`GrowthMap deterministic module IDs: indistinguishable collision for ${a.normalized}`);
  }
  for (const row of rows) {
    const base = sha(row.normalized).slice(0, 16);
    let id = base;
    for (let suffix = 1; used.has(String(id)); suffix += 1) id = `${base}-${suffix}`;
    used.add(String(id)); set(row.module, id);
  }
  if (access.diagnosticPath) writeDiagnostics(rows, root, access.diagnosticPath);
}

export class StableModuleIdsPlugin {
  constructor(root) { this.root = root; }
  apply(compiler) {
    compiler.hooks.compilation.tap("GrowthMapStableModuleIds", (compilation) => {
      compilation.hooks.beforeModuleIds.tap("GrowthMapStableModuleIds", (modules) => {
        assignStableModuleIds(modules, this.root, {
          get: (module) => compilation.chunkGraph.getModuleId(module), set: (module, id) => compilation.chunkGraph.setModuleId(module, id),
          identity: (module) => [...compilation.chunkGraph.getModuleChunksIterable(module)]
            .map((chunk) => chunk.name || chunk.id || "").sort(compareTotal).join("\u0000"),
          // Next invokes this plugin for more than one compiler. Only the client
          // graph emits the public app/page module whose ID drives this gate.
          diagnosticPath: compiler.options?.name === "client" ? (process.env.GROWTHMAP_MODULE_IDENTITY_REPORT || "") : "",
        });
      });
    });
  }
}
