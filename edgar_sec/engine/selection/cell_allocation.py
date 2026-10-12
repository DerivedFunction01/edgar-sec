from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from edgar_sec.infra.storage.duckdb import sql_identifier


def equalized_cell_targets(
    cells: Sequence[tuple[str, str, int, int]], budget: int
) -> dict[tuple[str, str], int]:
    """Return final per-cell targets using bounded equal-level allocation."""
    targets = {(form, era): selected for form, era, selected, _ in cells}
    if budget <= 0 or not cells:
        return targets

    capacities = {
        (form, era): selected + available for form, era, selected, available in cells
    }
    low = min(selected for _, _, selected, _ in cells)
    high = max(capacities.values())

    def cost(level: int) -> int:
        return sum(
            min(capacities[(form, era)], level) - min(selected, level)
            for form, era, selected, _ in cells
        )

    while low < high:
        middle = (low + high + 1) // 2
        if cost(middle) <= budget:
            low = middle
        else:
            high = middle - 1

    for form, era, selected, _ in cells:
        key = (form, era)
        targets[key] = min(capacities[key], max(selected, low))

    remaining = budget - sum(
        targets[(form, era)] - selected for form, era, selected, _ in cells
    )
    for form, era, _, _ in cells:
        key = (form, era)
        if remaining <= 0:
            break
        if targets[key] == low and targets[key] < capacities[key]:
            targets[key] += 1
            remaining -= 1
    return targets


def account_staged_candidates(
    con: Any, signature_dimensions: Sequence[str], known_dimensions: Sequence[str]
) -> int:
    count = int(
        con.execute("SELECT COUNT(*) FROM selection_cell_additions").fetchone()[0]
    )
    if not count:
        return 0

    con.execute(
        "INSERT INTO active_locator_keys "
        "SELECT document_locator_key FROM selection_cell_additions"
    )
    signature_names = [sql_identifier(name) for name in signature_dimensions]
    signature_values = [
        _normalized_sql("selection_cell_additions", name) for name in signature_names
    ]
    signature_select = ", ".join(
        f"{value} AS {name}" for name, value in zip(signature_names, signature_values)
    )
    signature_group = ", ".join(signature_values)
    signature_columns = ", ".join(signature_names)
    con.execute(
        f"""
        INSERT INTO selection_signatures ({signature_columns}, signature_count)
        SELECT {signature_select}, COUNT(*)
        FROM selection_cell_additions
        GROUP BY {signature_group}
        ON CONFLICT ({signature_columns}) DO UPDATE SET
            signature_count = selection_signatures.signature_count + excluded.signature_count
        """
    )
    con.execute(
        """
        INSERT INTO selection_cells (form, era, available, selected, taken)
        SELECT form, era, 0, COUNT(*), 0
        FROM selection_cell_additions
        GROUP BY form, era
        ON CONFLICT (form, era) DO UPDATE SET
            selected = selection_cells.selected + excluded.selected
        """
    )

    exhibit_value = _normalized_sql("a", "primary_exhibit_like")
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE selection_new_exhibit_accessions AS
        SELECT DISTINCT {exhibit_value} AS value,
               COALESCE(CAST(representative_accession AS VARCHAR), 'None') AS accession
        FROM selection_cell_additions a
        WHERE NOT EXISTS (
            SELECT 1 FROM selection_exhibit_accessions e
            WHERE e.value = {exhibit_value}
              AND e.accession = COALESCE(CAST(representative_accession AS VARCHAR), 'None')
        )
        """
    )
    con.execute(
        "INSERT INTO selection_exhibit_accessions "
        "SELECT value, accession FROM selection_new_exhibit_accessions"
    )
    for dimension in known_dimensions:
        name = sql_identifier(dimension)
        if dimension == "primary_exhibit_like":
            query = """
                INSERT INTO selection_coverage (dimension, value, unit_count)
                SELECT ?, value, COUNT(*) FROM selection_new_exhibit_accessions
                GROUP BY value
                ON CONFLICT (dimension, value) DO UPDATE SET
                    unit_count = selection_coverage.unit_count + excluded.unit_count
            """
            con.execute(query, [dimension])
        else:
            value = _normalized_sql("selection_cell_additions", name)
            con.execute(
                f"""
                INSERT INTO selection_coverage (dimension, value, unit_count)
                SELECT ?, {value}, COUNT(*) FROM selection_cell_additions
                GROUP BY {value}
                ON CONFLICT (dimension, value) DO UPDATE SET
                    unit_count = selection_coverage.unit_count + excluded.unit_count
                """,
                [dimension],
            )
    return count


def _normalized_sql(table: str, column: str) -> str:
    table_name = sql_identifier(table)
    column_name = sql_identifier(column)
    value = f"{table_name}.{column_name}"
    return f"CASE WHEN {value} IS NULL THEN 'none' ELSE LOWER(TRIM(CAST({value} AS VARCHAR))) END"


__all__ = ["account_staged_candidates", "equalized_cell_targets"]
