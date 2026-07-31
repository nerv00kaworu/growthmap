# GrowthMap promote-mainline P1 remediation — 2026-07-31

Status: **remediation_complete_pending_rereview**
Baseline: `ad3b3705f6c028aba0e4ede43bd777939549c840`

## Remediation

Frontend promotion now derives the exact coupled node-ID set from the persisted endpoints of the target edge plus only the mainline siblings actually demoted. It requires `touched_node_revisions` to have exactly those keys and each value to equal the pre-request cached node revision. Missing cached endpoint state, malformed authoritative fields, or any in-flight project/edge/node snapshot change throws stable `MALFORMED_AUTHORITATIVE_RESPONSE`, invalidates the coupled project, target/demoted edges, and endpoint nodes, and returns no row. Valid responses atomically advance project/edge cache while retaining endpoint node revisions.

Focused coverage includes empty/missing/extra/wrong endpoint IDs, wrong positive revisions, unavailable cached nodes, in-flight node changes, exact valid maps, sequential promotion, unchanged 409 state, and the store caller not consuming malformed results.

## Verification

- Frontend focused: 13 passed.
- Frontend all TS/node: 53 + 28 passed.
- Frontend lint/typecheck: PASS.
- Clean production build, client-reference boundary, CSP generation: PASS.
- Three distinct clean roots: byte-identical; CSP SHA-256 `a885703731ac3a76c6810558d053dd4f0220ae43905fe86761984bfca35470dd`.
- Physical exported frontend file-set SHA-256: `443e1a87f96d5f6fb402a1920d10a4e05f3fcb55369fd93bef1885d8585d1584`.
- Desktop regression: 120 passed.
- Backend focused promotion: 1 passed.
- Full backend: 146 passed (one upstream Starlette/httpx deprecation warning).
- Payments regression: 31 passed (one upstream warning).
- `git diff --check`: PASS.

No backend production code changed. No live DB, CI, push, external write, or other worktree was used.
