"""Merge-validation queries for the submissions metadata cohort.
Duplicate accessions are **reportable fan-out, not a failure**: one filing is
listed by several registrants. A duplicate *CIK* means one registrant's rows
landed twice, so that check still rejects the merge.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from edgar_sec.infra.storage.duckdb import sql_identifier, sql_path_list

# The submissions row nests each registrant's filings in a list column, and the
# accession is the field that identifies a document across registrants.
FILINGS_COLUMN = "filings"
ACCESSION_FIELD = "accession_number"


def find_duplicate_accessions(
    con: Any,
    paths: Sequence[str],
    *,
    limit: int = 100,
) -> list[str]:
    """Return accession numbers that more than one row lists, up to ``limit``.

    A hit is evidence about the corpus, not a defect in the merge.
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
