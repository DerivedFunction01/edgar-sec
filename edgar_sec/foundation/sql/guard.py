"""Read-only validation for operator-supplied SQL.

Accepts a statement only if the first meaningful token is a read verb (``PRAGMA`` only as
``PRAGMA table_info`` -- bare ``PRAGMA`` can write) and no unquoted, uncommented ``;``
appears, after leading comments are stripped. A filter, not a sandbox.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

__all__ = ["ALLOWED_LEADING_KEYWORDS", "SqlGuardError", "validate_read_only"]


class SqlGuardError(ValueError):
    """Raised when a query is not an accepted read-only statement."""


ALLOWED_LEADING_KEYWORDS: tuple[str, ...] = (
    "SELECT",
    "WITH",
    "DESCRIBE",
    "EXPLAIN",
    "SHOW",
    r"PRAGMA\s+table_info",
)

_ALLOWED_START = re.compile(
    rf"^\s*({build_alternation(ALLOWED_LEADING_KEYWORDS)})\b",
    re.IGNORECASE,
)

_LEADING_LINE_COMMENT = re.compile(r"^\s*--[^\n]*\n")
_LEADING_BLOCK_COMMENT = re.compile(r"^\s*/\*.*?\*/", re.DOTALL)


def _strip_leading_comments(query: str) -> str:
    """Remove every leading line and block comment, repeatedly.

    A single pass leaves ``/* a */ -- b\nSELECT`` with a comment still in front.
    """
    stripped = query
    while True:
        removed = _LEADING_LINE_COMMENT.sub("", stripped, count=1)
        if removed != stripped:
            stripped = removed
            continue
        removed = _LEADING_BLOCK_COMMENT.sub("", stripped, count=1)
        if removed != stripped:
            stripped = removed
            continue
        return stripped.strip()


def _strip_trailing_semicolon(query: str) -> str:
    return query.strip().rstrip(";").strip()


def _contains_statement_separator(query: str) -> bool:
    """True when an unquoted, uncommented ``;`` appears in the statement.

    Scans once tracking quote state, treating ``''`` as escaped rather than
    terminating; an unterminated literal runs to end-of-string.
    """
    in_single = in_double = False
    index = 0
    while index < len(query):
        char = query[index]
        if not in_double and char == "'":
            if in_single and query[index : index + 2] == "''":
                index += 2
                continue
            in_single = not in_single
        elif not in_single and char == '"':
            if in_double and query[index : index + 2] == '""':
                index += 2
                continue
            in_double = not in_double
        elif not in_single and not in_double:
            if char == "-" and query[index : index + 2] == "--":
                end = query.find("\n", index)
                index = end if end != -1 else len(query)
                continue
            if char == "/" and query[index : index + 2] == "/*":
                end = query.find("*/", index + 2)
                index = len(query) if end == -1 else end + 2
                continue
            if char == ";":
                return True
        index += 1
    return False


def validate_read_only(query: str) -> str:
    """Return the normalized query if it is an accepted read, else raise.

    The separator check runs first, so ``DROP TABLE a; SELECT 1`` is reported as a
    multiple-statement problem rather than a verb problem.
    """
    normalized = _strip_trailing_semicolon(query)
    if not normalized:
        raise SqlGuardError("query is empty")
    if _contains_statement_separator(normalized):
        raise SqlGuardError("multiple statements are not allowed")
    if _ALLOWED_START.match(_strip_leading_comments(normalized)) is None:
        raise SqlGuardError(
            "only SELECT, WITH, DESCRIBE, SHOW, EXPLAIN, or PRAGMA table_info "
            "queries may run in the console"
        )
    return normalized
