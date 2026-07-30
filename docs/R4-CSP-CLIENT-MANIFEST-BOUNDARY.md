# R4 CSP client-reference render boundary

## Pinned upstream provenance

The frontend lockfile pins `next@15.5.21` from `next-15.5.21.tgz` with npm integrity
`sha512-/TsdBtkWLhkl+NVL3Uqws2UphNd6IPzOtzSk1fHaf+0P7GQKLZDUytyhns/Ykbzdy9+YRjwG7ONvrHaaTDdFqQ==`.
`postinstall` additionally requires the pristine target source SHA-256
`0ba3db12307085b9eb3f942b2f5eadad9dca46fb98516d28cbfe2d561cf9240b` and the exact
patched SHA-256. Version, registry integrity, source, anchor, and output therefore fail
closed on upstream drift.

## Complete producer-to-serializer dataflow

1. `next/dist/build/webpack/plugins/flight-manifest-plugin.js` installs
   `ClientReferenceManifestPlugin` on the client compiler at
   `PROCESS_ASSETS_STAGE_ANALYSE`.
2. `createAsset()` calls `getAppPathRequiredChunks(entrypoint, rootMainFiles)`. This is
   where the complete alternating `[chunkId, emittedFile, ...]` array is formed in
   memory. The same `requiredChunks` array is assigned to each client module recorded
   for that entrypoint. Group manifests are merged and immediately `JSON.stringify`'d,
   then emitted as `server/app/<page>_client-reference-manifest.js`.
3. `next/dist/server/load-components.js` calls `evalManifestWithRetries()` on that file,
   selects `context.__RSC_MANIFEST[entryName]`, and returns it as
   `clientReferenceManifest` before app rendering.
4. Static generation passes this object to React's Flight renderer. When it serializes a
   client reference, React reads that module entry's `chunks` array and emits the
   `I[<module id>,<complete chunks>,<export>]` row. Next writes those Flight rows through
   `self.__next_f.push(...)` bootstrap scripts in `out/index.html` (the target page row is
   in script #9 in this pinned build).

The previous after-emit contract was invalid: rewriting the durable file does not prove
that no renderer had already loaded or retained the object created from the original
asset. Finding any tuple in HTML was also weak evidence because most tuples were shared
between both orders.

## Fix at the actual producer boundary

The version-pinned npm patch sorts pairs inside `getAppPathRequiredChunks()` before
`requiredChunks` is attached to manifest entries, before `JSON.stringify`, before load
or cache, and before Flight serialization. It never postprocesses exported HTML.

Ordering is ordinal by **emitted file first**, then chunk id as a total-order tie-breaker.
Pairs remain intact. Webpack can expose a chunk whose `id` string is empty while its
`static/chunks/app/page-*.js` file is non-empty. Sorting by file explains and fixes the
required position: `static/chunks/1a258343-*` sorts first, the empty-id
`static/chunks/app/page-*` pair second, and `static/chunks/vendors-*` third. Empty id is
not treated as a missing pair and cannot become detached from its file. This comparison
uses JavaScript ordinal string operators and is independent of locale and path separator.

## Strong contract

`verify-client-reference-boundary.js` evaluates the normalized page manifest, selects the
single client module with id `c546470e5ca77f8d`, parses script #9 Flight `I` rows, selects
that module's `default` export, and requires its **entire chunks array** to equal the
normalized manifest entry. Its test includes a stale-cache simulation where one tuple
still matches but full ordering differs; that case must fail.
