# Current release evidence — 2026-09-02

**Current public release:** [growthmap-personal-v1-renderer-perf-20260902](https://github.com/nerv00kaworu/growthmap/releases/tag/growthmap-personal-v1-renderer-perf-20260902)
**Title:** GrowthMap Personal v1 — Renderer Responsiveness (2026-09-02)

| Item | Evidence |
| --- | --- |
| Installer | `GrowthMap-Setup-0.1.0-desktop.2-x64.exe` |
| Bytes | `145384654` |
| SHA-256 | `1b2075734ed82d2bbec60cdddf65c70d88bdfec5d0a602b0e307324b8a962110` |
| Installer source commit | `8d06f64e01d86f95b1ce361467c68f310718e991` |
| Production-personal CI run | `33621314435` |
| Manifest SHA-256 | `11d510c795f61972703562abae400affaba04362a6830dec9d9840f4ba276dd4` |
| Verification | All production-personal workflow gates passed; Security P0/P1/P2 `0/0/0`; focused `6/6`; frontend `236/236`; stable modules `20/20`; installed-build GUI acceptance completed. |

Renderer responsiveness computes each node’s subtree width once and does not rerun structural layout for selection-only changes, while preserving focus, graph, and relation behavior.

The installer is unsigned and may show **Unknown Publisher** or SmartScreen. Updates are manual. Verify the exact filename, byte size, and SHA-256 before installation. If Windows warns or the hash differs, stop—do not disable or bypass Windows security features.

## Historical release evidence

The 2026-09-01 `growthmap-personal-v1-live-sync-20260901` release was historical evidence for its own artifact: `GrowthMap-Setup-0.1.0-desktop.2-x64.exe`, `145385238` bytes, SHA-256 `cc1a4e15a390b8b56773d531902617ee84c41526c6fedbcfd233b5960ba8b928`, installer source `6702f5815b5f71b996cf87a95eab6e242ed62f5f`, and website deployed source `35634595392f1e75ee64725a2b1d80f735eca185`. It is not the current release.

`RELEASE-MANIFEST.json` is historical authoring.2 evidence only and is not updated or used as current Personal v1 evidence.
