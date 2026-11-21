"""Scanner routing identifier recognition through its homes.
Flags a private accession, CIK, commission file-number, EIN, registration,
or CUSIP recognizer spelled as pattern text outside its home; allows homed
compositions, SQL/URL format shapes, and the sanctioned sites below.
"""

from __future__ import annotations

import re

from .base import Scanner, ScannerFinding
from .lines import Rule, finding, scan_text_rule

# An accession core in either digit spelling: `\d{10}-\d{2}-\d{6}`.
_ACCESSION_CORE_RE = re.compile(
    r"(?:\\d|\[0-9\])\{10\}-(?:\\d|\[0-9\])\{2\}-(?:\\d|\[0-9\])\{6\}"
)

# The unhyphenated accession digits: `\d{18}` in either digit spelling.
_ACCESSION_DIGITS_RE = re.compile(r"(?:\\d|\[0-9\])\{18\}")

# A compile bound to an accession name, whatever its literal shape: the
# loose label captures are accession recognizers by name and intent.
_ACCESSION_DEF_RE = re.compile(r"ACCESSION\w*\s*(?::[^=\n]+)?=\s*re\.compile")

# The bulk member-name CIK capture: `CIK(\d{10})` in either digit spelling.
_CIK_MEMBER_RE = re.compile(r"CIK\((?:\\d|\[0-9\])\{10\}\)")

# The commission caption with its number/no alternation, in literal-space
# or `\s+` spelling: `commission file (?:numbers?|no...` and kin.
_COMMISSION_RE = re.compile(
    r"commission(?:\\s\+| )file(?:\\s\+| )\(\?:(?:numbers?\?|number|no)",
    re.IGNORECASE,
)

# The EIN hyphenated core: `\d{2}-\d{7}` in either digit spelling.
_EIN_RE = re.compile(r"(?:\\d|\[0-9\])\{2\}-(?:\\d|\[0-9\])\{7\}")

# A registration-number value: `\d{3}-\d{3,}` or the `(?:333|33)` prefix.
_REGISTRATION_RE = re.compile(
    r"(?:\\d|\[0-9\])\{3\}-(?:\\d|\[0-9\])\{3,\}|\(\?:333\|33\)"
)

# The CUSIP value class: `[0-9A-Z*@#]{9}` or its `{8,9}` clean form.
_CUSIP_RE = re.compile(r"\[0-9A-Z\*@#\]\{(?:9|8,9)\}")

# The CUSIP caption: `cusip (?:number|no...` in either spacing spelling.
_CUSIP_LABEL_RE = re.compile(r"cusip(?:\\s\+| )\(\?:number\|no", re.IGNORECASE)

# The modules that own the identifier vocabularies.
_ALLOWED_PREFIXES = (
    "edgar_sec/domain/identity.py",
    "edgar_sec/engine/forms/common/entities.py",
    "edgar_sec/pipelines/metadata_sync/paths.py",
)

# Database-dialect shapes and SEC URL paths are format shapes, not
# Python recognizer definitions (the census counting rule's allowlist).
_SQL_MARKERS = ("regexp_matches", "regexp_full_match")
_URL_MARKER = "/Archives/edgar/data/"

# Sanctioned sites: a flagged shape that stands as a priced divergence
# or a format shape, exempted by file and content fragment.
_SANCTIONED_SITES = (
    # Accession label captures (parser_atom, feed_inventory x2): the
    # token is validated by AccessionNumber.from_any, whose accepted
    # set (any hyphen placement over 18 digits) no strict-core
    # composition reproduces; composing flips served headers whose
    # hyphenation is non-canonical (Wave 2 priced stop, 2026-11-15).
    ("edgar_sec/engine/feeds/parser_atom.py", "_ACCESSION_RE"),
    (
        "edgar_sec/pipelines/document_acquisition/feed/feed_inventory.py",
        "_ACCESSION_RE",
    ),
    # Accession digits in ASCII spelling: re-pointing to the home's
    # `\d{18}` widens the verdict to Unicode decimal digits in a
    # catalog contract check (Wave 2 priced stop, 2026-11-15).
    ("edgar_sec/pipelines/document_planning/catalog_scope.py", "_ACCESSION_RE"),
    # A complete-submission filename shape (accession + ".txt"), a
    # document-numbering format shape, not a recognizer definition.
    ("edgar_sec/pipelines/document_planning/matching.py", "_COMPLETE_SUBMISSION_NAME"),
    # The submissions shard member name: a sibling shape of the homed
    # main member name, defined once for its own archive.
    ("edgar_sec/pipelines/metadata_sync/core/planner.py", "_SHARD_MEMBER_RE"),
    # Form 11-K's caption is singular-only ("number", never
    # "numbers"); the homed caption's plural widens its cover
    # verdicts (Wave 2 priced stop, 2026-11-15).
    ("edgar_sec/engine/forms/form_11k/analysis.py", "commission file (?:number|no"),
    # Form 425's caption allows whitespace runs between the caption
    # words; the homed caption's literal spaces narrow it (Wave 2
    # priced stop, 2026-11-15).
    ("edgar_sec/engine/forms/form_425/analysis.py", "_FILE_CAPTION_RE"),
    # Form SD's EIN-shaped anchor is the hyphenated alternative only;
    # the homed IRS_RE's bare 9-digit alternative would anchor file
    # numbers beside any 9-digit run (Wave 2 priced stop, 2026-11-15).
    ("edgar_sec/engine/forms/form_sd/analysis.py", "_EIN_RE"),
    # Registration values with family semantics the homed extractor
    # narrows or reshapes: 424B takes any 3-digit prefix and no
    # two-digit suffix; 497 takes any 3-digit prefix; FWP captures a
    # multi-number caption group and finds its tokens unanchored;
    # FN's label value excludes spaced hyphens its fallback covers
    # (Wave 2 priced stops, 2026-11-15).
    ("edgar_sec/engine/forms/form_424b/analysis.py", r"\d{3}-\d{3,}"),
    ("edgar_sec/engine/forms/form_497/analysis.py", r"\d{3}-\d{3,}"),
    ("edgar_sec/engine/forms/form_fwp/analysis.py", r"\d{3}-\d{3,}"),
    ("edgar_sec/engine/forms/form_fn/analysis.py", "(?:333|33)"),
    # The 12b-25 CUSIP caption: a label recognizer the value-side home
    # carries no surface for (census verdict: keep, register).
    ("edgar_sec/engine/forms/form_12b25/analysis.py", "_CUSIP_LABEL_RE"),
)

_ACCESSION_HINT = (
    "use ACCESSION_RE and ACCESSION_DIGITS_RE from edgar_sec.domain.identity "
    "instead of defining a private copy"
)

_CIK_HINT = (
    "use CIK_MEMBER_RE from edgar_sec.pipelines.metadata_sync.paths "
    "instead of defining a private copy"
)

_COMMISSION_HINT = (
    "use COMMISSION_FILE_NUMBER_RE, COMMISSION_FILE_CAPTION_RE, and "
    "COMMISSION_FILE_TOKEN_RE from edgar_sec.engine.forms.common.entities "
    "instead of defining a private copy"
)

_EIN_HINT = (
    "use IRS_RE from edgar_sec.engine.forms.common.entities "
    "instead of defining a private copy"
)

_REGISTRATION_HINT = (
    "use extract_registration_number from edgar_sec.engine.forms.common.entities "
    "instead of defining a private copy"
)

_CUSIP_HINT = (
    "use CUSIP_RE and parse_cusip from edgar_sec.engine.forms.common.entities "
    "instead of defining a private copy"
)


_DEF_START_RE = re.compile(r"^\s*[A-Za-z_]\w*\s*(?::[^=\n]+)?=(?!=)")


class _DefinitionLines:
    """The nearest preceding definition line in each scanned file.

    Sanctions name a definition, so a flagged core spelled on a
    continuation line is tested against its definition's line too.
    """

    def __init__(self) -> None:
        self._path = ""
        self._definition = ""

    def current(self, path: str, line: str) -> str:
        if path != self._path:
            self._path = path
            self._definition = ""
        if _DEF_START_RE.match(line):
            self._definition = line
        elif line.strip() and not line[:1].isspace():
            self._definition = ""
        return self._definition


def _rule(
    path: str, number: int, line: str, definition: str = ""
) -> ScannerFinding | None:
    if any(
        path == site and (fragment in line or fragment in definition)
        for site, fragment in _SANCTIONED_SITES
    ):
        return None
    if any(marker in line for marker in _SQL_MARKERS) or _URL_MARKER in line:
        return None
    if (
        _ACCESSION_CORE_RE.search(line)
        or _ACCESSION_DIGITS_RE.search(line)
        or _ACCESSION_DEF_RE.search(line)
    ):
        return finding(
            "identifier-patterns",
            path,
            number,
            "private accession recognizer outside its home",
            _ACCESSION_HINT,
        )
    if _CIK_MEMBER_RE.search(line):
        return finding(
            "identifier-patterns",
            path,
            number,
            "private CIK member-name recognizer outside its home",
            _CIK_HINT,
        )
    if _COMMISSION_RE.search(line):
        return finding(
            "identifier-patterns",
            path,
            number,
            "private commission file-number recognizer outside its home",
            _COMMISSION_HINT,
        )
    if _EIN_RE.search(line):
        return finding(
            "identifier-patterns",
            path,
            number,
            "private EIN recognizer outside its home",
            _EIN_HINT,
        )
    if _REGISTRATION_RE.search(line):
        return finding(
            "identifier-patterns",
            path,
            number,
            "private registration-number recognizer outside its home",
            _REGISTRATION_HINT,
        )
    if _CUSIP_RE.search(line) or _CUSIP_LABEL_RE.search(line):
        return finding(
            "identifier-patterns",
            path,
            number,
            "private CUSIP recognizer outside its home",
            _CUSIP_HINT,
        )
    return None


def _make_rule() -> Rule:
    definitions = _DefinitionLines()

    def rule(path: str, number: int, line: str) -> ScannerFinding | None:
        return _rule(path, number, line, definitions.current(path, line))

    return rule


def scan_identifier_patterns() -> list[ScannerFinding]:
    """Flag private identifier recognizers outside their homes."""
    return scan_text_rule(rule=_make_rule(), prefixes=_ALLOWED_PREFIXES)


SCANNER = Scanner(
    name="identifier-patterns",
    description=(
        "scan for private accession, CIK member-name, commission "
        "file-number, EIN, registration-number, and CUSIP recognizers "
        "outside domain/identity, forms/common/entities, and "
        "metadata_sync/paths"
    ),
    run=scan_identifier_patterns,
)
