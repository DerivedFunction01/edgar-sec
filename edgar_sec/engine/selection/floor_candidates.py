from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any

from .source import (
    POOL_COLUMNS,
    _POOL_SELECT,
    _QUALIFIED_POOL_SELECT,
    _SELECTED_TABLE,
)

_FLOOR_CANDIDATES_TABLE = "selection_floor_candidates"

if TYPE_CHECKING:
    from .source import CandidateSource


def stage_floor_candidates(
    source: CandidateSource,
    floors: dict[str, dict[str, int]],
    signature_dimensions: Sequence[str],
    signature_limit: int | None,
    target_units: int,
) -> int:
    con = source._require()
    floor_dimensions = tuple(
        source._dimension(dimension)
        for dimension, requirements in floors.items()
        if requirements
    )
    if not floor_dimensions or target_units <= 0:
        con.execute(
            f"CREATE OR REPLACE TEMP TABLE {_FLOOR_CANDIDATES_TABLE} "
            f"AS SELECT {_POOL_SELECT}, '' AS floor_dimension, "
            "'' AS floor_value, '' AS draw_order, 0 AS floor_rank "
            f"FROM {source.locator_relation} WHERE FALSE"
        )
        return 0

    dimensions = tuple(source._dimension(name) for name in signature_dimensions)
    signature_ctes = ""
    if signature_limit is None:
        signature_projection = ""
        eligible_cte = (
            f"eligible AS (SELECT {_POOL_SELECT}, draw_order "
            "FROM normalized_candidates)"
        )
    else:
        normalized = [
            (name, source._normalized_dimension_sql(name)) for name in dimensions
        ]
        signature_select = ", ".join(
            f"{expression} AS signature_{name}" for name, expression in normalized
        )
        signature_projection = f", {signature_select}"
        signature_join = " AND ".join(
            f"s.{name} = n.signature_{name}" for name in dimensions
        )
        signature_partition = ", ".join(f"signature_{name}" for name in dimensions)
        signature_ctes = f"""
            , candidates AS (
                SELECT n.*, COALESCE(s.signature_count, 0) AS previous_signature_count
                FROM normalized_candidates n
                LEFT JOIN selection_signatures s ON {signature_join}
            ), signature_ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY {signature_partition} ORDER BY draw_order
                ) AS signature_rank
                FROM candidates
            )
        """
        eligible_cte = f"""
            eligible AS (
                SELECT {_POOL_SELECT}, draw_order
                FROM signature_ranked
                WHERE signature_rank <= GREATEST(
                    {int(signature_limit)} - previous_signature_count, 0
                )
            )
        """
    floor_entries = tuple(
        (dimension, str(value).strip().lower())
        for dimension in floor_dimensions
        for value in floors[dimension]
    )
    floor_values = ", ".join(
        f"(?, ?, {source._normalized_dimension_sql(dimension, 'c')})"
        for dimension, _ in floor_entries
    )
    floor_candidate_columns = ", ".join(POOL_COLUMNS)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {_FLOOR_CANDIDATES_TABLE} AS
        WITH normalized_candidates AS (
            SELECT {_QUALIFIED_POOL_SELECT},
                   sha256(CAST(? AS VARCHAR) || l.document_locator_key) AS draw_order
                   {signature_projection}
            FROM {source._locator_source()}
            WHERE {source._exclusion_predicate()} AND {source.filters.predicate()}
        ){signature_ctes}, {eligible_cte}, floor_matches AS (
            SELECT c.*, f.dimension AS floor_dimension, f.value AS floor_value
            FROM eligible c
            CROSS JOIN LATERAL (VALUES {floor_values}) AS f(dimension, value, actual_value)
            WHERE f.value = f.actual_value
              AND (
                  f.dimension <> 'primary_exhibit_like'
                  OR NOT EXISTS (
                      SELECT 1 FROM {source.locator_relation} l2
                      JOIN {_SELECTED_TABLE} s2 USING (document_locator_key)
                      WHERE l2.representative_accession = c.representative_accession
                  )
              )
        ), accession_ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY floor_dimension, floor_value,
                    CASE WHEN floor_dimension = 'primary_exhibit_like'
                         THEN representative_accession
                         ELSE document_locator_key END
                ORDER BY draw_order
            ) AS accession_rank
            FROM floor_matches
        ), floor_ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY floor_dimension, floor_value ORDER BY draw_order
            ) AS floor_rank
            FROM accession_ranked
            WHERE accession_rank = 1
        )
        SELECT {floor_candidate_columns}, floor_dimension, floor_value,
               draw_order, floor_rank
        FROM floor_ranked
        WHERE floor_rank <= {int(target_units)}
        """,
        [source.seed, *(parameter for entry in floor_entries for parameter in entry)],
    )
    return int(
        con.execute(f"SELECT COUNT(*) FROM {_FLOOR_CANDIDATES_TABLE}").fetchone()[0]
    )


def pool_for_staged_floor(
    source: CandidateSource,
    dimension: str,
    value: str,
    limit: int,
    signature_dimensions: Sequence[str],
    signature_limit: int | None,
) -> Iterator[dict[str, Any]]:
    source._dimension(dimension)
    accession_filter = ""
    if dimension == "primary_exhibit_like":
        accession_filter = f"""
            AND NOT EXISTS (
                SELECT 1 FROM {source.locator_relation} l2
                JOIN {_SELECTED_TABLE} s2 USING (document_locator_key)
                WHERE l2.representative_accession = c.representative_accession
            )
        """
    signature_join = ""
    signature_filter = ""
    if signature_limit is not None:
        dimensions = tuple(source._dimension(name) for name in signature_dimensions)
        signature_join = "LEFT JOIN selection_signatures s ON " + " AND ".join(
            f"s.{name} = {source._normalized_dimension_sql(name, 'c')}"
            for name in dimensions
        )
        signature_filter = (
            f"AND COALESCE(s.signature_count, 0) < {int(signature_limit)}"
        )
    query = f"""
        SELECT {", ".join(f"c.{name}" for name in POOL_COLUMNS)}
        FROM {_FLOOR_CANDIDATES_TABLE} c
        {signature_join}
        WHERE c.floor_dimension = ? AND c.floor_value = ?
          {signature_filter}
          AND c.document_locator_key NOT IN (
              SELECT document_locator_key FROM {_SELECTED_TABLE}
          )
          {accession_filter}
        ORDER BY c.floor_rank
        LIMIT {int(limit)}
    """
    return source._rows(query, [dimension, str(value).strip().lower()])
