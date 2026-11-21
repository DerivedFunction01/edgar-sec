"""Scanner routing page-reference recognition through its one home.
Flags a private page-reference core outside ``foundation.text.patterns``.
Allows homed compositions; the page-marker vocabulary (extraction,
"page N of M" shapes, whole-line labels) is a different intent, skipped.
"""

from __future__ import annotations

import re

from ..base import Scanner, ScannerFinding
from ..lines import finding, scan_text_rule

# The reference cores, spelled as they appear in pattern source: the word
# page, a whitespace run (either escape spelling), and a number core.
_NO_CORE = re.compile(r"page\\s\*\(\?:no", re.IGNORECASE)
_PLAIN_CORE = re.compile(r"page(?:\\s|\[ \\t\])\+(?:\\d|\[0-9|\(\?P)", re.IGNORECASE)
_STAR_CORE = re.compile(r"page\\s\*(?:\\d|\[0-9)", re.IGNORECASE)
_LETTER_CLASS = re.compile(r"\[A-Z\]")
_DASH_DIGIT = re.compile(r"[-–—](?:\\s)?\*?(?:\\d|\[0-9)")

# Cousin sites dispositioned as distinct intents by the finalization
# inventory (§d3), by file and core fragment: the ownership boilerplate
# disjunct (a page term inside a boilerplate alternation).
_COUSIN_SITES = (("edgar_sec/engine/forms/ownership/patterns.py", "page"),)

# The module that owns the page-reference vocabulary.
_ALLOWED_PREFIXES = ("edgar_sec/foundation/text/patterns.py",)

_HINT = (
    "use RE_PAGE_REFERENCE from edgar_sec.foundation.text.patterns "
    "instead of a private page-reference recognizer"
)


def _is_boilerplate_branch(line: str) -> bool:
    """Whether a page core is one branch of a boilerplate alternation:
    the literal alternates it with non-page pattern branches."""
    quotes = [index for index, char in enumerate(line) if char in "\"'"]
    span = line[quotes[0] : quotes[-1] + 1] if len(quotes) >= 2 else line
    if "|" not in span:
        return False
    branches = span.split("|")
    has_core = any(
        _PLAIN_CORE.search(branch) or _STAR_CORE.search(branch) for branch in branches
    )
    has_boilerplate = any(
        "page" not in branch.lower() and ("\\" in branch or "{" in branch)
        for branch in branches
    )
    return has_core and has_boilerplate


def _is_cousin(path: str, line: str) -> bool:
    """Whether the line is an inventory-dispositioned cousin shape."""
    if any(path == site and fragment in line for site, fragment in _COUSIN_SITES):
        return True
    # The boilerplate disjunct is a shape, not a file: a page core
    # alternated with non-page boilerplate terms is the same cousin
    # wherever it sits.
    if _is_boilerplate_branch(line):
        return True
    # An optional page prefix ((?:page ...) heads a line-classification
    # shape, not a reference: the page word is not required.
    if "(?:page" in line:
        return True
    # A composition over the home's own fragments ({PAGE_NUMBER_CORE},
    # {ROMAN_NUMERAL_PATTERN}) is the sanctioned use of the home, not a
    # private core.
    if "{PAGE_NUMBER_CORE}" in line or "{ROMAN_NUMERAL_PATTERN}" in line:
        return True
    # A whole-line anchored literal (^ ... $) classifies or extracts a
    # page label; it does not recognize a reference inside prose.
    if "^" in line and "$" in line:
        return True
    return False


def _rule(path: str, number: int, line: str) -> ScannerFinding | None:
    if _is_cousin(path, line):
        return None
    if _NO_CORE.search(line):
        return finding(
            "page-patterns",
            path,
            number,
            "private page-reference core (page no. form) outside the page home",
            _HINT,
        )
    plain = _PLAIN_CORE.search(line) or _STAR_CORE.search(line)
    if plain is not None:
        rest = line[plain.end() :]
        # "page N of M" is page-marker extraction, a different intent;
        # authors spell the "of" in either case (OF\s+ included).
        lowered = rest.lower()
        if "of\\s" in lowered or "of[ \\t]" in lowered or lowered.startswith("of "):
            return None
        return finding(
            "page-patterns",
            path,
            number,
            "private page-reference core outside the page home",
            _HINT,
        )
    word = line.lower().find("page")
    if word >= 0:
        letter = _LETTER_CLASS.search(line, word)
        if letter is not None and _DASH_DIGIT.search(line, letter.end()):
            return finding(
                "page-patterns",
                path,
                number,
                "private page-reference core (letter-dash form) outside the page home",
                _HINT,
            )
    return None


def scan_page_patterns() -> list[ScannerFinding]:
    """Flag page-reference cores defined outside the page home."""
    return scan_text_rule(rule=_rule, prefixes=_ALLOWED_PREFIXES)


SCANNER = Scanner(
    name="page-patterns",
    description=(
        "scan for private page-reference cores outside foundation.text.patterns"
    ),
    run=scan_page_patterns,
)
