"""Dialect policies: quoting, physical SQL types, and capability matrix."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import SqlDialect


def quote_ident(ident: str) -> str:
    """ANSI double-quoted identifier with quote doubling."""
    return '"' + ident.replace('"', '""') + '"'


@dataclass(frozen=True)
class DialectPolicy:
    name: SqlDialect
    supports_ilike: bool
    insert_ignore_style: str  # "or-ignore" | "on-conflict"
    replace_style: str  # "or-replace" | "on-conflict"
    median_support: str  # "native" | "extension"
    mode_support: str  # "native" | "correlated" | "extension"
    supports_drop_constraint: bool = True
    truncate_native: bool = True
    uses_pragma: bool = True
    explain_analyze_prefix: str = "EXPLAIN ANALYZE"
    bool_type: str = "BOOLEAN"
    uuid_type: str = "UUID"
    timestamp_type: str = "TIMESTAMP"
    json_type: str = "JSON"
    real_type: str = "REAL"
    blob_type: str = "BLOB"
    unsupported_functions: frozenset[str] = field(default_factory=frozenset)


def policy_for(dialect: SqlDialect) -> DialectPolicy:
    if dialect is SqlDialect.SQLITE:
        return DialectPolicy(
            name=dialect,
            supports_ilike=False,
            insert_ignore_style="or-ignore",
            replace_style="or-replace",
            median_support="extension",
            mode_support="extension",
            supports_drop_constraint=False,
            truncate_native=False,
            explain_analyze_prefix="EXPLAIN QUERY PLAN",
            bool_type="INTEGER",
            uuid_type="TEXT",
            timestamp_type="TEXT",
            json_type="TEXT",
            real_type="REAL",
            blob_type="BLOB",
        )
    if dialect is SqlDialect.DUCKDB:
        return DialectPolicy(
            name=dialect,
            supports_ilike=True,
            insert_ignore_style="on-conflict",
            replace_style="on-conflict",
            median_support="native",
            mode_support="native",
            explain_analyze_prefix="EXPLAIN ANALYZE",
            bool_type="BOOLEAN",
            uuid_type="UUID",
            timestamp_type="TIMESTAMP",
            json_type="JSON",
            real_type="REAL",
            blob_type="BLOB",
        )
    return DialectPolicy(
        name=SqlDialect.POSTGRES,
        supports_ilike=True,
        insert_ignore_style="on-conflict",
        replace_style="on-conflict",
        median_support="native",
        mode_support="native",
        truncate_native=True,
        explain_analyze_prefix="EXPLAIN ANALYZE",
        bool_type="BOOLEAN",
        uuid_type="UUID",
        timestamp_type="TIMESTAMP WITH TIME ZONE",
        json_type="JSONB",
        real_type="DOUBLE PRECISION",
        blob_type="BYTEA",
    )


def sql_literal(value: object) -> str:
    """Inline literal for DDL contexts (defaults). Not for runtime values."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"
