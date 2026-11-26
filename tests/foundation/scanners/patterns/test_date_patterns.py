"""The date-patterns scanner.
A private month table makes two modules disagree about which year a fiscal period
falls in, surfacing as a mis-partitioned dataset rather than a crash.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners.patterns import date_patterns


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
            "edgar_sec/foundation/text/date_patterns.py": (
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
                "from edgar_sec.foundation.text.date_patterns import MONTH_PATTERN\n"
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


def test_flags_strict_year_shape_in_the_date_vocabulary_owner(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/text/date_patterns.py": (
                'STRICT_MONTH_PATTERN = "|".join(MONTH_NAMES)\n'
                'STRICT_YEAR_TOKEN_PATTERN = r"(?:19|20)\\d{2}"\n'
            )
        },
    )
    findings = date_patterns.scan_date_patterns()
    assert [f.path for f in findings] == [
        "edgar_sec/foundation/text/date_patterns.py"
    ]
    assert findings[0].message == "narrowed year alternation in a regex"


def test_flags_narrowed_year_in_the_owner_under_any_other_name(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/text/date_patterns.py": (
                '_YEAR_RE = re.compile(r"\\b(?:19|20)\\d{2}\\b")\n'
                'YEARS = r"19\\d{2}|20\\d{2}"\n'
            )
        },
    )
    findings = date_patterns.scan_date_patterns()
    assert [f.path for f in findings] == [
        "edgar_sec/foundation/text/date_patterns.py",
        "edgar_sec/foundation/text/date_patterns.py",
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


def test_flags_century_prefix_filter_on_the_six_known_sites(
    synthetic_repo: Path,
) -> None:
    # The exact lines of main 038321b8, pulled from git before the cure.
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/extraction/core/text/period_keys.py": (
                "    return [y for y in YEAR_TOKEN_SEARCH_RE.findall(line)"
                ' if y[:2] in ("19", "20")]\n'
                "    if year is not None and year.group(0)[:2]"
                ' in ("19", "20"):\n'
            ),
            "edgar_sec/engine/tables/extraction/evidence/balance_sheet/"
            "aro_evidence.py": (
                "        year for year in YEAR_TOKEN_SEARCH_RE.findall(line)"
                ' if year[:2] in ("19", "20")\n'
                "    if year is not None and year.group(0)[:2]"
                ' in ("19", "20"):\n'
            ),
            "edgar_sec/engine/tables/extraction/evidence/balance_sheet/"
            "lease_evidence.py": ('            if year[:2] in ("19", "20")\n'),
            "edgar_sec/engine/tables/extraction/note_separators/"
            "lease_separator_evidence.py": ('        if y[:2] in ("19", "20")\n'),
        },
    )
    findings = date_patterns.scan_date_patterns()
    assert len(findings) == 6
    assert {f.message for f in findings} == {"narrowed year century-prefix filter"}
    assert all("YEAR_TOKEN_SEARCH_RE" in f.hint for f in findings)


@pytest.mark.parametrize(
    "line",
    [
        '    if y[:2] in ("20", "19"):\n',
        "    if y[:2] in ('19', '20'):\n",
        '    if y[:2] in ["19", "20"]:\n',
        '    if y[:2] in {"19", "20"}:\n',
        '    if y[0:2] in ("19", "20"):\n',
        '    if y[:2] not in ("19", "20"):\n',
        '    if token.startswith("19"):\n',
        "    if token.startswith('20'):\n",
        '    if token.startswith(("19", "20")):\n',
        "    if token.startswith(('20', '19')):\n",
        '    if y[:2] == "19" or y[:2] == "20":\n',
        '    if "19" == year.group(0)[:2]:\n',
    ],
)
def test_flags_century_prefix_filter_spelling_variants(
    synthetic_repo: Path, line: str
) -> None:
    _build_repo(synthetic_repo, {"edgar_sec/engine/thing.py": line})
    findings = date_patterns.scan_date_patterns()
    assert [f.message for f in findings] == ["narrowed year century-prefix filter"]


def test_allows_century_pair_as_data(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'CODES = {"19": ("a",), "20": ("b",)}\n'
                'ITEMS = ("19", "20")\n'
                "def pick(code):\n"
                "    return code in ITEMS\n"
            )
        },
    )
    assert date_patterns.scan_date_patterns() == []


def test_allows_non_century_prefix_tests(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "def a(label, day, sha, entry, other, token):\n"
                '    x = label.startswith("total")\n'
                '    y = token.startswith("20x")\n'
                "    z = day[:4] == str(2024)\n"
                '    w = sha[:2] == "ab"\n'
                "    v = entry[:2] > other[:2]\n"
                "    return x and y and z and w and v\n"
            )
        },
    )
    assert date_patterns.scan_date_patterns() == []


def test_flags_century_prefix_filter_in_the_owner_under_any_other_name(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/text/date_patterns.py": (
                'def pick(y):\n    return y[:2] in ("19", "20")\n'
            )
        },
    )
    findings = date_patterns.scan_date_patterns()
    assert [f.message for f in findings] == ["narrowed year century-prefix filter"]


def test_flags_sanctioned_name_in_the_owner_for_the_filter_form(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/text/date_patterns.py": (
                'STRICT_YEAR_TOKEN_PATTERN: str = pick(y[:2] in ("19", "20"))\n'
            )
        },
    )
    findings = date_patterns.scan_date_patterns()
    assert [f.message for f in findings] == ["narrowed year century-prefix filter"]


def test_allows_import_of_year_token_search_pattern(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "from edgar_sec.foundation.text.date_patterns import (\n"
                "    YEAR_TOKEN_SEARCH_RE,\n"
                ")\n"
                "def years(text):\n"
                "    return YEAR_TOKEN_SEARCH_RE.findall(text)\n"
            )
        },
    )
    assert date_patterns.scan_date_patterns() == []
