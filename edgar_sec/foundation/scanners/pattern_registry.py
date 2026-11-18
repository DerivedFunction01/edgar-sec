"""Scanner keeping each recognizer intent in its one homed family.

Flags a registered name outside its home, and a bare year recognizer,
month alternation, any-word month slot, or MONTH_PATTERN recomposition
outside foundation/text/dates.py; allows uses and allowlisted formats.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files
from .lines import finding, is_noise, is_scanner_infrastructure

_DATES_HINT = (
    "use the recognizers from edgar_sec.foundation.text.dates "
    "(YEAR_TOKEN_PATTERN, YEAR_TOKEN_RE, YEAR_TOKEN_SEARCH_RE, "
    "MONTH_PATTERN, MONTH_RE, MONTH_WORD_RE) instead of a private copy"
)

# Modules whose every pattern is a format shape, never a recognizer:
# SEC archive URL formats; OMB control-number formats; the signer-name
# termination slot in document/signatures.py (a named exception).
_FORMAT_ALLOWLIST = {
    "edgar_sec/domain/sec_urls.py",
    "edgar_sec/engine/forms/common/statutory.py",
    "edgar_sec/engine/document/signatures.py",
}

# A bare four-digit recognizer, in either digit spelling.
_YEAR_SHAPE_RE = re.compile(r"\\d\{4\}|\[0-9\]\{4\}")
# A ZIP+4 suffix: the four digits after a five-digit ZIP are a format.
_ZIP_SHAPE_RE = re.compile(r"(?:\\d|\[0-9\])\{5\}[^ ]{0,4}-(?:\\d|\[0-9\])\{4\}")
# A phone tail: a four-digit group after a three-digit group.
_PHONE_SHAPE_RE = re.compile(r"(?:\\d|\[0-9\])\{3(?:,4)?\}.{0,24}?(?:\\d|\[0-9\])\{4\}")
# An ISO or compact date format: the year group is fused to the
# month/day groups, a filename quarter, or an archive path segment.
_ISO_SHAPE_RE = re.compile(
    r"(?:\\d|\[0-9\])\{4\}(?:\)?-[(]?(?:\\d|\[0-9\])\{2\}"
    r"|\)?[(](?:\\d|\[0-9\])\{2\}[)]|\)?q|/|\.nc\.)"
)
# A word class standing in for a month name in a date pattern.
_ANY_WORD_RE = re.compile(r"\[A-Za-z\]\+|\[a-z\]\+|\[A-Z\]\[a-z\]\+")
_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def _year_shape(path: str, line: str) -> str | None:
    if path in _FORMAT_ALLOWLIST:
        return None
    normalized = line.replace("{{", "{").replace("}}", "}")
    match = _YEAR_SHAPE_RE.search(normalized)
    if match is None:
        return None
    if _ZIP_SHAPE_RE.search(normalized) or _PHONE_SHAPE_RE.search(normalized):
        return None
    if _ISO_SHAPE_RE.search(normalized):
        return None
    # A four-digit filename stem (0001.txt) is numbering, not a year.
    if normalized[match.end() : match.end() + 2] == r"\.":
        return None
    return "bare year recognizer (\\d{4}) outside its foundation home"


def _year_vocabulary_shape(path: str, line: str) -> str | None:
    if not re.match(r"^\s*[A-Za-z_]\w*\s*(?::[^=\n]+)?=", line):
        return None
    years = sorted(int(y) for y in re.findall(r"[\"']((?:19|20)\d{2})[\"']", line))
    if len(years) >= 3 and years[-1] - years[0] == len(years) - 1:
        return "hard-coded year vocabulary outside its foundation home"
    return None


def _month_recomposition_shape(path: str, line: str) -> str | None:
    normalized = line.replace("{{", "{").replace("}}", "}")
    if (
        "MONTH_PATTERN" in line
        and "re.compile" in line
        and r"\d{" not in normalized
        and "[0-9]" not in normalized
    ):
        return "private month recognizer composed from MONTH_PATTERN"
    return None


def _any_word_month_shape(path: str, line: str) -> str | None:
    normalized = line.replace("{{", "{").replace("}}", "}")
    if (
        _ANY_WORD_RE.search(normalized)
        and r"\d{1,2}" in normalized
        and (_YEAR_SHAPE_RE.search(normalized) or "YEAR_TOKEN_PATTERN" in line)
    ):
        return "any-word month slot in a date pattern"
    return None


def _month_alternation_shape(path: str, line: str) -> str | None:
    lowered = line.lower()
    named = [name for name in _MONTH_NAMES if name in lowered]
    if "|" in line and len(named) >= 2:
        return "hand-crafted month-name alternation in a regex"
    return None


# The intent registry: one recognizer family, one home, one sanctioned
# surface (its export names). The rule consumes this table as data —
# a new family is a new row (plus its shape detectors), never new code.
RECOGNIZER_FAMILIES: tuple[dict, ...] = (
    {
        "family": "dates",
        "home": "edgar_sec/foundation/text/dates.py",
        "names": (
            "RE_FULL_DATE",
            "FULL_DATE_STUB_RE",
            "RE_DATE_OR_YEAR",
            "TABLE_YEAR_RE",
            "YEAR_TOKEN_PATTERN",
            "YEAR_TOKEN_RE",
            "YEAR_TOKEN_SEARCH_RE",
            "YEAR_IN_TEXT_RE",
            "MONTH_PATTERN",
            "MONTH_RE",
            "MONTH_NAME_RE",
            "MONTH_SUFFIX_RE",
            "MONTH_WORD_RE",
            # The frozen Step 3 instrument's strict variant: the
            # sanctioned narrowed pair; consumers of record are
            # primary_gate.py and core_form_evidence.py (F-S8-2).
            "STRICT_MONTH_PATTERN",
            "STRICT_YEAR_TOKEN_PATTERN",
            "PERIOD_ENDED_PAT",
            "PERIOD_ENDED_RE",
            "REPORTING_PERIOD_CAPTION_RE",
            "REPORTING_PERIOD_FROM_PAT",
            "REPORTING_PERIOD_LABEL_RE",
            "REPORTING_PERIOD_VALUE_RE",
            "REPORT_QUARTER_ENDED_RE",
        ),
        "shapes": (
            _year_shape,
            _year_vocabulary_shape,
            _month_recomposition_shape,
            _any_word_month_shape,
            _month_alternation_shape,
        ),
        "shape_hint": _DATES_HINT,
    },
    {
        "family": "step3-primary-gate",
        "home": "edgar_sec/engine/tables/extraction/primary_gate.py",
        "names": (),
        "literals": (
            # The frozen Step 3 instrument's alternation text: the
            # sanctioned hand-crafted literals; port of record is
            # engine/tables/extraction/primary_gate.py.
            r"(stockholder|shareholder|member|partner)s?'? (equity|deficit)\b",
            r"(stockholder|shareholder|member|partner)s?'? \(deficit\) equity",
            r"unrealized (gain|gains|loss|losses) on\b",
        ),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "pension-routed",
        "home": "edgar_sec/engine/tables/extraction/pension_routed_specs.py",
        "names": (),
        "literals": (
            # The pension routed separator's priced host vocabulary:
            # the sanctioned scale-phrase datum (a deferred_tax census
            # core term of the determination instrument, carried as
            # supporting vocabulary and matched by whole-key equality,
            # never a recognizer); sanctioned by name at the
            # coordinator seat, 2026-11-18, on the term-veto
            # priced-data disposition (2026-11-17).
            "in thousands",
        ),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "word-token",
        "home": "edgar_sec/foundation/text/words.py",
        "names": ("WORD_TOKEN_RE",),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "table-patterns",
        "home": "edgar_sec/engine/tables/patterns.py",
        "names": (
            "SCALE_PATTERNS",
            "UNITS_LABEL_RE",
            "SCALE_SUFFIX_ALT",
            "SCALE_SUFFIX_TOKENS",
        ),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "extraction-normalizers",
        "home": "edgar_sec/engine/tables/extraction/normalize.py",
        "names": ("normalize_text", "normalize_label", "collapse_text"),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "classifier-registry",
        "home": "edgar_sec/engine/tables/extraction/profiles.py",
        "names": (),
        "def_only": ("registry_state", "registry_fingerprint"),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "classifier-work-items",
        "home": "edgar_sec/pipelines/table_classification/planner.py",
        "names": (),
        "def_only": ("work_item_id_for",),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "identity",
        "home": "edgar_sec/domain/identity.py",
        "names": (
            "ACCESSION_DIGITS_RE",
            "ACCESSION_RE",
        ),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "numeric-cells",
        "home": "edgar_sec/engine/tables/numeric_cells.py",
        "names": (
            "AMOUNT_RE",
            "CURRENCY_TOKEN_RE",
            "DECIMAL_AMOUNT_RE",
            "DECIMAL_FIGURE_RE",
            "EUROPEAN_COMMA_DECIMAL_RE",
            "GROUPED_AMOUNT_RE",
            "GROUPED_INTEGER_FRAGMENT",
            "GROUPED_INTEGER_RE",
            "NUMERIC_CELL_RE",
            "UNICODE_NUMERIC_CORE",
            "UNIT_TOKEN_RE",
        ),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "metadata-paths",
        "home": "edgar_sec/pipelines/metadata_sync/paths.py",
        "names": ("CIK_MEMBER_RE",),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "entities",
        "home": "edgar_sec/engine/forms/common/entities.py",
        "names": (
            "COMMISSION_FILE_CAPTION_RE",
            "COMMISSION_FILE_NUMBER_RE",
            "COMMISSION_FILE_TOKEN_RE",
            "CUSIP_RE",
            "IRS_RE",
            "SEC_FILE_NUMBER_RE",
        ),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "text-patterns",
        "home": "edgar_sec/foundation/text/patterns.py",
        "names": (
            "FLOAT_SCALE_ALT",
            "GROUPED_AMOUNT_CORE",
            "ITEM_REFERENCE_CORE",
            "LOOSE_FIGURE_CLASS",
            "PAGE_NUMBER_CORE",
            "PART_REFERENCE_CORE",
            "RE_COLUMN_GAP",
            "RE_NAMED_ENTITY",
            "RE_NON_ALNUM",
            "RE_NUMERIC_ENTITY",
            "RE_PAGE_NUMBER_SUFFIX",
            "RE_PAGE_REFERENCE",
            "RE_TABLE_CLOSE",
            "RE_TABLE_OPEN",
            "RE_TABLE_SPAN",
            "RE_WHITESPACE",
            "RE_WHITESPACE_GAP",
            "RE_WHITESPACE_SPLIT",
        ),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "toc-patterns",
        "home": "edgar_sec/engine/tables/toc/patterns.py",
        "names": (
            "ITEM_HEADING_CORE",
            "ITEM_NUMBER_PATTERN",
            "RE_ITEM_EXACT",
            "RE_ITEM_GROUPED",
            "RE_ITEM_HEADING",
            "RE_ITEM_HEADING_MARKER",
            "RE_ITEM_INLINE",
            "RE_ITEM_OR_NUMBERED_HEADING",
            "RE_ITEM_REFERENCE",
            "RE_ITEM_SECTION_HEADING",
            "RE_NOTE_CAPTION",
            "RE_NOTE_GROUPED",
            "RE_NOTE_HEADING",
            "RE_NOTE_HEADING_CUE",
            "RE_NOTE_REFERENCE",
            "RE_NUMERIC_LABEL",
            "RE_NUMERIC_RUN_IN",
            "RE_PAGE_SUFFIX",
            "RE_PAREN_LABEL",
            "RE_PART_REFERENCE",
            "RE_SECTION_REFERENCE",
            "RE_SEE_REFERENCE",
            "RE_TOC_ITEM",
            "RE_TOC_ITEM_ROW",
            "RE_TOC_LEADER",
        ),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "schema-numbers",
        "home": "edgar_sec/engine/forms/common/numbers.py",
        "names": (
            "PERCENT_OF_CLASS_RE",
            "SCHEMA_CLOSING_PERCENT_RE",
            "SCHEMA_LEADING_PERCENT_RE",
            "SCHEMA_PERCENT_RE",
        ),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "typed-rows",
        "home": "edgar_sec/engine/tables/extraction/typed_rows.py",
        "names": ("TOTAL_ROW_RE",),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "operator-kit",
        "home": "edgar_sec/apps/client/operator_kit.py",
        "names": (
            "artifacts_root",
            "error_result",
            "gather_options",
            "json_native",
            "make_build_specs",
            "make_spec",
        ),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "row-extraction",
        "home": "edgar_sec/engine/forms/common/row_extraction.py",
        "names": (
            "column_spec",
            "row_field",
        ),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "family-scaffold",
        "home": "edgar_sec/engine/forms/common/family_scaffold.py",
        "names": (
            "core_status",
            "element_int",
            "empty_report",
            "first_group",
            "merge_sections",
            "name_before_label",
            "qname",
        ),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "company-cohort",
        "home": "edgar_sec/engine/company_family/cohort.py",
        "names": ("dataset_path",),
        "shapes": (),
        "shape_hint": "",
    },
)

# Derived name -> home view of the registry, kept for readers.
PATTERN_HOMES: dict[str, str] = {
    name: family["home"]
    for family in RECOGNIZER_FAMILIES
    for name in family["names"] + tuple(family.get("def_only", ()))
}

_DEF_RES: dict[str, re.Pattern[str]] = {}
_ASSIGN_RES: dict[str, re.Pattern[str]] = {}


def _is_definition(name: str, line: str) -> bool:
    if name not in _DEF_RES:
        _DEF_RES[name] = re.compile(rf"^def\s+{name}\s*\(")
        _ASSIGN_RES[name] = re.compile(rf"^{name}\s*(?::[^=\n]+)?=(?!=)")
    # A registered name is copied only by a module-level definition:
    # an indented def is a method or a nested function, and an
    # indented assignment is a local, a field, or a keyword
    # argument — uses of the name, never copies of the pattern.
    if line[:1].isspace():
        return False
    return bool(_DEF_RES[name].search(line) or _ASSIGN_RES[name].search(line))


def _module_of(home: str) -> str:
    return home.removesuffix(".py").replace("/", ".")


def _rule(path: str, number: int, line: str) -> ScannerFinding | None:
    for family in RECOGNIZER_FAMILIES:
        if path == family["home"]:
            continue
        named = list(family["names"]) + list(family.get("def_only", ()))
        for name in named:
            if _is_definition(name, line):
                return finding(
                    "pattern-registry",
                    path,
                    number,
                    f"registered pattern {name} defined outside its home",
                    f"import {name} from {_module_of(family['home'])} "
                    "instead of defining a copy",
                )
        for detector in family["shapes"]:
            message = detector(path, line)
            if message is not None:
                return finding(
                    "pattern-registry",
                    path,
                    number,
                    message,
                    family["shape_hint"],
                )
    return None


def _scan_lines(path: str, lines: list[str]) -> list[ScannerFinding]:
    findings: list[ScannerFinding] = []
    for number, line in enumerate(lines, start=1):
        if is_noise(line):
            continue
        found = _rule(path, number, line)
        if found is not None:
            findings.append(found)
    return findings


def scan_pattern_registry() -> list[ScannerFinding]:
    """Flag registered names and recognizer shapes outside their home."""
    findings: list[ScannerFinding] = []
    for path_str in discover_python_files():
        if is_scanner_infrastructure(path_str):
            continue
        try:
            content = Path(path_str).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings += _scan_lines(path_str, content.splitlines())
    return findings


SCANNER = Scanner(
    name="pattern-registry",
    description=(
        "scan for registered pattern names and recognizer shapes "
        "defined outside their one home"
    ),
    run=scan_pattern_registry,
)
