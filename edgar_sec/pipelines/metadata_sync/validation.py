"""Merge-validation queries for the submissions metadata cohort.

These checks express Phase 1 cohort semantics — one row per CIK, and an
accession that is legitimately listed by more than one registrant — so they
belong to the pipeline that owns the merge rather than to the storage layer
that runs them. The SQL is unchanged from the shared helper it replaces; only
the ownership of the column names moves, from a default in the storage layer to
a constant here.

Duplicate accessions are **reportable fan-out, not a failure**: the same filing
is listed by more than one registrant, so the result is surfaced as a warning on
the merge report rather than raising. A duplicate *CIK* is a different fact — it
means one registrant's rows landed twice — so that check still rejects the merge.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from edgar_sec.infra.storage.duckdb import sql_identifier, sql_path_list

# The Phase 1 submissions row nests each registrant's filings in a list column,
# and the accession is the field that identifies a document across registrants.
FILINGS_COLUMN = "filings"
ACCESSION_FIELD = "accession_number"


def find_duplicate_accessions(
    con: Any,
    paths: Sequence[str],
    *,
    limit: int = 100,
) -> list[str]:
    """Return accession numbers that more than one row lists, up to ``limit``.

    The same filing appearing under two registrants is expected on EDGAR, so a
    hit is evidence about the corpus rather than a defect in the merge.
    """
    if not paths:
        return []
    columns = sql_identifier(FILINGS_COLUMN)
    field = sql_identifier(ACCESSION_FIELD)
    query = f"""
        SELECT val::VARCHAR
        FROM (
            SELECT unnest({columns}).{field} AS val
            FROM read_parquet({sql_path_list(list(paths))})
        )
        WHERE val IS NOT NULL
        GROUP BY val
        HAVING count(*) > 1
        LIMIT {int(limit)}
    """
    return [row[0] for row in con.execute(query).fetchall()]


__all__ = [
    "ACCESSION_FIELD",
    "FILINGS_COLUMN",
    "find_duplicate_accessions",
]
