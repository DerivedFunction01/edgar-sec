"""The refcell-patterns scanner.
A private caption core makes two modules disagree about what counts as a
note or item reference, surfacing as inconsistent section extraction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners.patterns import refcell_patterns


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_flags_note_caption_definition(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_NOTE_CAPTION_RE = re.compile(r"(?i)^\\s*note\\s+\\d{1,3}'
                '(?:\\s*[\\.\\):\\-]\\s*|\\s+)[a-z]")\n'
            )
        },
    )
    findings = refcell_patterns.scan_refcell_patterns()
    assert [f.path for f in findings] == ["edgar_sec/engine/thing.py"]
    assert findings[0].scanner == "refcell-patterns"
    assert "engine.tables.toc.patterns" in findings[0].hint


def test_flags_note_heading_core_line(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "PAT = re.compile(\n"
                '    r"^\\s*(?:[\\|+\\t-]\\s*)?NOTES?\\s+(\\d+)\\b'
                '(?:\\s*[:.\\-]\\s*|\\s+)?(.*)$",\n'
                "    re.IGNORECASE,\n"
                ")\n"
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns()


def test_flags_grouped_note_core_line(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "PAT = re.compile(\n"
                '    rf"\\bNOTES?\\s+(\\d+(?:(?:\\s*{CONJ}\\s*(?:NOTES?\\s+)?)'
                '\\d+)+)\\b",\n'
                "    re.IGNORECASE,\n"
                ")\n"
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns()


def test_flags_inline_item_definition(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_ITEM_INLINE_RE = re.compile(r"\\bITEMS?\\s+(\\d+[A-Z]?'
                '(?:\\.\\d{1,2})?)\\b", re.IGNORECASE)\n'
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns()


def test_flags_heading_note_definition(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_HEADING_NOTE = re.compile(r"notes to|^\\s*note\\s+\\d", '
                "re.IGNORECASE)\n"
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns()


def test_flags_narrowed_part_term(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": '_TERMS = [\n    r"Part\\s+[IVX]+",\n]\n'},
    )
    findings = refcell_patterns.scan_refcell_patterns()
    assert [f.path for f in findings] == ["edgar_sec/engine/thing.py"]
    assert findings[0].message.startswith("narrowed PART")


def test_flags_see_reference_definition(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_RE_SEE_ROW = re.compile(r"(?i)\\bsee\\s+(?:item|row)\\s+(\\d+)")\n'
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns()


def test_allows_omb_number(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'OMB = re.compile(r"^\\d{4}-\\d{2}$")\nOMB_TEXT = "OMB No. 3235-0001"\n'
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns() == []


def test_allows_phone_number(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'PHONE = re.compile(r"^\\(\\d{3}\\) \\d{3}-\\d{4}$")\n'
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns() == []


def test_allows_zip_plus_four(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'ZIP = re.compile(r"^\\d{5}-\\d{4}$")\n'},
    )
    assert refcell_patterns.scan_refcell_patterns() == []


def test_allows_archive_and_feed_date_formats(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'STAMP = re.compile(r"^\\d{4}/\\d{2}/\\d{2}$")\n'
                'FEED = re.compile(r"^\\d{1,2}/\\d{1,2}/\\d{2,4}$")\n'
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns() == []


def test_allows_sec_url_paths(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'DATA = "https://www.sec.gov/Archives/edgar/data/1234567/'
                '0001234567-25-000001-index.htm"\n'
                'PATH = re.compile(r"/Archives/edgar/data/\\d+/")\n'
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns() == []


def test_allows_keyword_adjacent_words(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'A = re.compile(r"ITEMIZED\\s+DEDUCTIONS")\n'
                'B = re.compile(r"PARTNER\\s+\\d+")\n'
                'C = re.compile(r"NOTEBOOK\\s+\\d+")\n'
                'D = re.compile(r"see\\s+section\\s+\\d+")\n'
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns() == []


def test_allows_slot_prefix_fragments(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '"fundType": r"(?:\\(?\\b(?:ITEM\\s+\\d+|\\d+)\\)?\\s*[.:]?\\s*)?'
                '(?:SOURCE\\s+OF\\s+FUNDS)",\n'
                '"secUseOnly": r"(?:\\(?\\b(?:ITEM\\s+3|3)\\)?\\s*[.:]?\\s*)?'
                '(?:SEC\\s+USE)",\n'
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns() == []


def test_allows_boundary_term(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": '_TERMS = [\n    r"ITEM\\s+\\d+\\b",\n]\n'},
    )
    assert refcell_patterns.scan_refcell_patterns() == []


def test_allows_item_range_branch(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_ALT = (\n    r"ITEMS?\\s+\\d+(?:[-\u2013]\\d+)?",\n)\n'
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns() == []


def test_allows_item_range_definition(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_ITEMS_RE = re.compile(r"Items\\s+(\\d+)\\s*-\\s*(\\d+)")\n'
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns() == []


def test_allows_full_part_composition(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_PART_INLINE_RE = re.compile(r"\\bPART\\s+([IVXLCDM]+|\\d+)\\b", '
                "re.IGNORECASE)\n"
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns() == []


def test_allows_the_reference_home(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/toc/patterns.py": (
                '_NOTE_CAPTION_RE = re.compile(r"(?i)^\\s*note\\s+\\d{1,3}'
                '(?:\\s*[\\.\\):\\-]\\s*|\\s+)[a-z]")\n'
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns() == []


def test_allows_import_of_reference_home(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "from edgar_sec.engine.tables.toc.patterns import (\n"
                "    RE_NOTE_REFERENCE,\n"
                ")\n"
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns() == []


def test_ignores_tests(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "tests/test_thing.py": (
                '_RE_SEE_ROW = re.compile(r"(?i)\\bsee\\s+(?:item|row)\\s+(\\d+)")\n'
            )
        },
    )
    assert refcell_patterns.scan_refcell_patterns() == []
