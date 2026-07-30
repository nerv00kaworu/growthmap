import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const SUFFIX = "_client-reference-manifest.js";
const CONTRACT_FILE = "growthmap-client-reference-boundary.json";
function compareTotal(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
function digest(value) { return crypto.createHash("sha256").update(value).digest("hex"); }

export function normalizeChunkPairs(chunks) {
  if (!Array.isArray(chunks) || chunks.length % 2 !== 0 || chunks.some((item) => typeof item !== "string")) {
    throw new Error("GrowthMap manifest boundary: chunks must be string id/file pairs");
  }
  const pairs = [];
  for (let index = 0; index < chunks.length; index += 2) pairs.push([chunks[index], chunks[index + 1]]);
  pairs.sort((a, b) => compareTotal(a[0], b[0]) || compareTotal(a[1], b[1]));
  return pairs.flat();
}

function normalizeManifest(value) {
  if (!value || typeof value !== "object") return;
  if (Array.isArray(value)) {
    for (const item of value) normalizeManifest(item);
    return;
  }
  for (const [key, child] of Object.entries(value)) {
    if (key === "chunks") value[key] = normalizeChunkPairs(child);
    else normalizeManifest(child);
  }
}

export function normalizeClientReferenceManifest(source) {
  const marker = "]=", offset = source.indexOf(marker);
  if (offset < 0) throw new Error("GrowthMap manifest boundary: assignment marker is missing");
  const jsonOffset = offset + marker.length;
  const manifest = JSON.parse(source.slice(jsonOffset));
  normalizeManifest(manifest);
  return `${source.slice(0, jsonOffset)}${JSON.stringify(manifest)}`;
}

export class ClientReferenceManifestBoundaryPlugin {
  apply(compiler) {
    compiler.hooks.afterEmit.tap("GrowthMapClientReferenceManifestBoundary", (compilation) => {
      const outputPath = compilation.outputOptions.path;
      if (!outputPath) throw new Error("GrowthMap manifest boundary: webpack output path is missing");
      const records = [];
      for (const asset of compilation.getAssets()) {
        if (!asset.name.endsWith(SUFFIX)) continue;
        const absolute = path.join(outputPath, ...asset.name.split("/"));
        const before = fs.readFileSync(absolute, "utf8");
        const normalized = normalizeClientReferenceManifest(before);
        // afterEmit is the durable boundary consumed by Next's static renderer:
        // update the emitted file, not an earlier in-memory traversal.
        if (normalized !== before) fs.writeFileSync(absolute, normalized, "utf8");
        records.push({ asset: asset.name, sha256: digest(normalized) });
      }
      if (!records.length) throw new Error("GrowthMap manifest boundary: client compiler emitted no client-reference manifest");
      records.sort((a, b) => compareTotal(a.asset, b.asset));
      fs.writeFileSync(path.join(outputPath, CONTRACT_FILE), `${JSON.stringify({ version: 1, compiler: "client", files: records }, null, 2)}\n`, "utf8");
    });
  }
}
