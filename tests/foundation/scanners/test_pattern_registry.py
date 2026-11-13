"""The pattern-registry scanner.
A registered pattern defined in a second module drifts from its home, so
consumers stop describing the same concept.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import date_patterns, pattern_registry


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_flags_scale_patterns_defined_outside_patterns_home(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'SCALE_PATTERNS = (("in thousands",),)\n'},
    )
    findings = pattern_registry.scan_pattern_registry()
    assert [f.path for f in findings] == ["edgar_sec/engine/thing.py"]


def test_flags_units_label_defined_outside_patterns_home(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'UNITS_LABEL_RE = "x"\n'},
    )
    assert pattern_registry.scan_pattern_registry()


def test_flags_scale_definition_in_the_corpus_tool(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "tools/table_extraction_corpus/extract.py": (
                'SCALE_PATTERNS = (("in thousands",),)\n'
            )
        },
    )
    findings = pattern_registry.scan_pattern_registry()
    assert [f.path for f in findings] == ["tools/table_extraction_corpus/extract.py"]


def test_flags_normaliser_function_defined_outside_its_home(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": "def normalize_text(text):\n    return text\n"},
    )
    assert pattern_registry.scan_pattern_registry()


def test_flags_normaliser_function_defined_in_the_corpus_tool(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "tools/table_extraction_corpus/coverage.py": (
                "def collapse_text(text):\n    return text\n"
            )
        },
    )
    assert pattern_registry.scan_pattern_registry()


def test_allows_definitions_in_their_registered_homes(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/patterns.py": (
                'SCALE_PATTERNS = (("in thousands",),)\nUNITS_LABEL_RE = "x"\n'
            ),
            "edgar_sec/engine/tables/extraction/normalize.py": (
                "def normalize_text(text):\n    return text\n"
                "def normalize_label(text):\n    return text\n"
                "def collapse_text(text):\n    return text\n"
            ),
        },
    )
    assert pattern_registry.scan_pattern_registry() == []


def test_a_home_for_one_name_is_not_a_home_for_another(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/patterns.py": (
                "def normalize_text(text):\n    return text\n"
            )
        },
    )
    assert pattern_registry.scan_pattern_registry()


def test_allows_imports_and_uses_anywhere(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "from edgar_sec.engine.tables.patterns import SCALE_PATTERNS\n"
                "def scale_in(text):\n"
                "    for pattern, unit in SCALE_PATTERNS:\n"
                "        pass\n"
            ),
            "tools/table_extraction_corpus/extract.py": (
                "from edgar_sec.engine.tables.patterns import SCALE_PATTERNS\n"
                "def scale(text):\n"
                "    return normalize_text(text)\n"
            ),
        },
    )
    assert pattern_registry.scan_pattern_registry() == []


def test_ignores_tests(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"tests/test_thing.py": 'SCALE_PATTERNS = (("in thousands",),)\n'},
    )
    assert pattern_registry.scan_pattern_registry() == []


def test_flags_full_date_defined_outside_dates_home(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'RE_FULL_DATE = "x"\n'},
    )
    assert pattern_registry.scan_pattern_registry()


def test_flags_year_token_defined_outside_dates_home(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'YEAR_TOKEN_RE = "x"\n'},
    )
    assert pattern_registry.scan_pattern_registry()


def test_flags_scale_patterns_defined_in_the_corpus_tool(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {"tools/table_extraction_corpus/label.py": 'SCALE_PATTERNS = "x"\n'},
    )
    findings = pattern_registry.scan_pattern_registry()
    assert [f.path for f in findings] == ["tools/table_extraction_corpus/label.py"]


def test_allows_seed_definitions_in_their_foundation_homes(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/patterns.py": (
                'SCALE_PATTERNS = "x"\nUNITS_LABEL_RE = "x"\n'
            ),
            "edgar_sec/foundation/text/words.py": 'WORD_TOKEN_RE = "x"\n',
            "edgar_sec/foundation/text/dates.py": (
                'RE_FULL_DATE = "x"\nYEAR_TOKEN_PATTERN = "x"\n'
                'YEAR_TOKEN_RE = "x"\nYEAR_TOKEN_SEARCH_RE = "x"\n'
                'YEAR_IN_TEXT_RE = "x"\n'
            ),
        },
    )
    assert pattern_registry.scan_pattern_registry() == []


def test_flags_word_token_defined_outside_words_home(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'WORD_TOKEN_RE = "x"\n'},
    )
    assert pattern_registry.scan_pattern_registry()


def test_allows_word_token_annotated_definition_in_words_home(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/foundation/text/words.py": 'WORD_TOKEN_RE: "Pattern" = "x"\n'},
    )
    assert pattern_registry.scan_pattern_registry() == []


def test_date_patterns_protections_still_fire_beside_the_registry(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'MONTH_NAMES = ("january", "february")\n'},
    )
    assert date_patterns.scan_date_patterns()
    assert pattern_registry.scan_pattern_registry() == []
