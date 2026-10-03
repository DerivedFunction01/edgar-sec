"""Read-only validation for operator-supplied SQL.

A query typed into a console is untrusted input with unknown intent. This guard
is the first line of defense for that case, and it is deliberately narrow: it
accepts a statement only if the first meaningful token is one of a fixed set of
read verbs, and refuses anything containing a statement separator.

Three properties are important, and the third is the one usually got wrong:

1. **Only read verbs start a statement.** ``SELECT``, ``WITH``, ``DESCRIBE``,
   ``SHOW``, ``EXPLAIN``, and ``PRAGMA table_info`` are allowed. ``PRAGMA`` is
   allowed *only* in that one form -- bare ``PRAGMA`` can write.
2. **One statement, ever.** ``;`` is rejected unless it is inside a string
   literal or a comment. This is why a plain ``";" in query`` test is not enough
   and why the separator scan below is hand-written rather than a regex.
3. **Leading comments are stripped before the verb check.** Otherwise
   ``-- a note\\nDROP TABLE x`` passes the keyword test, because the query does
   not *start* with ``DROP``.

A guard is a filter, not a sandbox, and the caller is responsible for the rest:
this returns a string, not a connection. Pair it with an in-memory connection,
a row cap, and a timeout.
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

    A single pass is not enough: ``/* a */ -- b\\nSELECT`` leaves a comment in
    front after the block is removed, and a guard that stopped there would read
    the comment as the statement.
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

    Hand-written because the naive ``";" in query`` test is wrong in both
    directions: it rejects the harmless ``SELECT ';' AS x`` and, worse, a regex
    that tries to be clever about quotes and comments is exactly where a guard
    quietly stops being one. This scans once, tracking quote state, and treats a
    doubled quote (``''``) as an escaped quote rather than a terminator.

    An unterminated comment or literal runs to end-of-string rather than
    raising: the caller has already decided the statement is otherwise a read,
    and the SQL engine will report the malformed input far more precisely than a
    hand-rolled scanner could.
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

    Order matters: the separator check runs before the verb check so that
    ``DROP TABLE a; SELECT 1`` is reported as a multiple-statement problem rather
    than as a verb problem, which is the more actionable message.
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
