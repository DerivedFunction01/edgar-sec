"""Scanner routing section-reference recognition through its one home.

``engine.tables.toc.patterns`` owns the PART/ITEM/NOTE reference vocabulary; a module
keeping its own caption core yields a second, drifting answer to what a reference is.
"""

from __future__ import annotations

import re

from ..base import Scanner, ScannerFinding
from ..lines import Rule, finding, scan_text_rule

# The caption cores, spelled as they appear in pattern source: the keyword,
# a whitespace run, and a digit core (a \d, a capture, or a digit-led class).
# No leading \b: source keywords usually follow a literal \b or a quote.
_NOTE_CORE = re.compile(r"NOTE(?:S\?|S)?\\s\+(?:\\d|\()", re.IGNORECASE)
_ITEM_CORE = re.compile(r"ITEM(?:S\?|S)?\\s\+(?:\\d|\(|\[0-9)", re.IGNORECASE)

# A PART core narrowed below the homed grammar (roman subset or digits only);
# the full [IVXLCDM] class is the homed core composed, and is allowed.
_PART_CORE = re.compile(
    r"PART\\s\+\[(?:IVX|IV|IX|X|I|V)+]\+|PART\\s\+\\d", re.IGNORECASE
)

# A see-reference with its target alternation spelled out, e.g. (?:item|row):
# the alternation is literal text here, so its pipes are escaped.
_SEE_CORE = re.compile(r"see\\s\+\(\?:[a-z]+(?:\|[a-z]+)*\)", re.IGNORECASE)

# Fragments that mark the text after a core as something else: a slot prefix
# alternated with a bare number, a parenthetical or range continuation, or a
# boundary-closed fragment. Those are compositions, not standalone recognizers.
_FRAGMENT_HEADS = ("|", "(?:\\(", "(?:[", "\\b")

# An item range ("Items 5 - 9" in an index) is a different intent: the
# captured number is closed and a dash joins it to the range's end.
_RANGE_TAIL = re.compile(r"\\d\+\)\\s\*-")

# Source fragments of a reference tail: separators, title classes, grouped
# continuations — evidence the core heads a reference recognizer.
_TAIL_FRAGMENTS = (
    "[:.\\-]",
    "[\\.\\)\\:\\-]",
    "[.:]",
    "[:.]",
    "[\\.",
    "(?:",
    "[A-Z]",
)

# The module that owns the reference vocabulary.
_ALLOWED_PREFIXES = ("edgar_sec/engine/tables/toc/patterns.py",)

# Sanctioned divergences (coordinator rulings, 2026-11-15), transcribed
# from the census register: the schema-surface composites in numbers.py.
_SANCTIONED_SITES = (
    ("edgar_sec/engine/forms/common/values/numbers.py", "_SCHEMA_FOOTNOTE_LABEL_ALT"),
    ("edgar_sec/engine/forms/common/values/numbers.py", "_SCHEMA_DISCLAIMER_ALT"),
    ("edgar_sec/engine/forms/common/values/numbers.py", "_NARRATIVE_NUMERIC_ALT"),
)

_HINT = (
    "use RE_NOTE_REFERENCE, RE_ITEM_REFERENCE, RE_PART_REFERENCE and the "
    "heading/grouped forms from edgar_sec.engine.tables.toc.patterns "
    "instead of a private reference recognizer"
)


def _is_fragment(rest: str) -> bool:
    """Whether the text after a core makes it a fragment of a larger shape."""
    return rest.lstrip("+?}").startswith(_FRAGMENT_HEADS)


# The digit core's own optional letter suffix (`\d+[A-Z]?`) is number
# grammar, not a reference tail: it is stripped before the tail test,
# which otherwise counts the core's quantifier continuation as a tail.
_LETTER_SUFFIX_RE = re.compile(r"^(?:\+|\{\d+(?:,\d*)?\})?\[A-Z\]\?")


def _tail_text(rest: str) -> str:
    """The text after a core, its own letter suffix stripped."""
    match = _LETTER_SUFFIX_RE.match(rest)
    return rest[match.end() :] if match is not None else rest


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
        path == site_path and (fragment in line or fragment in definition)
        for site_path, fragment in _SANCTIONED_SITES
    ):
        return None
    if _PART_CORE.search(line):
        return finding(
            "refcell-patterns",
            path,
            number,
            "narrowed PART reference core outside the reference home",
            _HINT,
        )
    if _SEE_CORE.search(line):
        return finding(
            "refcell-patterns",
            path,
            number,
            "private see-reference outside the reference home",
            _HINT,
        )
    for core in (_NOTE_CORE, _ITEM_CORE):
        match = core.search(line)
        if match is None:
            continue
        rest = line[match.end() :]
        if _is_fragment(rest) or _RANGE_TAIL.match(rest):
            continue
        if "re.compile" in line or any(
            fragment in _tail_text(rest)[:24] for fragment in _TAIL_FRAGMENTS
        ):
            return finding(
                "refcell-patterns",
                path,
                number,
                "private note/item reference core outside the reference home",
                _HINT,
            )
    return None


def _make_rule() -> Rule:
    definitions = _DefinitionLines()

    def rule(path: str, number: int, line: str) -> ScannerFinding | None:
        return _rule(path, number, line, definitions.current(path, line))

    return rule


def scan_refcell_patterns() -> list[ScannerFinding]:
    """Flag note/item/part caption cores defined outside the reference home."""
    return scan_text_rule(rule=_make_rule(), prefixes=_ALLOWED_PREFIXES)


SCANNER = Scanner(
    name="refcell-patterns",
    description=(
        "scan for private note/item/part reference cores outside "
        "engine.tables.toc.patterns"
    ),
    run=scan_refcell_patterns,
)
