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
    is_year_token,
    parse_date,
)

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


def _is_date_only_line(stripped: str) -> bool:
    """Whether the whole line is one date, ignoring audit/continuation qualifiers.
    The one date core both public predicates share: the line must parse as a single date and leave no residue once month names and date numerals are removed.
    """
    rest = _WHITESPACE_RE.sub(" ", _DATE_QUALIFIER_RE.sub(" ", stripped)).strip(" ,")
    if not rest or len(rest.split()) > 5 or parse_date(rest) is None:
        return False
    return not _NON_DATE_TOKEN_RE.sub(" ", MONTH_RE.sub(" ", rest)).strip()


def is_date_line(stripped: str) -> bool:
    """Return whether the whole line is one date, ignoring audit/continuation qualifiers.
    The template route's refusal predicate: stricter than is_number_or_date_line, which also admits figure-only lines that are data, not dates.
    """
    return _is_date_only_line(stripped)


def _has_amount_figures(stripped: str) -> bool:
    """Whether the line carries at least two comma-separated amount figures.
    Figures in SEC forms carry comma separators, so bare-digit tokens are years or addresses, not amounts.
    """
    figures = sum(
        1
        for token in stripped.split()
        if "," in token and any(char.isdigit() for char in token)
    )
    return figures >= 2


def is_number_or_date_line(stripped: str) -> bool:
    """Return whether a line carries only a date or figures, with no prose riding along.
    The date case is the shared core; the figures case is its named extension — a numeric date, a year pair, or comma-separated amounts is a data header; a lone page label is not, so it stays furniture-shaped.
    """
    if _is_date_only_line(stripped):
        return True
    if not any(char.isdigit() for char in stripped):
        return False
    if any(char.isalpha() for char in stripped):
        return False
    tokens = stripped.split()
    return bool(
        _has_amount_figures(stripped)
        or NUMERIC_DATE_RE.search(stripped)
        or any(is_year_token(token.strip(",/")) for token in tokens)
    )


#: The word alone, bounded: "oversee" and "Seeley" carry no cross-reference.
_SEE_RE = re.compile(r"\bsee\b", re.IGNORECASE)


def has_cross_reference(text: str) -> bool:
    """Whether a line carries a "see" cross-reference.
    A cross-reference is prose, so its presence vetoes a strip even where the line's other shapes are furniture-shaped.
    """
    return bool(_SEE_RE.search(text))


__all__ = [
    "has_cross_reference",
    "is_content_line",
    "is_date_line",
    "is_number_or_date_line",
    "is_statement_title",
]
