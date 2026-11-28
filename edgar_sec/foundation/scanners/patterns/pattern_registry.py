"""Scanner keeping each recognizer intent in its one homed family.

Flags a registered name outside its home, and a bare year recognizer,
month alternation, any-word month slot, MONTH_PATTERN recomposition, or a
build over a registered vocabulary outside foundation/text/date_patterns.py.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..base import Scanner, ScannerFinding
from ..files import discover_python_files
from ..lines import finding, is_noise, is_scanner_infrastructure

_DATES_HINT = (
    "use the recognizers from edgar_sec.foundation.text.date_patterns "
    "(YEAR_TOKEN_PATTERN, YEAR_TOKEN_RE, YEAR_TOKEN_SEARCH_RE, "
    "MONTH_PATTERN, MONTH_RE, MONTH_WORD_RE) instead of a private copy"
)

# Modules whose every pattern is a format shape, never a recognizer:
# SEC archive URL formats; OMB control-number formats; the signer-name
# termination slot in document/signatures.py (a named exception).
_FORMAT_ALLOWLIST = {
    "edgar_sec/domain/sec_urls.py",
    "edgar_sec/engine/forms/common/phrases/statutory.py",
    "edgar_sec/engine/document/signatures.py",
    "edgar_sec/foundation/text/date_formats.py",
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

# The date home's registered data vocabularies: building a recognizer
# over one is the offence the literal shapes cannot see; consuming a
# homed compiled export (MONTH_WORD_RE) carries no build verb.
_VOCABULARY_IDENTIFIERS = ("MONTH_NAMES", "MONTH_ALIASES")
_BUILD_VERB_RE = re.compile(
    r"build_alternation\s*\(|[\"']\|[\"']\s*\.join\s*\(|re\.compile\s*\("
)
# Registered membership sets for the literal-list equivalence shape:
# the home's twelve month names (_MONTH_NAMES omits "may", tuned for
# the alternation shape) and its ordinal suffixes.
_MONTH_MEMBERSHIP = frozenset(_MONTH_NAMES) | {"may"}
_ORDINAL_MEMBERSHIP = frozenset({"st", "nd", "rd", "th"})
_MEMBERSHIP_SETS = (_MONTH_MEMBERSHIP, _ORDINAL_MEMBERSHIP)
_LITERAL_LIST_RE = re.compile(r"build_alternation\s*\(\s*\[([^\]]*)\]")
_LITERAL_ITEM_RE = re.compile(r"[\"']([^\"']*)[\"']")


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


def _year_recomposition_shape(path: str, line: str) -> str | None:
    if "YEAR_TOKEN_PATTERN" not in line or "re.compile" not in line:
        return None
    normalized = line.replace("{{", "{").replace("}}", "}")
    if re.search(r"re\.compile\(\s*YEAR_TOKEN_PATTERN\s*[,\)]", normalized):
        return "private year recognizer compiled from YEAR_TOKEN_PATTERN"
    match = re.search(r"re\.compile\(\s*rf?[\"']([^\"']*)[\"']", normalized)
    if match is None:
        return None
    residue = match.group(1).replace("{YEAR_TOKEN_PATTERN}", "")
    if residue and all(char in "\\b(?:)" for char in residue):
        return "private year recognizer composed from YEAR_TOKEN_PATTERN"
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


def _is_vocabulary_build(line: str) -> bool:
    if not _BUILD_VERB_RE.search(line):
        return False
    return any(
        re.search(rf"\b{identifier}\b", line) for identifier in _VOCABULARY_IDENTIFIERS
    )


def _vocabulary_build_shape(path: str, line: str) -> str | None:
    if path in _FORMAT_ALLOWLIST:
        return None
    if _is_vocabulary_build(line):
        return (
            "private recognizer built over a registered vocabulary "
            "(MONTH_NAMES, MONTH_ALIASES)"
        )
    return None


def _membership_equivalence_shape(path: str, line: str) -> str | None:
    if path in _FORMAT_ALLOWLIST:
        return None
    match = _LITERAL_LIST_RE.search(line)
    if match is None:
        return None
    members = frozenset(
        item.lower() for item in _LITERAL_ITEM_RE.findall(match.group(1))
    )
    if members in _MEMBERSHIP_SETS:
        return "literal list duplicating a registered vocabulary's membership"
    return None


# The intent registry: one recognizer family, one home, one sanctioned
# surface (its export names). The rule consumes this table as data —
# a new family is a new row (plus its shape detectors), never new code.
RECOGNIZER_FAMILIES: tuple[dict, ...] = (
    {
        "family": "dates",
        "home": "edgar_sec/foundation/text/date_patterns.py",
        "names": (
            "RE_FULL_DATE",
            "FULL_DATE_STUB_RE",
            "MONTH_NAME_WORD_RE",
            "FULL_DATE_ANY_RE",
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
            # The frozen Step 3 instrument's strict month variant
            # (full month names only); consumers of record are
            # primary_gate.py and core_form_evidence.py (F-S8-2).
            "STRICT_MONTH_PATTERN",
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
            _year_recomposition_shape,
            _month_recomposition_shape,
            _any_word_month_shape,
            _month_alternation_shape,
            _vocabulary_build_shape,
            _membership_equivalence_shape,
        ),
        "shape_hint": _DATES_HINT,
    },
    {
        "family": "step3-primary-gate",
        "home": "edgar_sec/engine/tables/extraction/seats/primary_gate.py",
        "names": (),
        "literals": (
            # The frozen Step 3 instrument's alternation text: the
            # sanctioned hand-crafted literals; port of record is
            # engine/tables/extraction/seats/primary_gate.py.
            r"(stockholder|shareholder|member|partner)s?'? (equity|deficit)\b",
            r"(stockholder|shareholder|member|partner)s?'? \(deficit\) equity",
            r"unrealized (gain|gains|loss|losses) on\b",
        ),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "pension-routed",
        "home": "edgar_sec/engine/tables/extraction/pension/pension_routed_specs.py",
        "names": (),
        "literals": (
            # The pension routed separator's priced host vocabulary:
            # the sanctioned scale-phrase datum (a deferred_tax census
            # core term of the determination instrument, carried as
            # supporting vocabulary and matched by whole-key equality,
            # never a recognizer); sanctioned by name at the
            # coordinator seat, on the term-veto
            # priced-data disposition.
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
        "home": "edgar_sec/engine/tables/extraction/core/text/normalize.py",
        "names": ("normalize_text", "normalize_label", "collapse_text"),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "classifier-registry",
        "home": "edgar_sec/engine/tables/extraction/core/subjects/profiles.py",
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
        "family": "table-tokens",
        "home": "edgar_sec/engine/tables/tokens.py",
        "names": (
            "CLOSING_DELIMITERS",
            "PREFIX_TOKENS",
            "RANGE_MARKERS",
            "SUFFIX_TOKENS",
            "is_prefix_token",
            "is_range_marker",
            "is_suffix_token",
            "numeric_cell_starts",
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
        "home": "edgar_sec/engine/forms/common/identity/entities.py",
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
        "home": "edgar_sec/engine/forms/common/values/numbers.py",
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
        "home": "edgar_sec/engine/tables/extraction/core/typed_rows.py",
        "names": ("TOTAL_ROW_RE",),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "operator-kit",
        "home": "edgar_sec/apps/client/operator/operator_kit.py",
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
        "home": "edgar_sec/engine/forms/common/fields/row_extraction.py",
        "names": (
            "column_spec",
            "row_field",
        ),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "family-scaffold",
        "home": "edgar_sec/engine/forms/common/scaffold/family_scaffold.py",
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


_DATES_HOME = next(
    family["home"] for family in RECOGNIZER_FAMILIES if family["family"] == "dates"
)
_TAINT_ASSIGN_RE = re.compile(r"^([A-Za-z_]\w*)\s*(?::[^=\n]+)?=(?!=)")
_COMPILE_RE = re.compile(r"re\.compile\s*\(")


class _VocabularyTaint:
    """Per-file taint state for the dates family: names assigned from
    a vocabulary build, and the paren depth of an open re.compile."""

    def __init__(self, path: str) -> None:
        self._active = path != _DATES_HOME and path not in _FORMAT_ALLOWLIST
        self._tainted: set[str] = set()
        self._compile_depth = 0
        self._compile_flagged = False

    def step(self, path: str, number: int, line: str) -> ScannerFinding | None:
        if not self._active:
            return None
        found = self._compile_step(path, number, line)
        assign = _TAINT_ASSIGN_RE.match(line)
        if assign is not None and _is_vocabulary_build(line):
            self._tainted.add(assign.group(1))
        return found

    def _compile_step(self, path: str, number: int, line: str) -> ScannerFinding | None:
        if self._compile_depth == 0 and not _COMPILE_RE.search(line):
            return None
        if self._compile_depth == 0:
            self._compile_flagged = False
        found = None
        if not self._compile_flagged:
            for name in sorted(self._tainted):
                if re.search(rf"\b{re.escape(name)}\b", line):
                    found = finding(
                        "pattern-registry",
                        path,
                        number,
                        f"private recognizer compiled from {name}, "
                        "a build over a registered vocabulary",
                        _DATES_HINT,
                    )
                    self._compile_flagged = True
                    break
        self._compile_depth = max(
            0, self._compile_depth + line.count("(") - line.count(")")
        )
        return found


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
    taint = _VocabularyTaint(path)
    for number, line in enumerate(lines, start=1):
        if is_noise(line):
            continue
        found = _rule(path, number, line)
        tainted = taint.step(path, number, line)
        if found is None:
            found = tainted
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
