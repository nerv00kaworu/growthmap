"""Cross-platform backend test custody helpers.

Windows production provider locks intentionally reject a shared TEMP/checkout
parent.  Tests get a newly-created, current-user-owned child instead; existing
paths are never repaired by this harness.
"""
import os
import tempfile
from pathlib import Path

import pytest


if os.name == "nt":
    _native_mkdtemp = tempfile.mkdtemp

    def _make_private(path: Path) -> Path:
        # Callers pass only a child they created in this process; never repair a
        # pre-existing TEMP/AppData/check-out parent.
        from api.windows_file_security import apply_private, verify
        apply_private(path)
        verify(path, kind="dir")
        return path

    def _private_mkdtemp(*args, **kwargs):
        return str(_make_private(Path(_native_mkdtemp(*args, **kwargs))))

    tempfile.mkdtemp = _private_mkdtemp

    def pytest_configure(config):
        """Put pytest's tmp_path tree below one newly-created private root."""
        if config.option.basetemp is not None:
            raise RuntimeError("Windows backend tests require harness-owned --basetemp")
        job_root = os.getenv("GROWTHMAP_WINDOWS_BACKEND_ROOT")
        if job_root:
            base = Path(job_root) / f"pytest-{os.getpid()}"
            base.mkdir()
            _make_private(base)
        else:
            base = Path(_private_mkdtemp(prefix="growthmap-pytest-"))
        config.option.basetemp = str(base)

    @pytest.fixture(autouse=True)
    def _private_windows_tmp_path(request):
        """Make only pytest-created per-test children exact private containers."""
        if "tmp_path" in request.fixturenames:
            _make_private(request.getfixturevalue("tmp_path"))
