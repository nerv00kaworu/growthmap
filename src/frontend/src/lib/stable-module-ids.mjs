import crypto from "node:crypto";

function slash(value) { return String(value).replaceAll("\\", "/"); }
function windowsRoot(root) { return /^[A-Za-z]:\//.test(root); }
function regexEscape(value) { return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
function encodedEscape(value) {
  return regexEscape(value).replace(/%([0-9A-F])([0-9A-F])/g, (_, a, b) => `%[${a.toLowerCase()}${a.toUpperCase()}][${b.toLowerCase()}${b.toUpperCase()}]`);
}
function rootPatterns(root) {
  // Do not decode caller-controlled identifiers. Match only the exact raw root
  // and its single, standard URI encodings. The component-encoded spelling may
  // mix literal and encoded path separators, as emitted by loader composition.
  const variants = [root, encodeURI(root), encodeURIComponent(root)];
  const component = root.split("/").map((part) => encodedEscape(encodeURIComponent(part)))
    .join("(?:/|%[2][fF])");
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
export function normalizeModuleIdentifier(identifier, root) {
  const normalizedRoot = slash(root).replace(/\/+$/, "") || "/";
  return normalizedRoot === "/"
    ? replaceFilesystemRoot(identifier)
    : replaceRoot(identifier, normalizedRoot);
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
