from __future__ import annotations

from pathlib import Path
from typing import Literal

import duckdb

from edgar_sec.infra.storage.duckdb import connect, copy_query_to_parquet


class FamilyIndexNotFoundError(FileNotFoundError):
    """The requested family index is absent, unreadable, or malformed."""


_DELTA_QUERY = """
WITH kept AS (
    SELECT requested.ordinal, requested.cik_padded, requested.name
    FROM read_parquet(?) AS requested
    WHERE NOT EXISTS (
        SELECT 1 FROM read_parquet(?) AS base
        WHERE base.cik = requested.cik_padded
    )
)
SELECT row_number() OVER (ORDER BY ordinal) - 1 AS ordinal, cik_padded, name
FROM kept
ORDER BY ordinal
"""


def _dataset(path: Path | str) -> str:
    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    return str(source)


def execute_delta_roster(
    requested_dataset: Path,
    base_cik_map_dataset: Path,
    output_dataset: Path,
) -> int:
    with connect() as con:
        return copy_query_to_parquet(
            con,
            _DELTA_QUERY,
            output_dataset,
            params=[_dataset(requested_dataset), _dataset(base_cik_map_dataset)],
        )


def sample_cohort(
    source_dataset: Path,
    output_dataset: Path,
    *,
    method: Literal["modulo", "random"] = "modulo",
    rate_percent: float | None = None,
    sample_limit: int | None = None,
    seed: int = 42,
    family_index_dataset: Path | None = None,
    group_by_family: bool = False,
    exclude_spv: bool = False,
) -> int:
    if method not in {"modulo", "random"}:
        raise ValueError(f"unsupported sampling method: {method!r}")
    if rate_percent is not None and not 0.0 < rate_percent <= 100.0:
        raise ValueError("rate_percent must be in (0, 100]")
    if sample_limit is not None and sample_limit < 1:
        raise ValueError("sample_limit must be at least 1")
    source = Path(source_dataset).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if group_by_family and (
        family_index_dataset is None or not Path(family_index_dataset).is_file()
    ):
        raise FamilyIndexNotFoundError("family index is missing")

    params: list[object] = [str(source)]
    if group_by_family:
        family_path = Path(family_index_dataset).resolve()
        try:
            with connect() as con:
                schema = {
                    str(row[0])
                    for row in con.execute(
                        "DESCRIBE SELECT * FROM read_parquet(?)", [str(family_path)]
                    ).fetchall()
                }
            if not {"cik", "company_family", "family_kind"}.issubset(schema):
                raise ValueError("family index schema is incomplete")
        except (duckdb.Error, OSError, TypeError, ValueError) as exc:
            raise FamilyIndexNotFoundError("family index is unreadable") from exc
        params.append(str(family_path))
        family_cte = """
        , joined AS (
            SELECT s.ordinal, s.cik_padded, s.name,
                   coalesce(nullif(f.company_family, ''), 'cik:' || s.cik_padded) AS family,
                   coalesce(f.family_kind = 'spv', false) AS is_spv
            FROM source_rows s
            LEFT JOIN read_parquet(?) f
              ON lpad(cast(f.cik AS VARCHAR), 10, '0') = s.cik_padded
        ), candidates AS (
            SELECT *, row_number() OVER (
                PARTITION BY family ORDER BY is_spv, ordinal
            ) AS family_rank
            FROM joined
            {spv_filter}
        )
        """.format(spv_filter="WHERE NOT is_spv" if exclude_spv else "")
        sampling_source = (
            "SELECT ordinal, cik_padded, name FROM candidates WHERE family_rank = 1"
        )
    else:
        family_cte = ""
        sampling_source = "SELECT ordinal, cik_padded, name FROM source_rows"

    if method == "modulo":
        params.append(rate_percent if rate_percent is not None else 100.0)
        selection = f"""
            SELECT * FROM ({sampling_source}) sample_source
            WHERE try_cast('0x' || substr(md5(cik_padded), 1, 8) AS BIGINT) % 100 < ?
        """
        if sample_limit is not None:
            selection += " ORDER BY try_cast(cik_padded AS BIGINT) LIMIT ?"
            params.append(sample_limit)
    else:
        params.append(seed)
        limit_filter = ""
        if rate_percent is not None:
            params.append(rate_percent)
            limit_filter = "sample_rank <= ceil(sample_count * ? / 100.0)"
        if sample_limit is not None:
            params.append(sample_limit)
            limit_filter = (
                f"{limit_filter} AND " if limit_filter else ""
            ) + "sample_rank <= ?"
        selection = f"""
            SELECT ordinal, cik_padded, name FROM (
                SELECT *, row_number() OVER (ORDER BY hash(cik_padded, ?)) AS sample_rank,
                       count(*) OVER () AS sample_count
                FROM ({sampling_source}) sample_source
            ) ranked
            {f"WHERE {limit_filter}" if limit_filter else ""}
        """
    query = f"""
        WITH source_rows AS (SELECT ordinal, cik_padded, name FROM read_parquet(?))
        {family_cte}
        SELECT row_number() OVER (ORDER BY try_cast(cik_padded AS BIGINT)) - 1 AS ordinal,
               cik_padded, name
        FROM ({selection}) sampled
        ORDER BY try_cast(cik_padded AS BIGINT)
    """
    with connect() as con:
        return copy_query_to_parquet(con, query, output_dataset, params=params)


__all__ = [
    "FamilyIndexNotFoundError",
    "execute_delta_roster",
    "sample_cohort",
]
