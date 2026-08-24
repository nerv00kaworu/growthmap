# Windows R39 candidate checklist

Status: **source candidate only — not packaged, installed, tagged, released, deployed, signed, or published**.

Scope: Windows x64 unsigned-commercial. R17–R24 Linux/VPS Authority rails are historical Linux gates, not Windows sale blockers.

- [x] Exact R39 release-relevant source inventory and SHA-256 pins are closed over workflows, Desktop, frontend, backend, tests, release, and legal metadata.
- [x] Production verification requires a clean committed checkout: `node release/verify-windows-r39-candidate.cjs`.
- [x] Dirty-tree review recomputation is separate and cannot weaken production: `node release/verify-windows-r39-candidate.cjs --review`.
- [x] Normal Windows launch does not start the native replacement broker. Import/restore preflight starts it on demand before stopping the sidecar or mutating files; unavailable native evidence/transaction authority fails only that high-risk operation closed. Pending replacement journals still require native recovery authority before normal writable launch.
- [x] The production chain runs the isolated `dist:win:e2e` + `renderer:e2e` real-main flow before production packaging, then deletes its test distribution. It covers fresh and existing-Free profiles, sidecar/renderer readiness, import/backup/restore authority flow, orderly close, process-tree cleanup, and E2E-source ASAR boundaries.
- [ ] The final NSIS installer must still be installed and accepted on a clean Windows host as an external release gate; this source phase does not claim that test.
- [ ] Production workflow package run, generated artifact hashes, and human distribution approval.

R29 files are retained as superseded history and are not invoked by the R39 production workflow.
