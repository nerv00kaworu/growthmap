import crypto from "node:crypto";

// Webpack/Next loader queries URI-encode native Windows separators before this
// compiler boundary sees them. Canonicalize both raw and encoded separators
// without decoding any other request/query content.
function slash(value) { return String(value).replaceAll("\\", "/").replace(/%(?:5c|2f)/gi, "/"); }
function windowsRoot(root) { return /^[A-Za-z]:\//.test(root); }
function regexEscape(value) { return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
function encodedEscape(value) {
  return regexEscape(value).replace(/%([0-9A-F])([0-9A-F])/g, (_, a, b) => `%[${a.toLowerCase()}${a.toUpperCase()}][${b.toLowerCase()}${b.toUpperCase()}]`);
}
function rootPatterns(root) {
  // Do not decode caller-controlled identifiers. Match only exact component
  // spellings and single standard URI encodings. Windows loaders may preserve
  // the drive colon while encoding only separators (D:%5Ca...), so each path
  // component needs its own raw/encodeURI/encodeURIComponent alternatives.
  const variants = [root, encodeURI(root), encodeURIComponent(root)];
  const component = root.split("/").map((part) => {
    const forms = [...new Set([part, encodeURI(part), encodeURIComponent(part)])]
      .map(encodedEscape).sort((a, b) => b.length - a.length || compareTotal(a, b));
    return forms.length === 1 ? forms[0] : `(?:${forms.join("|")})`;
  }).join("(?:/|%[2][fF])");
  return [...new Set([...variants.map(encodedEscape), component])]
    .sort((a, b) => b.length - a.length || compareTotal(a, b));
}
function replaceFilesystemRoot(value) {
  // A filesystem root is itself the separator, so treating it like an ordinary
  // root would either compile an empty pattern or redact every slash. Limit it
  // to absolute path starts (including starts of loader-chain segments).
  return slash(value).replace(/(^|!)(?:\/|%2f)/gi, (match, prefix, offset, input) =>
    `${prefix}<PROJECT_ROOT>${offset + match.length < input.length ? "/" : ""}`);
}
function replaceRoot(value, root) {
  let out = slash(value);
  for (const source of rootPatterns(root)) {
    // Consume and canonicalize a real child separator. A literal `!` is the
    // preserved boundary after a complete loader-chain segment. The lookahead
    // prevents lexical-prefix redaction while retaining exact-root matches.
    const pattern = new RegExp(`${source}(?:\/|%2[fF])|${source}(?=!|$)`, windowsRoot(root) ? "gi" : "g");
    out = out.replace(pattern, (match) => `<PROJECT_ROOT>${/(?:\/|%2f)$/i.test(match) ? "/" : ""}`);
  }
  return out;
}
function decodeQueryComponentOnce(value) {
  if (/%(?![0-9a-f]{2})/i.test(value)) return null;
  try { return decodeURIComponent(value.replaceAll("+", " ")); } catch { return null; }
}
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
  return [...canonicalModules.map((value) => `modules=${encodeURIComponent(value)}`),
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
  const raw = /^next-flight-client-entry-loader\?([^!|]+)!$/.exec(input);
  if (!raw) return input;
  const canonical = canonicalFlightQuery(raw[1], root);
  return canonical === null ? input : `next-flight-client-entry-loader?${canonical}!`;
}
export function normalizeModuleIdentifier(identifier, root) {
  const normalizedRoot = slash(root).replace(/\/+$/, "") || "/";
  const structured = canonicalizeNextFlightEntryIdentifier(identifier, normalizedRoot);
  return normalizedRoot === "/"
    ? replaceFilesystemRoot(structured)
    : replaceRoot(structured, normalizedRoot);
}
function compareTotal(a, b) {
  // JS relational string comparison is a total UTF-16 code-unit order: unlike
  // locale collation, distinct NFC/NFD strings can never compare equal.
  return a < b ? -1 : a > b ? 1 : 0;
}
function stableTie(module, normalized, root) {
  const values = [normalized, module.constructor?.name || "", module.type || "", module.layer || "",
    module.resource || "", module.userRequest || "", module.request || "", module.rawRequest || ""];
  return values.map((value) => normalizeModuleIdentifier(value, root)).join("\u0000");
}
export function assignStableModuleIds(modules, root, access = {}) {
  const get = access.get || ((module) => module.id);
  const set = access.set || ((module, id) => { module.id = id; });
  const identity = access.identity || (() => "");
  const all = [...modules];
  const used = new Set(all.map(get).filter((id) => id != null).map(String));
  // RuntimeModules are chunk-scoped bootstrap fragments, not addressable module
  // graph entries; webpack does not require or serialize module IDs for them.
  const rows = all.filter((module) => get(module) == null && module.type !== "runtime" && !module.identifier().startsWith("webpack/runtime/")).map((module) => {
    const normalized = normalizeModuleIdentifier(module.identifier(), root);
    const tie = stableTie(module, normalized, root);
    const useIdentity = normalizeModuleIdentifier(identity(module), root);
    return { module, normalized, tie, useIdentity };
  }).sort((a, b) => compareTotal(a.normalized, b.normalized) || compareTotal(a.tie, b.tie) || compareTotal(a.useIdentity, b.useIdentity));
  for (let index = 1; index < rows.length; index += 1) {
    const a = rows[index - 1], b = rows[index];
    if (a.normalized === b.normalized && a.tie === b.tie && a.useIdentity === b.useIdentity) {
      throw new Error(`GrowthMap deterministic module IDs: indistinguishable collision for ${a.normalized}`);
    }
  }
  for (const row of rows) {
    const base = crypto.createHash("sha256").update(row.normalized).digest("hex").slice(0, 16);
    let id = base;
    for (let suffix = 1; used.has(String(id)); suffix += 1) id = `${base}-${suffix}`;
    used.add(String(id)); set(row.module, id);
  }
}

function chunkKey(chunk) {
  return [chunk.name || "", chunk.id == null ? "" : String(chunk.id)].join("\u0000");
}
export function compareChunks(a, b) { return compareTotal(chunkKey(a), chunkKey(b)); }
export function stabilizeChunkGroups(chunkGroups) {
  for (const group of chunkGroups) group.chunks.sort(compareChunks);
}

export function stabilizeChunkTraversal(compilation) {
  // Next reads entrypoint chunk/file iterables while creating its client-reference
  // manifest at PROCESS_ASSETS_STAGE_ANALYSE. Normalize those public iterables at
  // the immediately preceding stage, after webpack has assigned chunk names/files.
  stabilizeChunkGroups(compilation.chunkGroups);
  stabilizeChunkGroups(compilation.entrypoints.values());
  for (const chunk of compilation.chunks) {
    const files = [...chunk.files].sort(compareTotal);
    chunk.files.clear();
    for (const file of files) chunk.files.add(file);
  }
}

export class StableModuleIdsPlugin {
  constructor(root) { this.root = root; }
  apply(compiler) {
    compiler.hooks.compilation.tap("GrowthMapStableModuleIds", (compilation) => {
      compilation.hooks.beforeModuleIds.tap("GrowthMapStableModuleIds", (modules) => {
        // Webpack 5's ChunkGraph API is the supported module-ID interface.
        assignStableModuleIds(modules, this.root, {
          get: (module) => compilation.chunkGraph.getModuleId(module),
          set: (module, id) => compilation.chunkGraph.setModuleId(module, id),
          // Named chunk membership is webpack-supported persistent use identity;
          // sort it so iterable order cannot affect suffix allocation.
          identity: (module) => [...compilation.chunkGraph.getModuleChunksIterable(module)]
            .map((chunk) => chunk.name || chunk.id || "")
            .sort(compareTotal).join("\u0000"),
        });
      });
      compilation.hooks.processAssets.tap(
        { name: "GrowthMapStableChunkTraversal", stage: compiler.webpack.Compilation.PROCESS_ASSETS_STAGE_ANALYSE - 1 },
        () => stabilizeChunkTraversal(compilation),
      );
    });
  }
}
