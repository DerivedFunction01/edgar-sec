"""Scratch directories for tests: placement, registry, and exit sweep."""

from __future__ import annotations

import atexit
import shutil
import tempfile
import threading
from pathlib import Path

from edgar_sec.foundation.runtime.env import get_env
from edgar_sec.foundation.runtime.paths import resolve_paths, transient_dataset_root
from tests.support.fixtures import TESTS_ROOT

#: Scratch dirs are registered per process; the exit sweep removes exactly
#: the dirs this process created, never another concurrent run's.
_SCRATCH_DIRS: set[Path] = set()
_SCRATCH_LOCK = threading.Lock()


def scratch_base() -> Path:
    """Scratch placement: TMPDIR when set, else the repo transient root."""
    configured = get_env("TMPDIR")
    if configured:
        return Path(configured)
    paths = resolve_paths(TESTS_ROOT.parent)
    return transient_dataset_root(paths.artifacts_root, "tests")


def _make_scratch_dir(prefix: str) -> Path:
    base = scratch_base()
    base.mkdir(parents=True, exist_ok=True)
    created = Path(tempfile.mkdtemp(prefix=prefix, dir=base))
    with _SCRATCH_LOCK:
        _SCRATCH_DIRS.add(created)
    return created


def sweep_scratch_dirs() -> None:
    """Remove this process's registered scratch dirs, each in isolation."""
    with _SCRATCH_LOCK:
        pending = tuple(_SCRATCH_DIRS)
        _SCRATCH_DIRS.clear()
    for path in pending:
        shutil.rmtree(path, ignore_errors=True)


atexit.register(sweep_scratch_dirs)


def scratch_root() -> Path:
    """Compiling writes a dataset, so read-only tests still need somewhere to put it."""
    global _ROOT_SCRATCH
    if _ROOT_SCRATCH is None:
        _ROOT_SCRATCH = _make_scratch_dir("edgar-test-root-")
    return _ROOT_SCRATCH


_ROOT_SCRATCH: Path | None = None


__all__ = [
    "scratch_base",
    "scratch_root",
    "sweep_scratch_dirs",
]
