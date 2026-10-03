"""SQL predicate compilers for the shared catalog filter vocabulary. The suffix and
date vocabularies are owned by `domain.filing_catalog.filters`, which two layers
must agree on.
"""

from __future__ import annotations

from edgar_sec.domain.filing_catalog.filters import (
    GRANULARITY_QUARTER,
    AbsoluteDateClause,
    DateSelection,
    RecurringDateClause,
)
from edgar_sec.infra.storage.duckdb import sql_identifier, sql_literal

# A module constant, not a caller argument, so the projection fragment and the
# predicate cannot drift and a caller wrapping a relation knows what to project away.
PARSED_DATE_ALIAS = "parsed_report_date"


def suffix_sql(column: str, suffixes: tuple[str, ...]) -> str:
    """A SQL predicate matching `column` against any allowed suffix; empty yields
    `TRUE`, non-empty is parenthesized so a caller's `AND` cannot change its meaning.
    """
    sql_identifier(column)
    if not suffixes:
        return "TRUE"
    return (
        "("
        + " OR ".join(
            f"lower({column}) LIKE {sql_literal('%.' + suffix)}" for suffix in suffixes
        )
        + ")"
    )


def date_projection_sql(column: str) -> str:
    """The projection fragment that parses a text date column once. The alias is an
    extra column, so a caller projecting `SELECT *` must project its own out.
    """
    return f"TRY_CAST({sql_identifier(column)} AS DATE) AS {PARSED_DATE_ALIAS}"


def parsed_date_relation(source_sql: str, column: str) -> str:
    """Wrap `source_sql` so a date predicate sees one parsed column; the projection
    stays inside the subquery, so the caller's alias still governs the WHERE.
    """
    return f"(SELECT *, {date_projection_sql(column)} FROM {source_sql})"


def date_selection_sql(selection: DateSelection) -> str:
    """A predicate matching a parsed `report_date`; empty is `TRUE` and keeps rows with
    a missing date, which a nonempty selection excludes, so the answers differ.
    """
    if not selection:
        return "TRUE"
    column = PARSED_DATE_ALIAS
    parts = [
        _recurring_clause_sql(column, clause)
        if isinstance(clause, RecurringDateClause)
        else _absolute_clause_sql(column, clause)
        for clause in selection
    ]
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"


def _absolute_clause_sql(column: str, clause: AbsoluteDateClause) -> str:
    """Emit one interval, unparenthesized: `BETWEEN`'s `AND` binds tighter than any
    `AND` a caller conjoins, so it cannot swallow a neighbouring condition.
    """
    if clause.start_date is not None and clause.end_date is not None:
        return (
            f"{column} BETWEEN DATE '{clause.start_date.isoformat()}' "
            f"AND DATE '{clause.end_date.isoformat()}'"
        )
    if clause.start_date is not None:
        return f"{column} >= DATE '{clause.start_date.isoformat()}'"
    return f"{column} <= DATE '{clause.end_date.isoformat()}'"


def _recurring_clause_sql(column: str, clause: RecurringDateClause) -> str:
    """Emit one recurring clause, parenthesized because it is a conjunction."""
    part = "quarter" if clause.granularity == GRANULARITY_QUARTER else "month"
    values = ", ".join(str(value) for value in clause.values)
    checks = [f"date_part('{part}', {column}) IN ({values})"]
    if clause.start_year is not None:
        checks.append(f"date_part('year', {column}) >= {int(clause.start_year)}")
    if clause.end_year is not None:
        checks.append(f"date_part('year', {column}) <= {int(clause.end_year)}")
    return "(" + " AND ".join(checks) + ")"


__all__ = [
    "PARSED_DATE_ALIAS",
    "date_projection_sql",
    "date_selection_sql",
    "parsed_date_relation",
    "suffix_sql",
]
