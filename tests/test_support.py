"""Scratch lifecycle of the shared test helpers: placement and exit sweep."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.paths import resolve_paths, transient_dataset_root
from tests import support
from tests.support import TESTS_ROOT

_CHILD = """
import os
from pathlib import Path

from tests.support import roster_of

base = Path(os.environ["TMPDIR"])
foreign = base / "edgar-test-cohort-foreign"
foreign.mkdir()
roster_of(["0000320193"], ["APPLE INC"])
created = [p for p in base.glob("edgar-test-cohort-*") if p != foreign]
assert len(created) == 1
print(created[0])
"""


def test_scratch_base_honors_tmpdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert support.scratch_base() == tmp_path


def test_scratch_base_falls_back_to_repo_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TMPDIR", raising=False)
    paths = resolve_paths(TESTS_ROOT.parent)
    expected = transient_dataset_root(paths.artifacts_root, "tests")
    assert support.scratch_base() == expected


def test_cohort_dir_is_gone_after_the_creating_process_exits(
    tmp_path: Path,
) -> None:
    """The child creates a cohort dir and exits; only the foreign dir stays."""
    env = {
        **os.environ,
        "TMPDIR": str(tmp_path),
        "PYTHONPATH": str(TESTS_ROOT.parent),
    }
    result = subprocess.run(
        [sys.executable, "-c", _CHILD],
        capture_output=True,
        text=True,
        cwd=TESTS_ROOT.parent,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    created = Path(result.stdout.strip())
    assert created.parent == tmp_path
    assert not created.exists()
    assert (tmp_path / "edgar-test-cohort-foreign").is_dir()
