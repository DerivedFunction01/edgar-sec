"""Content and rule line shapes no furniture route may claim.
One home for the line predicates the candidate, template, and policy routes share: a content
line is document content even when it repeats, and a rule line is table structure, not text.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import (
    MONTH_RE,
    NUMERIC_DATE_RE,
    RE_FULL_DATE,
    is_year_token,
    parse_date,
)
from edgar_sec.foundation.text.patterns import RE_SEPARATOR_LINE

_CONTENT_SHAPE_RE = re.compile(
    build_alternation(
        (
            r"/s/",
            r"\bcusip\b",
            r"\bisin\b",
            r"\)\s*ss:",
            r"^\s*by\s*:",
            r"^\s*name\s*:",
            r"^\s*title\s*:",
            r"^\s*re\s*:",
            r"^\s*[a-z]{2,3}\.\s+[a-z]",
            r"^\s*\*+\S*(?:\s+\S+){2,}",
            r"^\s*schedule\s+of\s+investments\b",
            r"^\s*state\s+of\s+.*\)\s*$",
            r"^\s*county\s+of\s+.*\)\s*$",
            r"^\s*the\s+commonwealth\s+of\s+.*\)\s*$",
            r"\bfinancial\s+statements?\b",
            r"\bbalance\s+sheets?\b",
            r"\bstatements?\s+of\b",
            r"\bsee\b",
        ),
        auto_escape=False,
    ),
    re.IGNORECASE,
)


def is_content_line(text: str) -> bool:
    """Whether a line carries document content no furniture route may claim.
    Signature, jurat, schedule- and statement-title, identifier, letter subject, addressee, footnote, and cross-reference lines are cover content even when they repeat at an anchor.
    """
    return bool(_CONTENT_SHAPE_RE.search(text))


#: Templates are casefolded with values masked, so a bare vocabulary test suffices.
_STATEMENT_TITLE_RE = re.compile(r"statement|balance\s+sheet", re.IGNORECASE)


def is_statement_title(text: str) -> bool:
    """Whether a template names a statement title, wherever the caller found it.
    The statement-title vocabulary lives here with the content shapes; the template route's titled test and the content-line test must never drift into two copies.
    """
    return bool(_STATEMENT_TITLE_RE.search(text))


_WHITESPACE_RE = re.compile(r"\s+")
_DATE_QUALIFIER_RE = re.compile(r"\((?:unaudited|continued)\)", re.IGNORECASE)
_NON_DATE_TOKEN_RE = re.compile(r"[\d,.\s]+")


def is_date_line(stripped: str) -> bool:
    """Return whether the whole line is one date, ignoring audit/continuation qualifiers.
    The template route's refusal predicate: stricter than is_number_or_date_line, which also admits figure-only lines that are data, not dates.
    """
    rest = _WHITESPACE_RE.sub(" ", _DATE_QUALIFIER_RE.sub(" ", stripped)).strip(" ,")
    if not rest or len(rest.split()) > 5 or parse_date(rest) is None:
        return False
    return not _NON_DATE_TOKEN_RE.sub(" ", MONTH_RE.sub(" ", rest)).strip()


def is_number_or_date_line(stripped: str) -> bool:
    """Return whether a line carries only a date or figures, with no prose riding along.
    A numeric date, a year pair, or a full date (an "unaudited" qualifier aside) is a data header; a lone page label is not, so it stays furniture-shaped.
    """
    if not any(char.isdigit() for char in stripped):
        return False
    if not any(char.isalpha() for char in stripped):
        tokens = stripped.split()
        figures = sum(1 for token in tokens if any(c.isdigit() for c in token))
        return bool(
            figures >= 2
            or NUMERIC_DATE_RE.search(stripped)
            or any(is_year_token(token.strip(",/")) for token in tokens)
        )
    residue = RE_FULL_DATE.sub(" ", stripped)
    if any(char.isdigit() for char in residue):
        return False
    words = [word.strip("(),.").casefold() for word in residue.split()]
    return all(word in {"", "unaudited"} for word in words)


#: The word alone, bounded: "oversee" and "Seeley" carry no cross-reference.
_SEE_RE = re.compile(r"\bsee\b", re.IGNORECASE)


def has_cross_reference(text: str) -> bool:
    """Whether a line carries a "see" cross-reference.
    A cross-reference is prose, so its presence vetoes a strip even where the line's other shapes are furniture-shaped.
    """
    return bool(_SEE_RE.search(text))


#: Em- and en-dash rule runs: the separator border RE_SEPARATOR_LINE's ASCII class misses.
_DASH_RULE_RE = re.compile(r"^[—–]{2,}(?:\s+[—–]{2,})*$")
#: A single rule run over the wider rule-character set, asterisks and the horizontal bar included.
_RULE_ONLY_RE = re.compile(r"^[-_=—–―*]{3,}$")


def is_rule_line(text: str) -> bool:
    """Whether a line is only a rule: separator runs and nothing else.
    A rule line is table structure, so it is neither a furniture observation nor table content.
    """
    stripped = text.strip()
    return bool(
        RE_SEPARATOR_LINE.fullmatch(stripped)
        or _DASH_RULE_RE.fullmatch(stripped)
        or _RULE_ONLY_RE.fullmatch(stripped)
    )


__all__ = [
    "has_cross_reference",
    "is_content_line",
    "is_date_line",
    "is_number_or_date_line",
    "is_rule_line",
    "is_statement_title",
]
