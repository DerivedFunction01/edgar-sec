"""The folder-density scanner: per-folder code-file cap and creep band."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners.structure import folder_density
from edgar_sec.foundation.scanners.base import (
    SEVERITY_ERROR,
    SEVERITY_NOTICE,
    ScannerFinding,
)


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _populate(
    root: Path,
    folder: str,
    count: int,
    suffix: str = ".py",
    stem: str = "mod",
) -> None:
    directory = root / folder
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        path = directory / f"{stem}{index}{suffix}"
        path.write_text("value = 1\n", encoding="utf-8")


def _errors(findings: list[ScannerFinding]) -> list[ScannerFinding]:
    return [f for f in findings if f.severity == SEVERITY_ERROR]


def _notices(findings: list[ScannerFinding]) -> list[ScannerFinding]:
    return [f for f in findings if f.severity == SEVERITY_NOTICE]


def test_folder_at_cap_reports_notice_only(synthetic_repo: Path) -> None:
    _populate(synthetic_repo, "edgar_sec/pkg", 20)
    findings = folder_density.scan_folder_density()
    assert _errors(findings) == []
    assert len(_notices(findings)) == 1
    assert _notices(findings)[0].path == "edgar_sec/pkg"


def test_folder_over_cap_reports_one_error(synthetic_repo: Path) -> None:
    _populate(synthetic_repo, "edgar_sec/pkg", 21)
    findings = folder_density.scan_folder_density()
    assert len(_errors(findings)) == 1
    assert _notices(findings) == []


def test_folder_at_creep_floor_reports_nothing(synthetic_repo: Path) -> None:
    _populate(synthetic_repo, "edgar_sec/pkg", 16)
    assert folder_density.scan_folder_density() == []


def test_folder_in_creep_band_reports_one_notice(synthetic_repo: Path) -> None:
    _populate(synthetic_repo, "edgar_sec/pkg", 17)
    findings = folder_density.scan_folder_density()
    assert _errors(findings) == []
    assert len(_notices(findings)) == 1


def test_root_folder_counts_root_entry_points(synthetic_repo: Path) -> None:
    for name in ("check.py", "run.py", "init_venv.py"):
        (synthetic_repo / name).write_text("value = 1\n", encoding="utf-8")
    assert folder_density.folder_counts() == {".": 3}
    assert folder_density.scan_folder_density() == []


def test_subfolder_files_do_not_count_toward_parent(
    synthetic_repo: Path,
) -> None:
    _populate(synthetic_repo, "edgar_sec/pkg", 16)
    _populate(synthetic_repo, "edgar_sec/pkg/child", 5)
    assert folder_density.folder_counts() == {
        "edgar_sec/pkg": 16,
        "edgar_sec/pkg/child": 5,
    }
    assert folder_density.scan_folder_density() == []


def test_data_files_do_not_count(synthetic_repo: Path) -> None:
    _populate(synthetic_repo, "edgar_sec/pkg", 7, suffix=".json", stem="data")
    _populate(synthetic_repo, "edgar_sec/pkg", 7, suffix=".parquet", stem="tab")
    _populate(synthetic_repo, "edgar_sec/pkg", 7, suffix=".md", stem="doc")
    assert "edgar_sec/pkg" not in folder_density.folder_counts()
    assert folder_density.scan_folder_density() == []


def test_assets_and_generated_parts_do_not_count(synthetic_repo: Path) -> None:
    _populate(synthetic_repo, "edgar_sec/pkg/assets", 21)
    _populate(synthetic_repo, "edgar_sec/pkg/generated", 21)
    assert folder_density.scan_folder_density() == []


def test_css_and_ts_files_count_toward_a_folder(synthetic_repo: Path) -> None:
    _populate(synthetic_repo, "edgar_sec/pkg", 7, suffix=".py", stem="mod")
    _populate(synthetic_repo, "edgar_sec/pkg", 7, suffix=".ts", stem="view")
    _populate(synthetic_repo, "edgar_sec/pkg", 7, suffix=".css", stem="style")
    findings = folder_density.scan_folder_density()
    assert len(_errors(findings)) == 1
    assert _notices(findings) == []
