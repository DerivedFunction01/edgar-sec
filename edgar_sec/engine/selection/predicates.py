"""SQL predicate compilers for the shared catalog filter vocabulary.

The suffix and date vocabularies live in ``domain.filing_catalog.filters``
because two layers must agree on them: deterministic-scope planning
(``pipelines.filing_catalog``) and policy-scope quota selection (this package).
Layer 4 may import Layer 3, so the compilers that turn that vocabulary into
DuckDB predicates live here rather than in the pipeline or in infra — infra
owns the dialect primitives, not the filter semantics.

Deterministic-scope planning reuses these compilers for its ``dates`` filter, which is
why the module is owned by the selection engine and not by the planner.
"""

from __future__ import annotations

from edgar_sec.domain.filing_catalog.filters import (
    GRANULARITY_QUARTER,
    AbsoluteDateClause,
    DateSelection,
    RecurringDateClause,
)
from edgar_sec.infra.storage.duckdb import sql_identifier, sql_literal

# The alias a date predicate filters on. It is a module constant rather than
# a caller argument so the projection fragment and the predicate cannot drift
# apart, and so a caller that wraps a relation knows the extra column to project
# away.
PARSED_DATE_ALIAS = "parsed_report_date"


def suffix_sql(column: str, suffixes: tuple[str, ...]) -> str:
    """Return a SQL predicate matching ``column`` against any allowed suffix.

    An empty suffix tuple yields ``TRUE`` so a caller can always apply the
    predicate unconditionally. A non-empty one is parenthesized: the predicate
    is a disjunction, and a caller that conjoins it with ``AND`` without
    adding its own parentheses would silently change the meaning to
    ``a AND b OR c``.
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
    """Return the projection fragment that parses a text date column once.

    ``report_date`` is stored as text, so any date predicate has to parse it.
    Emitting the parse inline instead costs a re-parse per reference: over the
    3.19M rows of a published catalog, the same four-clause selection measured
    0.36s inline against 0.11s projected once, with nine ``TRY_CAST`` nodes in
    the inline plan against none in the projected one. The fragment therefore
    names one alias, and :func:`date_selection_sql` filters on it.

    The alias is an extra column, so a caller projecting ``SELECT *`` will leak
    it into the result. A published catalog shard has a fixed schema, so the
    caller must project its own columns out of the wrapped relation.
    """
    return f"TRY_CAST({sql_identifier(column)} AS DATE) AS {PARSED_DATE_ALIAS}"


def parsed_date_relation(source_sql: str, column: str) -> str:
    """Wrap ``source_sql`` so a date predicate sees exactly one parsed column.

    Both callers that filter a date need the same shape -- deterministic
    planning over the catalog, and the selection engine over its feature
    snapshot -- so the wrapping lives here rather than being written twice. The
    relation is aliased by the caller's own query, which is why the projection
    stays inside: the alias is visible to the enclosing ``WHERE`` without the
    caller's qualified column references seeing a new name.
    """
    return f"(SELECT *, {date_projection_sql(column)} FROM {source_sql})"


def date_selection_sql(selection: DateSelection) -> str:
    """Return the predicate matching a parsed ``report_date`` against ``selection``.

    The predicate takes the alias :func:`date_projection_sql` defines rather
    than the raw column, because a recurring clause needs the parsed value twice
    (period and year) and an OR of several clauses needs it many more times.

    An empty selection is ``TRUE``, matching the other predicate builders: no
    date predicate at all, which keeps rows whose ``report_date`` is missing.
    A nonempty selection cannot represent those rows -- a missing date has no
    quarter and no interval -- so it excludes them, which is why the two answers
    differ rather than being two spellings of one.
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
    """Emit one interval.

    No parentheses: a comparison or ``BETWEEN`` is an atom, and ``BETWEEN``'s
    ``AND`` binds tighter than any ``AND`` a caller conjoins with it, so this
    cannot swallow a neighbouring condition the way a bare conjunction would.
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
