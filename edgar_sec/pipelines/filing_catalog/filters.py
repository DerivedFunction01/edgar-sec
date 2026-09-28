"""Shared document-path filters for target planning.

v1 built its suffix predicate by interpolating both the column name and each
suffix straight into a SQL string literal, and ``normalize_suffixes`` only
lower-cased and de-dotted, so a suffix containing a quote could terminate the
literal. v2 rejects any suffix outside a conservative allowlist up front, which
fails loudly at the call site instead of producing malformed or injected SQL.
"""

from __future__ import annotations

import re

from edgar_sec.infra.storage.duckdb_catalog import sql_literal

# Suffixes are user input arriving from a CLI flag. Real SEC document names use
# letters, digits, and dots (``0001.htm`` is a real stub suffix), so the
# allowlist covers exactly that and rejects everything quote- or comment-shaped.
_SUFFIX_RE = re.compile(r"^[a-z0-9][a-z0-9.]*$")

# Only bare SQL identifiers may be passed as the filtered column.
_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

DEFAULT_AMENDMENT = "both"
AMENDMENT_POLICIES = ("both", "original", "amendments")
DEFAULT_DOCUMENT_SUFFIXES: tuple[str, ...] = ()


def normalize_suffixes(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Lower-case, de-dot, de-duplicate, and validate document suffixes.

    Order is preserved because a plan's recorded suffix list participates in
    the plan identity hash; de-duplication keeps that hash stable when a caller
    repeats a suffix.
    """
    normalized: list[str] = []
    for suffix in values:
        if not isinstance(suffix, str):
            raise ValueError(f"suffix must be a string, got {type(suffix).__name__}")
        token = suffix.strip().lower().lstrip(".")
        if not token:
            continue
        if not _SUFFIX_RE.match(token):
            raise ValueError(
                f"invalid document suffix {suffix!r}; expected letters, digits, "
                "or dots only"
            )
        if token not in normalized:
            normalized.append(token)
    return tuple(normalized)


def suffix_sql(column: str, suffixes: tuple[str, ...]) -> str:
    """Return a SQL predicate matching ``column`` against any allowed suffix.

    An empty suffix tuple yields ``TRUE`` so a caller can always apply the
    predicate unconditionally.
    """
    if not _COLUMN_RE.match(column):
        raise ValueError(f"unsafe SQL column identifier: {column!r}")
    if not suffixes:
        return "TRUE"
    return " OR ".join(
        f"lower({column}) LIKE {sql_literal('%.' + suffix)}" for suffix in suffixes
    )


def amendment_sql(policy: str) -> str:
    """Return the SQL predicate implementing an amendment policy.

    ``original`` keeps filings whose form is not an amendment and
    ``amendments`` keeps only amendments. The predicate is derived from the
    catalog's own ``is_amendment`` column rather than recomputing the suffix
    rule, so the two can never drift.
    """
    if policy not in AMENDMENT_POLICIES:
        raise ValueError(
            f"amendment must be one of {', '.join(AMENDMENT_POLICIES)}; got {policy!r}"
        )
    if policy == "original":
        return "is_amendment = false"
    if policy == "amendments":
        return "is_amendment = true"
    return "TRUE"


__all__ = [
    "AMENDMENT_POLICIES",
    "DEFAULT_AMENDMENT",
    "DEFAULT_DOCUMENT_SUFFIXES",
    "amendment_sql",
    "normalize_suffixes",
    "suffix_sql",
]
