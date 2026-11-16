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
        "family": "word-token",
        "home": "edgar_sec/foundation/text/words.py",
        "names": ("WORD_TOKEN_RE",),
        "shapes": (),
        "shape_hint": "",
    },
    {
        "family": "table-patterns",
        "home": "edgar_sec/engine/tables/patterns.py",
        "names": ("SCALE_PATTERNS", "UNITS_LABEL_RE"),
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
)

# Derived name -> home view of the registry, kept for readers.
PATTERN_HOMES: dict[str, str] = {
    name: family["home"]
    for family in RECOGNIZER_FAMILIES
    for name in family["names"] + tuple(family.get("def_only", ()))
}

_DEF_RES: dict[str, re.Pattern[str]] = {}
_ASSIGN_RES: dict[str, re.Pattern[str]] = {}


def _is_definition(name: str, line: str, depth: int, def_only: bool = False) -> bool:
    if name not in _DEF_RES:
        _DEF_RES[name] = re.compile(rf"^\s*def\s+{name}\s*\(")
        _ASSIGN_RES[name] = re.compile(rf"^\s*{name}\s*(?::[^=\n]+)?=(?!=)")
    if _DEF_RES[name].search(line):
        return True
    if not _ASSIGN_RES[name].search(line):
        return False
    # An assignment inside brackets is a keyword argument, not a
    # definition; a def-only (function) name is redefined by an
    # assignment only at module level, never by an indented local.
    if depth > 0:
        return False
    return not def_only or not line[0].isspace()


def _module_of(home: str) -> str:
    return home.removesuffix(".py").replace("/", ".")


def _rule(path: str, number: int, line: str, depth: int = 0) -> ScannerFinding | None:
    for family in RECOGNIZER_FAMILIES:
        if path == family["home"]:
            continue
        named = [(name, False) for name in family["names"]]
        named += [(name, True) for name in family.get("def_only", ())]
        for name, def_only in named:
            if _is_definition(name, line, depth, def_only):
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


class _BracketTracker:
    """Bracket depth at each line start, strings and comments aside."""

    def __init__(self) -> None:
        self.depth = 0
        self._quote: str | None = None
        self._triple = False

    def depth_at(self, line: str) -> int:
        start = self.depth
        index = 0
        while index < len(line):
            char = line[index]
            if self._quote is not None:
                if char == "\\":
                    index += 1
                elif line.startswith(
                    self._quote * 3 if self._triple else self._quote, index
                ):
                    index += 3 if self._triple else 1
                    self._quote = None
                    continue
            elif char == "#":
                break
            elif char in "'\"":
                self._triple = line.startswith(char * 3, index)
                self._quote = char
                index += 3 if self._triple else 1
                continue
            elif char in "([{":
                self.depth += 1
            elif char in ")]}":
                self.depth -= 1
            index += 1
        return start


def _scan_lines(path: str, lines: list[str]) -> list[ScannerFinding]:
    findings: list[ScannerFinding] = []
    tracker = _BracketTracker()
    for number, line in enumerate(lines, start=1):
        depth = tracker.depth_at(line)
        if is_noise(line):
            continue
        found = _rule(path, number, line, depth)
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
