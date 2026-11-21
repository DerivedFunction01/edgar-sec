"""The period-patterns scanner: period, total, whitespace, table-tag lines.
Each family's private copy makes two modules disagree about the shape; the
negatives pin the format shapes that are not recognizers of any family.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import period_patterns


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _scanners(findings: list) -> list[str]:
    return [f.scanner for f in findings]


# --- The period line: positives are the production copies verbatim ---


def test_flags_ica_head_period_ended_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_PERIOD_ENDED_RE = re.compile(r"(?:period|fiscal year) ended\\s+", re.IGNORECASE)\n'
            )
        },
    )
    findings = period_patterns.scan_period_patterns()
    assert _scanners(findings) == ["period-patterns"]
    assert findings[0].path == "edgar_sec/engine/thing.py"


def test_flags_multiline_reporting_period_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "_PERIOD_13Q1_RE = re.compile(\n"
                '    r"rule 13q-1.{0,200}?fiscal year ended\\s+", re.IGNORECASE | re.DOTALL\n'
                ")\n"
            )
        },
    )
    assert _scanners(period_patterns.scan_period_patterns()) == ["period-patterns"]


def test_flags_reporting_period_value_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_PERIOD_RE = re.compile(r"date of reporting period:\\s*(.+)", re.IGNORECASE)\n'
            )
        },
    )
    assert _scanners(period_patterns.scan_period_patterns()) == ["period-patterns"]


def test_allows_the_dates_home(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/text/dates.py": (
                'PERIOD_ENDED_RE = re.compile(r"(?:period|fiscal year) ended\\s+", re.IGNORECASE)\n'
                'REPORTING_PERIOD_LABEL_RE = re.compile(r"reporting period:\\s*(.*)")\n'
            )
        },
    )
    assert period_patterns.scan_period_patterns() == []


def test_allows_joint_date_capture_caption(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_FISCAL_YEAR_END_RE = re.compile(r"for the fiscal year ended\\s+([A-Z][a-z]+ \\d{1,2}, \\d{4})")\n'
            )
        },
    )
    assert period_patterns.scan_period_patterns() == []


def test_allows_composition_from_the_home(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "from edgar_sec.foundation.text.dates import PERIOD_ENDED_PAT\n"
                '_ENDED_RE = re.compile(PERIOD_ENDED_PAT + r"\\s+(.+)")\n'
            )
        },
    )
    assert period_patterns.scan_period_patterns() == []


# --- The totals line ---


def test_flags_total_row_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_TOTAL_RE = re.compile(r"^\\s*total\\b", re.IGNORECASE)\n'
            )
        },
    )
    findings = period_patterns.scan_period_patterns()
    assert _scanners(findings) == ["total-patterns"]


def test_allows_the_typed_rows_home(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/extraction/core/typed_rows.py": (
                'TOTAL_ROW_RE = re.compile(r"^\\s*total\\b", re.IGNORECASE)\n'
            )
        },
    )
    assert period_patterns.scan_period_patterns() == []


# --- The whitespace line ---


def test_flags_whitespace_run_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": '_WHITESPACE_RE = re.compile(r"\\s+")\n'},
    )
    assert _scanners(period_patterns.scan_period_patterns()) == ["whitespace-patterns"]


def test_flags_blank_line_run_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": '_RE_BLANKS = re.compile(r"\\n{3,}")\n'},
    )
    assert _scanners(period_patterns.scan_period_patterns()) == ["whitespace-patterns"]


def test_allows_the_patterns_and_normalize_homes(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/text/patterns.py": (
                'RE_WHITESPACE = re.compile(r"\\s+")\n'
                'RE_COLUMN_GAP = re.compile(r"[ \\t]{2,}")\n'
            ),
            "edgar_sec/foundation/text/normalize.py": (
                '_RE_MULTI_BLANKS = re.compile(r"\\n{3,}")\n'
                '_RE_MULTI_SPACES = re.compile(r"[ \\t]+")\n'
            ),
        },
    )
    assert period_patterns.scan_period_patterns() == []


def test_allows_whitespace_fragments_in_larger_patterns(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_PAGE_RE = re.compile(r"\\bpage\\s*(?:no\\.?\\s*)?\\d+", re.IGNORECASE)\n'
            )
        },
    )
    assert period_patterns.scan_period_patterns() == []


# --- The table-tag line ---


def test_flags_table_open_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_RE_TABLE_TAG = re.compile(r"<table\\b", re.IGNORECASE)\n'
            )
        },
    )
    assert _scanners(period_patterns.scan_period_patterns()) == ["table-tag-patterns"]


def test_flags_table_span_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_TAGGED_TABLE = re.compile(r"<TABLE\\b.*?</TABLE\\s*>", re.IGNORECASE | re.DOTALL)\n'
            )
        },
    )
    assert _scanners(period_patterns.scan_period_patterns()) == ["table-tag-patterns"]


def test_allows_the_migration_sources(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/protection/tags.py": (
                'TAGGED_TABLE_OPEN_RE = re.compile(r"<TABLE\\b", re.IGNORECASE)\n'
            ),
            "edgar_sec/engine/tables/patterns.py": (
                'RE_TABLE_BLOCK = re.compile(r"<TABLE>.*?</TABLE>", re.DOTALL)\n'
            ),
        },
    )
    assert period_patterns.scan_period_patterns() == []


def test_allows_table_tag_data_strings(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'lines = ["<TABLE>", "</TABLE>"]\n'},
    )
    assert period_patterns.scan_period_patterns() == []


# --- Negative fixtures: allowlisted format shapes no line may catch ---


def test_allows_omb_control_numbers(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'OMB_CONTROL_NUMBER = "1545-0074"\n'
                'OMB_RE = re.compile(r"\\d{4}-\\d{4}")\n'
            )
        },
    )
    assert period_patterns.scan_period_patterns() == []


def test_allows_phone_numbers(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'PHONE_RE = re.compile(r"\\(\\d{3}\\)\\s*\\d{3}-\\d{4}")\n'
            )
        },
    )
    assert period_patterns.scan_period_patterns() == []


def test_allows_zip_plus_four(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'ZIP = "12345-6789"\nZIP_RE = re.compile(r"^\\d{5}(?:-\\d{4})?$")\n'
            )
        },
    )
    assert period_patterns.scan_period_patterns() == []


def test_allows_archive_and_feed_date_formats(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'FEED_DATE_RE = re.compile(r"\\d{4}-\\d{2}-\\d{2}")\n'
                'ARCHIVE_STAMP = "20240131"\n'
            )
        },
    )
    assert period_patterns.scan_period_patterns() == []


def test_allows_sec_url_paths(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'SEC_PATH_RE = re.compile(r"/Archives/edgar/data/\\d+/\\d{18}")\n'
                'BROWSE_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"\n'
            )
        },
    )
    assert period_patterns.scan_period_patterns() == []
