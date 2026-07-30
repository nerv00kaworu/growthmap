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
function decodeQueryComponentOnce(value) {
  if (/%(?![0-9a-f]{2})/i.test(value)) return null;
  try { return decodeURIComponent(value.replaceAll("+", " ")); } catch { return null; }
}
function encodeQueryComponent(value) { return encodeURIComponent(value); }
function rootRelativePath(value, root) {
  const candidate = slash(value), normalizedRoot = slash(root).replace(/\/+$/, "") || "/";
  const insensitive = windowsRoot(normalizedRoot);
  const left = insensitive ? candidate.toLowerCase() : candidate;
  const right = insensitive ? normalizedRoot.toLowerCase() : normalizedRoot;
  if (left === right) return "";
  if (!left.startsWith(`${right}/`)) return null;
  return candidate.slice(normalizedRoot.length + 1);
}
function canonicalModuleOption(value, root) {
  let parsed;
  try { parsed = JSON.parse(value); } catch { return null; }
  if (!parsed || Object.getPrototypeOf(parsed) !== Object.prototype
    || Object.keys(parsed).some((key) => key !== "request" && key !== "ids")
    || typeof parsed.request !== "string" || !Array.isArray(parsed.ids)
    || parsed.ids.some((id) => typeof id !== "string")) return null;
  const relative = rootRelativePath(parsed.request, root);
  if (relative !== null) parsed.request = `<PROJECT_ROOT>${relative ? `/${relative}` : ""}`;
  return JSON.stringify({ request: parsed.request, ids: parsed.ids });
}
function canonicalFlightQuery(query, root) {
  if (!query || query.includes("#")) return null;
  const entries = [];
  for (const pair of query.split("&")) {
    const separator = pair.indexOf("=");
    if (separator < 1) return null;
    const key = decodeQueryComponentOnce(pair.slice(0, separator));
    const value = decodeQueryComponentOnce(pair.slice(separator + 1));
    if (key === null || value === null || (key !== "modules" && key !== "server")) return null;
    entries.push([key, value]);
  }
  const modules = entries.filter(([key]) => key === "modules");
  const servers = entries.filter(([key]) => key === "server");
  if (!modules.length || servers.length !== 1 || !/^(?:true|false)$/.test(servers[0][1])) return null;
  const canonicalModules = modules.map(([, value]) => canonicalModuleOption(value, root));
  if (canonicalModules.some((value) => value === null)) return null;
  return [...canonicalModules.map((value) => `modules=${encodeQueryComponent(value)}`),
    `server=${servers[0][1]}`].join("&");
}
/** Canonicalize only Next 15.5's exact flight client entry loader option schema. */
export function canonicalizeNextFlightEntryIdentifier(identifier, root) {
  const input = String(identifier);
  const loader = /(^|[!|])((?:[^?!|]*[\\/])?next-flight-client-entry-loader\.js)\?([^!|]+)(?=!)/gi;
  let found = false, failed = false;
  const output = input.replace(loader, (whole, boundary, loaderPath, query) => {
    found = true;
    const canonical = canonicalFlightQuery(query, root);
    if (canonical === null) { failed = true; return whole; }
    return `${boundary}${loaderPath}?${canonical}`;
  });
  if (failed) return input;
  if (found) return output;
  // webpack's rawRequest omits the loader basename, but retains its complete,
  // loader-terminated options request. Accept only that exact closed schema.
  const bare = /^(?:\?|)([^!|]+)!$/.exec(input);
  if (!bare) return input;
  const canonical = canonicalFlightQuery(bare[1], root);
  return canonical === null ? input : `${canonical}!`;
}
export function normalizeModuleIdentifier(identifier, root) {
  const normalizedRoot = slash(root).replace(/\/+$/, "") || "/";
  const structured = canonicalizeNextFlightEntryIdentifier(identifier, normalizedRoot);
  return normalizedRoot === "/" ? replaceFilesystemRoot(structured) : replaceRoot(structured, normalizedRoot);
}
function sha(value) { return crypto.createHash("sha256").update(String(value)).digest("hex"); }
function stableTie(module, normalized, root) {
  const values = [normalized, module.constructor?.name || "", module.type || "", module.layer || "",
    module.resource || "", module.userRequest || "", module.request || "", module.rawRequest || ""];
  return values.map((value) => normalizeModuleIdentifier(value, root)).join("\u0000");
}
const SAFE_LOADERS = new Set(["entry-loader.js", "next-flight-client-entry-loader.js"]);
const SAFE_QUERY_KEYS = new Set(["modules", "server"]);
function boundedTokens(values, allowlist) {
  const safe = values.slice(0, 16).map((value) => allowlist.has(value.toLowerCase()) ? value.toLowerCase() : "other");
  return { values: [...new Set(safe)], count: values.length, truncated: values.length > 16 };
}
function structuralTokens(value) {
  const text = String(value);
  const loaders = [...text.matchAll(/(?:^|!|[\\/])([A-Za-z0-9_.-]+(?:loader|entry-loader)\.js)(?=[?!|]|$)/gi)]
    .map((match) => match[1]).sort(compareTotal);
  const queries = [...text.matchAll(/[?&]([A-Za-z][A-Za-z0-9_.-]*)=/g)].map((match) => match[1]).sort(compareTotal);
  let current = text, encodingLevels = 0;
  for (; encodingLevels < 4 && /%25[0-9a-f]{2}/i.test(current); encodingLevels += 1) current = current.replace(/%25/gi, "%");
  const loaderTokens = boundedTokens(loaders, SAFE_LOADERS), queryTokens = boundedTokens(queries, SAFE_QUERY_KEYS);
  return {
    loaderBasenames: loaderTokens.values, loaderBasenameCount: loaderTokens.count, loaderBasenamesTruncated: loaderTokens.truncated,
    queryKeys: queryTokens.values, queryKeyCount: queryTokens.count, queryKeysTruncated: queryTokens.truncated, encodingLevels,
    separators: { slash: (text.match(/\//g) || []).length, backslash: (text.match(/\\/g) || []).length,
      encodedSlash: (text.match(/%2f/gi) || []).length, encodedBackslash: (text.match(/%5c/gi) || []).length,
      encodedPercent: (text.match(/%25/gi) || []).length, loaderBoundary: (text.match(/!/g) || []).length },
  };
}
const FIELD_NAMES = ["identifier", "readableIdentifier", "resource", "userRequest", "rawRequest", "request", "context", "layer", "type", "constructor", "chunkIdentity"];
function denialReason(normalized, root) {
  const lower = String(normalized).toLowerCase();
  const normalizedRoot = slash(root).replace(/\/+$/, "").toLowerCase();
  const rawRoots = [normalizedRoot, encodeURI(normalizedRoot)].filter(Boolean);
  const encodedRoots = [encodeURIComponent(normalizedRoot)].filter(Boolean);
  if (/[a-z]:[\\/]/i.test(normalized)) return "drive";
  if (rawRoots.some((value) => lower.includes(value)) || /(?:^|[!|"'])\/(?:home|users|runner|a)\//i.test(normalized)) return "raw-root";
  if (encodedRoots.some((value) => lower.includes(value.toLowerCase())) || /(?:^|%2f)(?:home|users|runner|a)%2f/i.test(normalized)
    || /[a-z]%3a(?:%2f|%5c)/i.test(normalized)) return "encoded-root";
  if (/growthmap/i.test(normalized)) return "project-marker";
  return null;
}
function fieldReport(raw, root) {
  const normalized = normalizeModuleIdentifier(raw, root);
  return {
    metadata: { rawSha256: sha(raw), normalizedSha256: sha(normalized), rawLength: String(raw).length,
      normalizedLength: normalized.length, rootRedactionCount: (normalized.match(/<PROJECT_ROOT>/g) || []).length,
      structure: structuralTokens(raw) },
    reason: denialReason(normalized, root),
  };
}
function diagnosticFields(module, root, chunkIdentity) {
  const fields = {
    identifier: module.identifier?.() || "",
    readableIdentifier: module.readableIdentifier?.({ shorten: (value) => normalizeModuleIdentifier(value, root) }) || "",
    resource: module.resource || "", userRequest: module.userRequest || "", rawRequest: module.rawRequest || "",
    request: module.request || "", context: module.context || "", layer: module.layer || "", type: module.type || "",
    constructor: module.constructor?.name || "", chunkIdentity,
  };
  return Object.fromEntries(FIELD_NAMES.map((name) => [name, fieldReport(fields[name], root)]));
}
function refusalError(field, result) {
  return new Error(`Module identity diagnostic refused: ${JSON.stringify({ field, denialReason: result.reason, ...result.metadata })}`);
}
export function moduleIdentityReport(module, root, chunkIdentity = "") {
  const bounded = diagnosticFields(module, root, chunkIdentity);
  const unsafe = FIELD_NAMES.find((name) => bounded[name].reason);
  if (unsafe) throw refusalError(unsafe, bounded[unsafe]);
  const report = Object.fromEntries(FIELD_NAMES.map((name) => [name, bounded[name].metadata]));
  report.hashInput = { normalizedIdentifierSha256: report.identifier.normalizedSha256,
    stableIdPrefix: report.identifier.normalizedSha256.slice(0, 16) };
  return report;
}
function writeJson(destination, payload) {
  const resolved = path.resolve(destination);
  fs.mkdirSync(path.dirname(resolved), { recursive: true });
  fs.writeFileSync(resolved, `${JSON.stringify(payload, null, 2)}\n`);
}
function writeDiagnostics(rows, root, destination) {
  const selected = rows.filter(({ module, useIdentity }) => /next-flight-client-entry-loader\.js/i.test(module.identifier?.() || "")
    && useIdentity.split("\u0000").includes("app/page"));
  if (selected.length !== 1) throw new Error(`Module identity diagnostic refused: selection-count=${selected.length}`);
  const reports = selected.map(({ module, useIdentity }) => diagnosticFields(module, root, useIdentity));
  const denials = reports.flatMap((fields, moduleIndex) => FIELD_NAMES.filter((field) => fields[field].reason)
    .map((field) => ({ moduleIndex, field, denialReason: fields[field].reason })));
  if (denials.length) {
    writeJson(destination, { schema: 2, status: "refused", fields: reports.map((fields) =>
      Object.fromEntries(FIELD_NAMES.map((name) => [name, fields[name].metadata]))), denials });
    const first = denials[0];
    throw refusalError(first.field, reports[first.moduleIndex][first.field]);
  }
  writeJson(destination, { schema: 1, modules: reports.map((fields) => {
    const report = Object.fromEntries(FIELD_NAMES.map((name) => [name, fields[name].metadata]));
    report.hashInput = { normalizedIdentifierSha256: report.identifier.normalizedSha256,
      stableIdPrefix: report.identifier.normalizedSha256.slice(0, 16) };
    return report;
  }) });
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
