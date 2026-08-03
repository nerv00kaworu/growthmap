"""Run the shared revision security contract in fresh processes.

The backend binds its engine at import time, so each case gets an independent
interpreter/app/database. These are assertions, never conditional skips.
"""
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).parents[1]
CASES = [
    "test_openapi_inventory_requires_revision_contract",
    "test_stale_edge_patch_is_no_write",
    "test_true_independent_gui_vs_gui_concurrency",
    "test_true_independent_gui_vs_agent_concurrency",
    "test_concurrent_identical_idempotency_key_has_one_canonical_write",
]

@pytest.mark.parametrize("case", CASES, ids=CASES)
def test_shared_revision_contract_in_fresh_app(case: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", f"tests.shared_revision_cases.SharedRevisionContractTest.{case}"],
        cwd=BACKEND,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "OK" in result.stderr
    assert "skipped" not in (result.stdout + result.stderr).lower()
