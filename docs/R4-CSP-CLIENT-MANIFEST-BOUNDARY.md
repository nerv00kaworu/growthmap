# R4 CSP client-reference manifest boundary

## Pinned upstream provenance

The frontend lockfile pins `next@15.5.21` from `next-15.5.21.tgz` with npm integrity
`sha512-/TsdBtkWLhkl+NVL3Uqws2UphNd6IPzOtzSk1fHaf+0P7GQKLZDUytyhns/Ykbzdy9+YRjwG7ONvrHaaTDdFqQ==`.
The following statements were traced against that installed source.

## Producer and consumer

* `next/dist/build/webpack-config.js` installs `ClientReferenceManifestPlugin` only when
  `isClient` is true. This is the **client webpack compiler**, not the server or edge
  compiler.
* `next/dist/build/webpack/plugins/flight-manifest-plugin.js` creates each manifest at
  `PROCESS_ASSETS_STAGE_ANALYSE` and emits
  `server/app/<route>_client-reference-manifest.js`. The resulting durable path is
  `.next/server/app/<route>_client-reference-manifest.js`, despite being produced by
  the client compiler.
* `next/dist/server/load-components.js` loads exactly that path with
  `evalManifestWithRetries`, selects `globalThis.__RSC_MANIFEST[entryName]`, and passes
  it as `clientReferenceManifest` to app rendering. Static generation/export then
  serializes React Flight references from this value into inline RSC bootstrap data in
  `out/*.html`.

The earlier attempts changed webpack chunk/group iteration or rewrote an in-memory
asset at another `processAssets` stage. They did not establish or verify control of the
post-emit file that `load-components.js` evaluates. In particular, the filesystem path
looks like server output even though ownership is the client compiler, so applying the
same plugin indiscriminately to all compiler callbacks obscured which compilation was
relevant. Build output proved those changes could produce a different ordering while
remaining platform-divergent.

## Owned boundary and contract

`ClientReferenceManifestBoundaryPlugin` is attached only to the client compiler. At
`afterEmit` it normalizes complete chunk-id/file pairs in the emitted manifest using
ordinal string ordering, writes the durable artifact, and records each artifact hash in
`.next/growthmap-client-reference-boundary.json`.

The build contract then:

1. verifies every recorded hash still matches the durable file after Next finishes;
2. parses `.next/server/app/page_client-reference-manifest.js`; and
3. proves `out/index.html` contains a byte-for-byte chunk tuple from that manifest.

This proves the correction hits the artifact consumed by static export, rather than
only exercising a normalization helper. Exported HTML is never postprocessed.
