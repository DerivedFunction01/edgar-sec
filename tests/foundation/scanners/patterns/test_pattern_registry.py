"""The pattern-registry scanner.
A registered pattern defined in a second module drifts from its home, so
consumers stop describing the same concept.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from edgar_sec.foundation.scanners.patterns import date_patterns, pattern_registry


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
            "edgar_sec/tools/table_extraction_corpus/extract.py": (
                'SCALE_PATTERNS = (("in thousands",),)\n'
            )
        },
    )
    findings = pattern_registry.scan_pattern_registry()
    assert [f.path for f in findings] == [
        "edgar_sec/tools/table_extraction_corpus/extract.py"
    ]


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
            "edgar_sec/tools/table_extraction_corpus/coverage.py": (
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
            "edgar_sec/engine/tables/extraction/core/text/normalize.py": (
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
            "edgar_sec/tools/table_extraction_corpus/extract.py": (
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
        {"edgar_sec/tools/table_extraction_corpus/label.py": 'SCALE_PATTERNS = "x"\n'},
    )
    findings = pattern_registry.scan_pattern_registry()
    assert [f.path for f in findings] == [
        "edgar_sec/tools/table_extraction_corpus/label.py"
    ]


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
            "edgar_sec/foundation/text/date_patterns.py": (
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


def test_keyword_arguments_are_not_definitions(synthetic_repo: Path) -> None:
    """The union-formation shapes: registered names passed as keyword
    arguments (or held in indented locals) are uses, not copies."""
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "def build(state, pattern):\n"
                "    request = PlanRequest(\n"
                "        registry_state=state,\n"
                "        MONTH_RE=pattern,\n"
                "    )\n"
                "    registry_state = state\n"
                "    return request\n"
            ),
            "edgar_sec/engine/tables/extraction/core/subjects/profiles.py": (
                "def registry_state():\n    return {}\n"
            ),
        },
    )
    assert pattern_registry.scan_pattern_registry() == []


def test_method_def_of_a_registered_name_is_not_a_copy(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "class Thing:\n    def qname(self, tag):\n        return tag\n"
            )
        },
    )
    assert pattern_registry.scan_pattern_registry() == []


def test_nested_def_of_a_registered_name_is_not_a_copy(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "def build():\n"
                "    def qname(tag):\n"
                "        return tag\n"
                "    return qname\n"
            )
        },
    )
    assert pattern_registry.scan_pattern_registry() == []


def test_indented_local_assignment_is_not_a_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "def build(row):\n    qname = row['concept_qname']\n    return qname\n"
            )
        },
    )
    assert pattern_registry.scan_pattern_registry() == []


def test_dataclass_field_named_like_a_registered_helper_is_not_a_copy(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "from dataclasses import dataclass\n"
                "\n"
                "@dataclass\n"
                "class Options:\n"
                "    artifacts_root: str = ''\n"
            )
        },
    )
    assert pattern_registry.scan_pattern_registry() == []


def test_private_def_of_a_def_only_name_is_flagged(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": "def registry_state():\n    return {}\n"},
    )
    findings = pattern_registry.scan_pattern_registry()
    assert len(findings) == 1
    assert "registry_state" in findings[0].message


def test_flags_registry_fingerprint_defined_outside_profiles_home(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": "def registry_fingerprint():\n    pass\n"},
    )
    assert pattern_registry.scan_pattern_registry()


def test_flags_work_item_id_defined_outside_planner_home(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": "def work_item_id_for():\n    pass\n"},
    )
    assert pattern_registry.scan_pattern_registry()


def test_module_level_assignment_of_a_def_only_name_is_flagged(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": "registry_state = build_state()\n"},
    )
    findings = pattern_registry.scan_pattern_registry()
    assert len(findings) == 1
    assert "registry_state" in findings[0].message


def test_family_table_is_consumed_as_data(
    synthetic_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new family is a new registry row: its names and shapes are
    enforced with no new rule code."""
    toy = {
        "family": "toy",
        "home": "edgar_sec/foundation/text/toy.py",
        "names": ("TOY_RE",),
        "shapes": (lambda path, line: "toy shape" if "TOYSHAPE" in line else None,),
        "shape_hint": "use TOY_RE from the toy home",
    }
    monkeypatch.setattr(
        pattern_registry,
        "RECOGNIZER_FAMILIES",
        pattern_registry.RECOGNIZER_FAMILIES + (toy,),
    )
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": 'TOY_RE = "x"\n_A = "TOYSHAPE"\n',
            "edgar_sec/foundation/text/toy.py": 'TOY_RE = "x"\n',
        },
    )
    findings = pattern_registry.scan_pattern_registry()
    assert [f.path for f in findings] == [
        "edgar_sec/engine/thing.py",
        "edgar_sec/engine/thing.py",
    ]


def test_flags_month_registered_names_defined_outside_dates_home(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'MONTH_RE = "x"\nMONTH_WORD_RE = "y"\n'},
    )
    assert len(pattern_registry.scan_pattern_registry()) == 2


def test_flags_bare_year_recognizer_under_a_new_private_name(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": '_YEAR_RE = re.compile(r"\\b\\d{4}\\b")\n'},
    )
    findings = pattern_registry.scan_pattern_registry()
    assert [f.path for f in findings] == ["edgar_sec/engine/thing.py"]
    assert "bare year recognizer" in findings[0].message


def test_flags_bare_year_recognizer_in_fstring_and_bracket_spellings(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_A = re.compile(rf"^\\d{{4}}$")\n_B = re.compile(r"^[0-9]{4}$")\n'
            )
        },
    )
    assert len(pattern_registry.scan_pattern_registry()) == 2


def test_flags_hard_coded_year_vocabulary(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_YEAR_TOKENS = ("2022", "2023", "2024", "2025")\n'
                '_ONE_YEAR = ("2024",)\n'
            )
        },
    )
    findings = pattern_registry.scan_pattern_registry()
    assert len(findings) == 1
    assert "year vocabulary" in findings[0].message


def test_flags_month_pattern_recomposition_under_a_private_name(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_MONTH_RE = re.compile(rf"\\b(?:{MONTH_PATTERN})\\b", re.IGNORECASE)\n'
            )
        },
    )
    findings = pattern_registry.scan_pattern_registry()
    assert len(findings) == 1
    assert "MONTH_PATTERN" in findings[0].message


def test_flags_any_word_month_slot_in_a_date_pattern(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_DATE = r"([a-z]+ \\d{1,2}, \\d{4})"\n'
                '_OTHER = rf"([A-Za-z]+ \\d{{1,2}}, '
                '(?:{YEAR_TOKEN_PATTERN}))"\n'
            )
        },
    )
    assert len(pattern_registry.scan_pattern_registry()) == 2


def test_flags_hand_crafted_month_name_alternation(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_M = re.compile(r"(?:january|february|march)")\n'
            )
        },
    )
    assert pattern_registry.scan_pattern_registry()


def test_allows_registry_and_work_item_definitions_in_their_homes(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/extraction/core/subjects/profiles.py": (
                "def registry_fingerprint():\n    pass\n"
            ),
            "edgar_sec/pipelines/table_classification/planner.py": (
                "def work_item_id_for():\n    pass\n"
            ),
        },
    )
    assert pattern_registry.scan_pattern_registry() == []


def test_allows_format_shapes_and_homed_compositions(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_ZIP = re.compile(r"\\d{5}(?:-\\d{4})?")\n'
                '_PHONE = re.compile(r"\\d{3}[-.\\s]\\d{3}[-.\\s]\\d{4}")\n'
                '_DATED = re.compile(r"^(\\d{4})-\\d{2}-\\d{2}$")\n'
                '_COMPACT = re.compile(r"^(\\d{4})(\\d{2})(\\d{2})$")\n'
                '_NUMBERED = re.compile(r"\\d{4}\\.[A-Za-z0-9]+\\Z")\n'
                "_NAMED = re.compile(\n"
                '    rf"(?:{MONTH_PATTERN}) \\d{{1,2}}, '
                '(?:{YEAR_TOKEN_PATTERN})")\n'
            ),
            "edgar_sec/domain/sec_urls.py": (
                '_RSS = re.compile(r"^/Archives/edgar/monthly/'
                'xbrlrss-\\d{4}-\\d{2}\\.xml$")\n'
            ),
            "edgar_sec/engine/forms/common/phrases/statutory.py": (
                '_OMB = re.compile(r"\\b3235-\\d{4}\\b")\n'
            ),
            "edgar_sec/foundation/text/date_patterns.py": (
                '_FMT = re.compile(r"(?P<year>\\d{4})")\n'
            ),
        },
    )
    assert pattern_registry.scan_pattern_registry() == []


def _module_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_every_registered_name_is_defined_in_its_home() -> None:
    # Registry integrity: a registered name its home does not define is
    # enforcement over a surface that does not exist — the scanner flags
    # copies of it while the home itself carries nothing to compose from.
    # The pin is the empty remainder: every registered name is defined at
    # module level in its stated home.
    root = Path(pattern_registry.__file__).parents[4]
    undefined = []
    for family in pattern_registry.RECOGNIZER_FAMILIES:
        defined = _module_level_names(root / family["home"])
        for name in family["names"] + tuple(family.get("def_only", ())):
            if name not in defined:
                undefined.append(f"{family['family']}:{name}")
    assert undefined == [], (
        "registered names not defined at module level in their home: "
        + ", ".join(sorted(undefined))
    )
