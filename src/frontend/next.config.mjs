import path from "node:path";
import { StableModuleIdsPlugin } from "./src/lib/stable-module-ids.mjs";
import { ClientReferenceManifestBoundaryPlugin } from "./src/lib/client-reference-manifest-boundary.mjs";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  // Static export embeds build and chunk identities in inline RSC bootstrap data.
  // Both must derive only from source-relative inputs for reproducible CSP hashes.
  generateBuildId: async () => "growthmap-static-export-v1",
  webpack: (config, { isServer, nextRuntime }) => {
    config.optimization.moduleIds = false;
    config.optimization.chunkIds = "named";
    config.plugins.push(new StableModuleIdsPlugin(process.cwd()));
    // Next 15.5.21's ClientReferenceManifestPlugin runs only in the client
    // compiler. Its emitted .next/server/app artifact is what static export
    // evaluates; server/edge compiler hooks cannot control that durable file.
    if (!isServer && nextRuntime === undefined) {
      config.plugins.push(new ClientReferenceManifestBoundaryPlugin());
    }
    return config;
  },
  trailingSlash: true,
  outputFileTracingRoot: path.join(process.cwd(), "..", "..", ".."),
  images: { unoptimized: true },
};

export default nextConfig;
