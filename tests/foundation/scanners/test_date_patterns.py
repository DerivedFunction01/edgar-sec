"""The date-patterns scanner.
A private month table makes two modules disagree about which year a fiscal period
falls in, surfacing as a mis-partitioned dataset rather than a crash.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import date_patterns


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_flags_private_month_table(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'MONTH_NAMES = ("january", "february")\n'},
    )
    findings = date_patterns.scan_date_patterns()
    assert [f.path for f in findings] == ["edgar_sec/engine/thing.py"]


def test_flags_inline_month_sequence(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'ORDER = ["jan", "feb", "mar"]\n'},
    )
    assert date_patterns.scan_date_patterns()


def test_flags_handcrafted_month_alternation(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'MONTHS = r"\\b(?:january|february|march)\\b"\n'
            )
        },
    )
    assert date_patterns.scan_date_patterns()


def test_flags_handcrafted_date_separator(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": ('STAMP = r"\\d{1,2}/\\d{1,2}/\\d{1,4}"\n')},
    )
    assert date_patterns.scan_date_patterns()


def test_allows_the_date_vocabulary_owner(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/text/dates.py": (
                'MONTH_NAMES = ("january", "february")\n'
                'STAMP = r"\\d{1,2}/\\d{1,2}/\\d{1,4}"\n'
            )
        },
    )
    assert date_patterns.scan_date_patterns() == []


def test_allows_import_of_month_pattern(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "from edgar_sec.foundation.text.dates import MONTH_PATTERN\n"
                "def is_month(text):\n    return bool(text)\n"
            )
        },
    )
    assert date_patterns.scan_date_patterns() == []


def test_ignores_tests(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"tests/test_thing.py": 'MONTH_NAMES = ("january", "february")\n'},
    )
    assert date_patterns.scan_date_patterns() == []
