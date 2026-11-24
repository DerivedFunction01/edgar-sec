"""The money-patterns scanner: the money, scale, and percent lines.
A private amount recognizer makes two modules disagree about what a figure
is; a private scale vocabulary makes them disagree about what it is worth.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners.patterns import money_patterns


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _messages(findings: list) -> list[str]:
    return [f.message for f in findings]


# --- The money line: positive fixtures are the production copies verbatim ---


def test_flags_toc_gate_amount_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": '_AMOUNT_RE = re.compile(r"\\d,\\d{3}|\\d+\\.\\d+")\n'
        },
    )
    findings = money_patterns.scan_money_patterns()
    assert [f.path for f in findings] == ["edgar_sec/engine/thing.py"]
    assert _messages(findings) == ["private money-amount recognizer outside its home"]


def test_flags_decimal_figure_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": '_DECIMAL_RE = re.compile(r"\\d+\\.\\d{2,}")\n'},
    )
    assert money_patterns.scan_money_patterns()


def test_flags_grouped_figure_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": '_GROUPED_RE = re.compile(r"\\d{1,3}(?:,\\d{3})+")\n'
        },
    )
    assert money_patterns.scan_money_patterns()


def test_flags_currency_amount_core_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_CURRENCY_AMOUNT_RE = re.compile(r"\\$\\s*\\d[\\d,]*(?:\\.\\d+)?")\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns()


def test_flags_numeric_fragment_core_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_RE_NUMERIC_FRAGMENT = re.compile(r"^\\$?\\s?\\(?-?\\d[\\d,]*(\\.\\d+)?\\)?\\s?%?$")\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns()


def test_flags_bracket_spelled_core_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'TOKEN_RE = re.compile(r"^\\s*([0-9][0-9,]*(?:\\.[0-9]+)?)\\s*$")\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns()


def test_flags_minimum_length_amount_core_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_AMOUNT_RE = re.compile(r"\\$\\s*([0-9][0-9,]{2,}(?:\\.[0-9]{2})?)")\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns()


# --- The money line: homes and compositions are allowed ---


def test_allows_the_numeric_home(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/numeric_cells.py": (
                'NUMERIC_TOKEN_RE = re.compile(r"[0-9][0-9,]*(?:\\.[0-9]+)?")\n'
                'GROUPED_AMOUNT_RE = re.compile(r"\\d{1,3}(?:,\\d{3})+")\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns() == []


def test_allows_import_and_composition_of_the_homed_core(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "from edgar_sec.engine.tables.numeric_cells import NUMERIC_TOKEN_RE\n"
                '_AMOUNT_RE = re.compile(rf"\\$\\s*{NUMERIC_TOKEN_RE.pattern}")\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns() == []


def test_ignores_tests(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"tests/test_thing.py": '_DECIMAL_RE = re.compile(r"\\d+\\.\\d{2,}")\n'},
    )
    assert money_patterns.scan_money_patterns() == []


# --- The scale line: positive fixtures are the production copies verbatim ---


def test_flags_scale_alternation_list_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "_FLOAT_UNIT = rf\"(?:{build_alternation(['billion', 'million', 'thousand'], auto_escape=True)})?\"\n"
            )
        },
    )
    findings = money_patterns.scan_money_patterns()
    assert _messages(findings) == ["private scale vocabulary outside its home"]


def test_flags_scale_alternation_bar_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'SCALE_WORDS = r"(?:thousand|million|billion)"\n'
            )
        },
    )
    findings = money_patterns.scan_money_patterns()
    assert _messages(findings) == ["private scale vocabulary outside its home"]


def test_flags_scale_label_string_match_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'def skip(text):\n    return "in thousands" in text or "in millions" in text\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns()


def test_flags_scale_label_regex_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'LABEL_RE = re.compile(r"in\\s+thousands", re.IGNORECASE)\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns()


def test_allows_the_scale_home(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/patterns.py": (
                'SCALE_PATTERNS = ((re.compile(r"in\\s+thousands", re.IGNORECASE), "thousands"),)\n'
                'SCALE_SUFFIX_ALT = build_alternation(("thousand", "million"))\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns() == []


def test_allows_scale_multiplier_data(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_SCALE_MULTIPLIERS = {\n    "thousand": 1_000,\n    "million": 1_000_000,\n}\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns() == []


# --- The percent line: positive fixtures are the production copies verbatim ---


def test_flags_bare_percent_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_RE_BARE_PERCENT = re.compile(r"^[+-]?\\d+(?:\\.\\d+)?%$")\n'
            )
        },
    )
    findings = money_patterns.scan_money_patterns()
    assert _messages(findings) == ["private percent recognizer outside its home"]


def test_flags_literal_percent_owner_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '("ten_percent", re.compile(r"(?<![\\w])10\\s*%\\s*Owner(?![\\w])", re.IGNORECASE)),\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns()


def test_flags_percent_sign_alternation_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": '    ("%", r"percent\\b"),\n'},
    )
    assert money_patterns.scan_money_patterns()


def test_flags_unit_class_percent_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_UNIT_RE = re.compile(r"^([+-]?\\d+(?:\\.\\d+)?)\\s*([a-zA-Z%]*)$")\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns()


def test_flags_tokenizer_percent_tail_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '    r"[A-Za-z]+(?:\'[A-Za-z]+)?|\\d+(?:,\\d{3})*(?:\\.\\d+)?%?|[^\\w\\s]"\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns()


def test_allows_the_percent_home(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/forms/common/values/numbers.py": (
                'SCHEMA_PERCENT_RE = re.compile(r"(?:%|\\s+percent)\\s*$")\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns() == []


def test_allows_plain_percent_text(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'LABEL = "100% complete"\n'
                'FMT = "%.2f%%"\n'
                'STYLE = "width:50%"\n'
                "# growth of 50% year over year\n"
            )
        },
    )
    assert money_patterns.scan_money_patterns() == []


def test_allows_the_word_percent_without_a_shape(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "    percent_of_net_assets: str | None = None\n"
                '    "percent of class represented",\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns() == []


# --- Negative fixtures: allowlisted format shapes neither rule may catch ---


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
    assert money_patterns.scan_money_patterns() == []


def test_allows_phone_numbers(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'PHONE = "(212) 555-0134"\n'
                'PHONE_RE = re.compile(r"\\(\\d{3}\\)\\s*\\d{3}-\\d{4}")\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns() == []


def test_allows_zip_plus_four(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'ZIP = "12345-6789"\nZIP_RE = re.compile(r"^\\d{5}(?:-\\d{4})?$")\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns() == []


def test_allows_archive_and_feed_date_formats(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'ISO_RE = re.compile(r"\\d{4}-\\d{2}-\\d{2}")\n'
                'US_RE = re.compile(r"\\d{1,2}/\\d{1,2}/\\d{4}")\n'
                'STAMP_FMT = "%Y-%m-%dT%H:%M:%S"\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns() == []


def test_allows_sec_url_paths(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                'ARCHIVE = "/Archives/edgar/data/1234567/0001234567-24-000001-index.html"\n'
                'ACCESSION_RE = re.compile(r"\\d{10}-\\d{2}-\\d{6}")\n'
                'BROWSE = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1234567"\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns() == []


def test_proposal_number_recognizer_is_sanctioned(synthetic_repo: Path) -> None:
    # Proposal numbers, not amounts (coordinator ruling).
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/forms/form_npx/ascii_parser.py": (
                '_PROPOSAL_NO_RE = re.compile(r"^\\\\d+\\\\.\\\\d+$")\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns() == []


def test_percent_mark_membership_data_is_sanctioned(synthetic_repo: Path) -> None:
    # Literal membership data, not a recognizer (coordinator ruling).
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/extraction/form_tests/percentage_form.py": (
                'marked = cells[index + 1].strip() in ("%", "percent")\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns() == []


def test_pension_routed_scale_datum_is_sanctioned(synthetic_repo: Path) -> None:
    # Priced host-vocabulary datum of the determination instrument,
    # sanctioned by name (coordinator ruling).
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/extraction/pension/pension_routed_specs.py": (
                'HOST_SUPP_VOCAB = {"deferred_tax": frozenset({"in thousands"})}\n'
            )
        },
    )
    assert money_patterns.scan_money_patterns() == []


def test_pension_routed_sanction_remainder_still_fires(synthetic_repo: Path) -> None:
    # Per-literal remainder: the sanction covers the one named datum;
    # any further scale label in the same file still fires.
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/extraction/pension/pension_routed_specs.py": (
                'HOST_SUPP_VOCAB = {"deferred_tax": frozenset({"in thousands"})}\n'
                'OTHER = {"in millions"}\n'
            )
        },
    )
    findings = money_patterns.scan_money_patterns()
    assert [f.path for f in findings] == [
        "edgar_sec/engine/tables/extraction/pension/pension_routed_specs.py"
    ]
    assert _messages(findings) == ["private scale vocabulary outside its home"]
