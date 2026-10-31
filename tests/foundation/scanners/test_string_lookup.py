"""The string-lookup scanner.

Both directions are pinned: name searches and stray residuals reads are
caught; filename searches and sanctioned residual flows are left alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import ALL_SCANNERS, string_lookup


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_flags_startswith_on_qname(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/xbrl/solve/thing.py": (
                "def is_gaap(qname):\n    return qname.startswith('us-gaap:')\n"
            )
        },
    )
    findings = string_lookup.scan_string_lookup()
    assert [(f.path, f.line) for f in findings] == [
        ("edgar_sec/engine/xbrl/solve/thing.py", 2)
    ]


def test_flags_residuals_outside_sanctioned_homes(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/apps/client/views.py": (
                "def pick(record):\n    return 'Shares' in record.residuals\n"
            )
        },
    )
    findings = string_lookup.scan_string_lookup()
    assert [(f.path, f.line) for f in findings] == [
        ("edgar_sec/apps/client/views.py", 2)
    ]


def test_leaves_sanctioned_and_non_name_uses_alone(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/xbrl/discovery/miner.py": (
                "def mine(record):\n    return record.residuals\n"
            ),
            "edgar_sec/apps/client/facts.py": (
                "def carry(record):\n    return record.residuals\n"
            ),
            "edgar_sec/engine/xbrl/discovery/files.py": (
                "def is_calc(fn):\n    return fn.endswith('_cal.xml')\n"
            ),
            "edgar_sec/apps/client/loaders.py": (
                "def pick(fname):\n    return fname.endswith('.txt')\n"
            ),
            "edgar_sec/engine/xbrl/schema/atoms.py": (
                "def norm(head):\n    return head.startswith('H_')\n"
            ),
            "edgar_sec/pipelines/other/thing.py": (
                "def f(qname):\n    return qname.startswith('us-gaap:')\n"
            ),
        },
    )
    assert string_lookup.scan_string_lookup() == []


def test_scanner_registered() -> None:
    assert string_lookup.SCANNER in ALL_SCANNERS
    assert "string-lookup" in {scanner.name for scanner in ALL_SCANNERS}
