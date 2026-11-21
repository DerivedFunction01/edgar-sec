"""Status command: report the store's vintages and the index tip."""

from __future__ import annotations

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output

from ..options import DatasetsOptions
from ..publish import store_tip
from edgar_sec.infra.storage.duckdb import sql_identifier

from ..store import VINTAGES_RELATION, open_store


def cmd_status(options: DatasetsOptions) -> int:
    """Report per-set vintage counts and the published index tip."""
    paths = options.datasets_paths()
    rows: list[KeyValueRow] = [KeyValueRow("command", "status")]
    if paths.store_file.is_file():
        con = open_store(paths.store_file)
        try:
            counts = con.execute(
                f"SELECT set_id, count(*) FROM {sql_identifier(VINTAGES_RELATION)} "
                "GROUP BY set_id ORDER BY set_id"
            ).fetchall()
        finally:
            con.close()
        for set_id, count in counts:
            rows.append(KeyValueRow(f"vintages_{set_id}", str(int(count))))
    rows.append(KeyValueRow("tip", store_tip(paths, options.branch) or "none"))
    render_output(rows, title="Datasets Status")
    return 0


__all__ = ["cmd_status"]
