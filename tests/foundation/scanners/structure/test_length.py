"""The file-length scanner: the cap and the creep band."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners.structure import length
from edgar_sec.foundation.scanners.base import (
    SEVERITY_ERROR,
    SEVERITY_NOTICE,
    ScannerFinding,
)


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _sized(lines: int) -> str:
    return "line\n" * lines


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _errors(findings: list[ScannerFinding]) -> list[ScannerFinding]:
    return [f for f in findings if f.severity == SEVERITY_ERROR]


def _notices(findings: list[ScannerFinding]) -> list[ScannerFinding]:
    return [f for f in findings if f.severity == SEVERITY_NOTICE]


def test_module_over_cap_is_one_error(synthetic_repo: Path) -> None:
    _build_repo(synthetic_repo, {"edgar_sec/mod.py": _sized(801)})
    findings = length.scan_file_length()
    assert len(findings) == 1
    assert findings[0].severity == SEVERITY_ERROR
    assert findings[0].line == 801


def test_module_at_cap_is_one_notice(synthetic_repo: Path) -> None:
    _build_repo(synthetic_repo, {"edgar_sec/mod.py": _sized(800)})
    findings = length.scan_file_length()
    assert _errors(findings) == []
    assert len(_notices(findings)) == 1


def test_module_in_creep_band_is_one_notice(synthetic_repo: Path) -> None:
    _build_repo(synthetic_repo, {"edgar_sec/mod.py": _sized(750)})
    findings = length.scan_file_length()
    assert _errors(findings) == []
    assert len(_notices(findings)) == 1


def test_module_below_band_is_clean(synthetic_repo: Path) -> None:
    _build_repo(synthetic_repo, {"edgar_sec/mod.py": _sized(699)})
    assert length.scan_file_length() == []


def test_suite_over_cap_is_one_error(synthetic_repo: Path) -> None:
    _build_repo(synthetic_repo, {"tests/apps/client/test_big.py": _sized(900)})
    findings = length.scan_file_length()
    assert len(_errors(findings)) == 1
    assert _notices(findings) == []


def test_suite_in_creep_band_is_clean(synthetic_repo: Path) -> None:
    _build_repo(synthetic_repo, {"tests/apps/client/test_big.py": _sized(750)})
    assert length.scan_file_length() == []


def test_infrastructure_in_creep_band_is_one_notice(synthetic_repo: Path) -> None:
    _build_repo(synthetic_repo, {"tests/support.py": _sized(750)})
    findings = length.scan_file_length()
    assert _errors(findings) == []
    assert len(_notices(findings)) == 1


def test_viewer_tsx_over_cap_is_one_error(synthetic_repo: Path) -> None:
    _build_repo(synthetic_repo, {"edgar_sec/apps/viewer/Panel.tsx": _sized(801)})
    findings = length.scan_file_length()
    assert len(_errors(findings)) == 1


def test_css_under_assets_is_outside_the_population(synthetic_repo: Path) -> None:
    _build_repo(synthetic_repo, {"edgar_sec/apps/viewer/assets/site.css": _sized(801)})
    assert length.scan_file_length() == []


def test_css_outside_assets_over_cap_is_one_error(synthetic_repo: Path) -> None:
    _build_repo(synthetic_repo, {"edgar_sec/apps/viewer/site.css": _sized(801)})
    findings = length.scan_file_length()
    assert len(_errors(findings)) == 1


def test_root_init_venv_over_cap_is_one_error(synthetic_repo: Path) -> None:
    _build_repo(synthetic_repo, {"init_venv.py": _sized(801)})
    findings = length.scan_file_length()
    assert len(_errors(findings)) == 1
