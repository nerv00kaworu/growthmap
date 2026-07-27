#!/usr/bin/env bash
set -euo pipefail

# Compatibility entry point. The maintained launcher is intentionally safe:
# it never installs dependencies, kills listeners, or changes database state.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/scripts/start_growthmap.sh" "$@"
