import crypto from "node:crypto";

function slash(value) { return String(value).replaceAll("\\", "/"); }
function decodeVariants(value) {
  const variants = new Set([value]);
  try { variants.add(decodeURIComponent(value)); } catch { /* malformed escapes stay literal */ }
  return [...variants];
}
function windowsRoot(root) { return /^[A-Za-z]:\//.test(root); }
function replaceRoot(value, root) {
  const flags = windowsRoot(root) ? "gi" : "g";
  const roots = new Set();
  for (const variant of decodeVariants(slash(root))) {
    roots.add(variant);
    roots.add(encodeURIComponent(variant));
    roots.add(encodeURI(variant));
  }
  let out = slash(value);
  for (const candidate of [...roots].sort((a, b) => b.length - a.length)) {
    out = out.replace(new RegExp(candidate.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), flags), "<PROJECT_ROOT>");
  }
  return out;
}
export function normalizeModuleIdentifier(identifier, root) {
  return replaceRoot(identifier, slash(root).replace(/\/$/, ""));
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
  }).sort((a, b) => a.normalized.localeCompare(b.normalized, "en") || a.tie.localeCompare(b.tie, "en") || a.useIdentity.localeCompare(b.useIdentity, "en"));
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
            .sort((a, b) => String(a).localeCompare(String(b), "en")).join("\u0000"),
        });
      });
    });
  }
}
