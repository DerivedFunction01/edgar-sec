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


def test_flags_narrowed_year_century_alternation(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_YEAR_RE = re.compile(r"\\b(?:19|20)\\d{2}\\b")\n'
            )
        },
    )
    findings = date_patterns.scan_date_patterns()
    assert [f.path for f in findings] == ["edgar_sec/engine/thing.py"]
    assert findings[0].message == "narrowed year alternation in a regex"
    assert "YEAR_TOKEN_SEARCH_RE" in findings[0].hint


def test_flags_narrowed_year_plain_century_group(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'YEARS = r"\\b(19|20)\\d{2}\\b"\n'},
    )
    assert date_patterns.scan_date_patterns()


def test_flags_narrowed_year_digit_alternation(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'YEARS = r"19\\d{2}|20\\d{2}"\n'},
    )
    assert date_patterns.scan_date_patterns()


def test_flags_narrowed_year_bracket_alternation(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'YEARS = r"19[0-9]{2}|20[0-9]{2}"\n'},
    )
    assert date_patterns.scan_date_patterns()


def test_flags_narrowed_year_reversed_alternation(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'YEARS = r"20\\d\\d|19\\d\\d"\n'},
    )
    assert date_patterns.scan_date_patterns()


def test_flags_narrowed_year_alternation_list(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'PAT = build_alternation([r"19\\d{2}", r"20\\d{2}"])\n'
            )
        },
    )
    assert date_patterns.scan_date_patterns()


def test_allows_sanctioned_strict_pair_in_the_date_vocabulary_owner(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/text/dates.py": (
                'STRICT_MONTH_PATTERN = "|".join(MONTH_NAMES)\n'
                'STRICT_YEAR_TOKEN_PATTERN = r"(?:19|20)\\d{2}"\n'
            )
        },
    )
    assert date_patterns.scan_date_patterns() == []


def test_flags_narrowed_year_in_the_owner_under_any_other_name(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/text/dates.py": (
                '_YEAR_RE = re.compile(r"\\b(?:19|20)\\d{2}\\b")\n'
                'YEARS = r"19\\d{2}|20\\d{2}"\n'
            )
        },
    )
    findings = date_patterns.scan_date_patterns()
    assert [f.path for f in findings] == [
        "edgar_sec/foundation/text/dates.py",
        "edgar_sec/foundation/text/dates.py",
    ]


def test_allows_year_literals_as_data(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "EXPECTED_YEARS = [1999, 2019, 2020, 2024]\n"
                'LABEL = "2019|2020 comparison"\n'
                "SPECIMENS = {'fy2019': 1, 'fy2020': 2}\n"
            )
        },
    )
    assert date_patterns.scan_date_patterns() == []


def test_allows_full_range_year_composition(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'PAT = build_alternation([r"19[0-9]{2}", r"[2-9][0-9]{3}"])\n'
            )
        },
    )
    assert date_patterns.scan_date_patterns() == []


def test_allows_import_of_year_token_search_pattern(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "from edgar_sec.foundation.text.dates import (\n"
                "    YEAR_TOKEN_SEARCH_RE,\n"
                ")\n"
                "def years(text):\n"
                "    return YEAR_TOKEN_SEARCH_RE.findall(text)\n"
            )
        },
    )
    assert date_patterns.scan_date_patterns() == []
