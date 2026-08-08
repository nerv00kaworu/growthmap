# Payment/Whop isolated local operations drills

These tools produce **source-only local evidence**. They do not call Whop, a payment
provider, or Authority, and do not clear production launch blockers. Never point them
at production, staging, copied production data, or a live service path.

## Safety contract

Create a fresh temporary directory and place the exact marker below in it. Every DB, checkpoint, key fixture, backup, and restore path must be an immediate child of that real (non-symlink) directory. Marker/key/artifacts must be single-link regular files opened without symlink following. Names are NFKC-normalized and compounds containing `prod`, `production`, `live`, or `staging` (case-insensitive) are refused.

```sh
ROOT="$(mktemp -d /tmp/growthmap-isolated-drill.XXXXXX)"
printf 'growthmap isolated local drill v1\n' > "$ROOT/.growthmap-isolated-test"
```

Use only a database/checkpoint pair created by an isolated `PaymentService` fixture and
a generated fixture MAC key. The backup uses SQLite's online backup API, checks that
the authenticated checkpoint remained stable, validates both artifacts, and atomically
publishes the directory. Restore verifies the pair manifest, integrity/FKs, migration
ledger/checksums/schema 13, authenticated closure, and `PaymentService` startup before
publishing. A partial or mismatched pair is never accepted.

From the repository root, select a Python interpreter explicitly (for example, an
activated virtual environment) and derive the payments path from the current checkout:

```sh
PY="${PYTHON:-python3}"
PP="$PWD/services/payments"
PYTHONPATH="$PP" "$PY" "$PP/scripts/ops_backup_restore.py" \
  --isolated-root "$ROOT" --db "$ROOT/payments.sqlite3" \
  --checkpoint "$ROOT/payments.checkpoint" --mac-key-file "$ROOT/mac.fixture" \
  --destination "$ROOT/backup"
```

Monitoring is bounded JSON. Exit `0=ok`, `1=warning`, `2=critical`. Warning thresholds:
any quarantine/manual-review/ambiguous row; entitlement age >=900s; revocation age
>=300s; or attempts >=5. Any checkpoint, integrity, FK, migration, or schema failure is
critical. Output contains counts/maxima only—no raw body/digest, email, recovery code,
activation key, provider signature, or secret.

```sh
PYTHONPATH="$PP" "$PY" "$PP/scripts/ops_monitor.py" --isolated-root "$ROOT" \
 --db "$ROOT/payments.sqlite3" --checkpoint "$ROOT/payments.checkpoint" \
 --mac-key-file "$ROOT/mac.fixture"
PYTHONPATH="$PP" "$PY" "$PP/scripts/ops_reconcile.py" --isolated-root "$ROOT" \
 --db "$ROOT/payments.sqlite3" --checkpoint "$ROOT/payments.checkpoint" \
 --mac-key-file "$ROOT/mac.fixture" --limit 100
```

The reconciliation report is read-only, bounded, uses report-scoped keyed 128-bit pseudonyms with no cross-report linkage,
and classifies webhook quarantine/pending, entitlement readback/stuck, revocation stuck,
and payment manual review. It intentionally performs **no replay or mutation**.
Operator actions require independently authenticated provider evidence or identity-pinned
Authority readback through the reviewed service procedures.

## Publication boundary and replay scope

Staging directories are mode 0700 and artifacts 0600, owned by the current local user. The local threat model does not claim protection from a privileged process, but final descriptor-bound identity/content/MAC checks immediately before descriptor-relative `renameat2`, plus post-rename no-follow verification, catch same-user substitution. A post-publication mismatch is moved to an isolated quarantine name and never reported as success.

This local format has no durable production generation or rollback anchor, so **anti-replay / rollback prevention is NOT PROVIDED**. Restore requires the operator-selected, 64-hex SHA-256 digest of the authenticated `manifest.json` (`bundle_manifest_digest(...)` then `restore_pair(..., expected_bundle_digest=...)`). This binds the requested bundle and rejects mismatch; it does not prevent an operator from deliberately selecting an older authenticated local bundle.

Source size/page bounds are checked before staging. Online backup copies in bounded page steps with a monotonic deadline and growth budget. Validation SQL has a progress-handler deadline. Monitoring converts all such failures into deterministic bounded critical JSON (exit 2).
