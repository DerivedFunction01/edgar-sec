"""The wheel payload is what the runtime locates: taxonomy data in, tools out.
Built with the project's own builder into a scratch directory; the sdist is
not this test's concern.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _find_uv() -> str:
    found = shutil.which("uv")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "uv"
    if candidate.exists():
        return str(candidate)
    pytest.skip("uv is not available to build the wheel")


def test_wheel_payload_matches_the_runtime_surface(tmp_path: Path) -> None:
    out_dir = tmp_path / "dist"
    subprocess.run(
        [_find_uv(), "build", "--wheel", "--out-dir", str(out_dir), str(_REPO_ROOT)],
        check=True,
        capture_output=True,
        text=True,
    )
    (wheel,) = out_dir.glob("*.whl")
    names = zipfile.ZipFile(wheel).namelist()

    assert any(name.endswith(".parquet") for name in names)
    assert any("/taxonomy/" in name and name.endswith(".json") for name in names)
    assert "edgar_sec/engine/xbrl/discovery/seed_cohort.json" in names
    for corpus in ("seed", "vintage", "sp100", "probe"):
        assert not any(
            name.startswith(f"edgar_sec/engine/xbrl/discovery/{corpus}/")
            for name in names
        )
    assert not any(name.startswith("edgar_sec/tools/") for name in names)
    assert not any(name.endswith(".pyc") or "__pycache__" in name for name in names)
    assert any("/viewer/ui/" in name for name in names)
