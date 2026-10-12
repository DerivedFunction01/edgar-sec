from __future__ import annotations

from typing import Any


def validate_limit_options(
    limit: int | None,
    accession_limit: int | None,
    min_exhibit_like: int | None,
) -> None:
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")
    if accession_limit is not None and accession_limit < 1:
        raise ValueError("accession_limit must be positive")
    if min_exhibit_like is not None and min_exhibit_like < 1:
        raise ValueError("min_exhibit_like must be positive")
    if limit is not None and accession_limit is not None:
        raise ValueError("limit and accession_limit are mutually exclusive")
    if limit is not None and min_exhibit_like is not None:
        raise ValueError("min_exhibit_like cannot be used with per-form limit")
    if (
        accession_limit is not None
        and min_exhibit_like is not None
        and min_exhibit_like > accession_limit
    ):
        raise ValueError("min_exhibit_like cannot exceed accession_limit")


def select_accession_groups(
    con: Any,
    source: str,
    where: str,
    accession_limit: int | None,
    min_exhibit_like: int | None,
) -> int | None:
    if accession_limit is None and min_exhibit_like is None:
        return None
    _, exhibit_like = con.execute(
        f"""
        SELECT COUNT(DISTINCT accession),
               COUNT(DISTINCT accession) FILTER (WHERE primary_exhibit_like)
        FROM {source}
        WHERE {where}
        """
    ).fetchone()
    exhibit_like = int(exhibit_like)
    if min_exhibit_like is not None and exhibit_like < min_exhibit_like:
        raise ValueError(
            "min_exhibit_like cannot be met: requested "
            f"{min_exhibit_like}, available {exhibit_like}"
        )
    if accession_limit is None:
        return None

    priority_count = min_exhibit_like or 0
    remaining_count = max(0, accession_limit - priority_count)
    con.execute(
        f"""
        CREATE TEMP TABLE selected_accessions AS
        WITH eligible AS (
            SELECT accession, bool_or(primary_exhibit_like) AS primary_exhibit_like
            FROM {source}
            WHERE {where}
            GROUP BY accession
        ), priority AS (
            SELECT accession FROM eligible
            WHERE primary_exhibit_like
            ORDER BY accession
            LIMIT {priority_count}
        ), fill AS (
            SELECT accession FROM eligible
            WHERE accession NOT IN (SELECT accession FROM priority)
            ORDER BY accession
            LIMIT {remaining_count}
        )
        SELECT accession FROM priority
        UNION ALL
        SELECT accession FROM fill
        """
    )
    return int(con.execute("SELECT COUNT(*) FROM selected_accessions").fetchone()[0])


def selected_accession_counts(con: Any, relation: str) -> tuple[int, int]:
    rows = con.execute(
        f"""
        SELECT COUNT(DISTINCT accession),
               COUNT(DISTINCT accession) FILTER (WHERE primary_exhibit_like)
        FROM {relation}
        """
    ).fetchone()
    return int(rows[0]), int(rows[1])
