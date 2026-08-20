# Windows R29 candidate checklist

Status: **candidate only — not tagged, released, deployed, signed, or published**.

Scope: Windows x64, unsigned-commercial. Linux sidecar packaging is explicitly outside this release gate; the Windows `.exe` sidecar and MCP resources remain package gates.

- [x] Source baseline identifies the reviewed commit plus candidate delta.
- [x] Frontend full dependency graph audit is zero.
- [x] Desktop full dependency graph audit is zero.
- [x] Release-relevant GitHub Actions use full commit SHA pins with version comments.
- [x] ASAR verifiers use the repository lockfile-resolved executable and fail closed on absence/version mismatch.
- [ ] Windows R29 workflow run and unsigned installer hashes recorded (requires an intentional candidate build; no release claimed here).
- [ ] Human review/approval for distribution.

Verify committed-file integrity declarations with `node release/verify-windows-r29-candidate.cjs`. The generated installer manifest is produced by `verify-production-unsigned-package.ps1` and hashes the installer, ASAR, Windows sidecar, and MCP bytes directly.

`RELEASE-MANIFEST.json` describes superseded authoring.2 provenance only and is not Windows R29 provenance.
