"""The page-patterns scanner.
A private page-reference core makes two modules disagree about what
counts as a page reference, surfacing as inconsistent cross-references.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import page_patterns


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_flags_plain_page_reference_definition(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_PAGE_REF_RE = re.compile(r"\\bpage\\\\s+\\\\d+", re.IGNORECASE)\n'
            )
        },
    )
    findings = page_patterns.scan_page_patterns()
    assert [f.path for f in findings] == ["edgar_sec/engine/thing.py"]
    assert findings[0].scanner == "page-patterns"


def test_flags_page_no_form_definition(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_PAGE_REF_RE = re.compile(r"page\\\\s*(?:no\\\\.?\\\\s*)?\\\\d+")\n'
            )
        },
    )
    findings = page_patterns.scan_page_patterns()
    assert [f.path for f in findings] == ["edgar_sec/engine/thing.py"]


def test_flags_letter_dash_form_definition(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_PAGE_REF_RE = re.compile(r"\\bpage\\\\s+[A-Z]-\\\\d+")\n'
            )
        },
    )
    findings = page_patterns.scan_page_patterns()
    assert [f.path for f in findings] == ["edgar_sec/engine/thing.py"]


def test_home_definition_is_allowed(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/text/patterns.py": (
                'RE_PAGE_REFERENCE = re.compile(r"\\bpage\\\\s*(?:no\\\\.?'
                '\\\\s*)?[A-Z]?-?\\\\d+", re.IGNORECASE)\n'
            )
        },
    )
    assert page_patterns.scan_page_patterns() == []


def test_optional_prefix_line_classifier_is_allowed(synthetic_repo: Path) -> None:
    # The items detector's non-prose test (inventory §d3 cousin).
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_RE_NON_PROSE = re.compile(r"^(?:page\\\\s+)?\\\\d+$|'
                '^[\\\\.\\\\-\\\\s|+=]+$", re.IGNORECASE)\n'
            )
        },
    )
    assert page_patterns.scan_page_patterns() == []


def test_whole_line_page_label_is_allowed(synthetic_repo: Path) -> None:
    # The page-markers whole-line page label (its internal vocabulary).
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_PAGE_NUMBER = re.compile(r"(?im)^[ \\t]*page[ \\t]+'
                '(?P<page>\\\\d+)[ \\t]*$", re.IGNORECASE)\n'
            )
        },
    )
    assert page_patterns.scan_page_patterns() == []


def test_page_of_count_extraction_is_allowed(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_PAGE_OF = re.compile(r"page[ \\t]+(?P<page>\\\\d+)[ \\t]+'
                'of[ \\t]+(?P<count>\\\\d+)")\n'
            )
        },
    )
    assert page_patterns.scan_page_patterns() == []


def test_label_value_extraction_is_allowed(synthetic_repo: Path) -> None:
    # The page-markers inline label extraction (inventory §d3 cousin).
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_LABEL = re.compile(r"^(?P<prefix>.{0,80}?\\bpage\\\\s+)'
                '(?P<value>\\\\d{1,4})\\b(?P<suffix>.{0,80})$")\n'
            )
        },
    )
    assert page_patterns.scan_page_patterns() == []


def test_boilerplate_disjunct_is_allowed(synthetic_repo: Path) -> None:
    # The ownership boilerplate disjunct (inventory §d3 cousin).
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/forms/ownership/patterns.py": (
                '_BOILERPLATE_RE = re.compile(\n'
                '    rf"(?i)\\b(?:{OWNERSHIP_FORM_ALT})\\b|page\\\\s+\\\\d+|'
                '\\\\(continued\\\\)"\n'
                ")\n"
            )
        },
    )
    assert page_patterns.scan_page_patterns() == []


def test_home_fragment_composition_is_allowed(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'RE_PAGE_SUFFIX = re.compile(\n'
                '    rf"(?:\\b[A-Z])?[\\.\\-\\s]?{PAGE_NUMBER_CORE}'
                '(?:\\s*[\\|+])?\\s*$",\n'
                "    re.IGNORECASE,\n"
                ")\n"
            )
        },
    )
    assert page_patterns.scan_page_patterns() == []


def test_unrelated_number_shapes_are_allowed(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_OMB_RE = re.compile(r"\\\\d{4}-\\\\d{2}-\\\\d{2}")\n'
                '_PHONE_RE = re.compile(r"\\\\(\\\\d{3}\\\\) \\\\d{3}-\\\\d{4}")\n'
                '_ZIP_RE = re.compile(r"\\\\d{5}(?:-\\\\d{4})?")\n'
                '_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data'
                '/123/0001193125/page"\n'
            )
        },
    )
    assert page_patterns.scan_page_patterns() == []
