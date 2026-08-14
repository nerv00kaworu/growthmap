#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
"${PYTHON_BIN:-python3}" -m PyInstaller --clean --noconfirm packaging/growthmap-mcp.spec
