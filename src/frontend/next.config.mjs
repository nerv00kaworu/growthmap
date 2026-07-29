import crypto from "node:crypto";
import path from "node:path";

class StableModuleIdsPlugin {
  constructor(root) { this.root = root; }
  apply(compiler) {
    compiler.hooks.compilation.tap("GrowthMapStableModuleIds", (compilation) => {
      compilation.hooks.beforeModuleIds.tap("GrowthMapStableModuleIds", (modules) => {
        const rawRoot = this.root.split(path.sep).join("/");
        const encodedRoot = encodeURIComponent(rawRoot);
        const rows = [...modules].filter((module) => module.id == null).map((module) => {
          const normalized = module.identifier().split(path.sep).join("/")
            .replaceAll(encodedRoot, "<PROJECT_ROOT>").replaceAll(rawRoot, "<PROJECT_ROOT>");
          return { module, normalized };
        }).sort((a, b) => a.normalized.localeCompare(b.normalized, "en"));
        const used = new Set();
        for (const row of rows) {
          const base = crypto.createHash("sha256").update(row.normalized).digest("hex").slice(0, 16);
          let id = base, suffix = 0;
          while (used.has(id)) id = `${base}-${++suffix}`;
          used.add(id); row.module.id = id;
        }
      });
    });
  }
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  // Static export embeds build and chunk identities in inline RSC bootstrap data.
  // Both must derive only from source-relative inputs for reproducible CSP hashes.
  generateBuildId: async () => "growthmap-static-export-v1",
  webpack: (config) => {
    config.optimization.moduleIds = false;
    config.optimization.chunkIds = "named";
    config.plugins.push(new StableModuleIdsPlugin(process.cwd()));
    return config;
  },
  trailingSlash: true,
  outputFileTracingRoot: path.join(process.cwd(), "..", "..", ".."),
  images: { unoptimized: true },
};

export default nextConfig;
