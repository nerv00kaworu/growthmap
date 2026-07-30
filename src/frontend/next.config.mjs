import path from "node:path";
import { StableModuleIdsPlugin } from "./src/lib/stable-module-ids.mjs";

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
