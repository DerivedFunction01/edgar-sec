"""Verify command: run the oracle verification pass over the store."""

from __future__ import annotations

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output

from ..options import DatasetsOptions
from ..verify import verify_store


def cmd_verify(options: DatasetsOptions) -> int:
    """Verify loaded rows against source lines and the BDC population."""
    paths = options.datasets_paths()
    result = verify_store(paths.store_file)
    rows: list[KeyValueRow] = [
        KeyValueRow("command", "verify"),
        KeyValueRow("tables_checked", str(len(result.tables))),
        KeyValueRow("tables_ok", str(sum(1 for t in result.tables if t.ok))),
    ]
    for table in result.tables:
        if not table.ok:
            rows.append(
                KeyValueRow(
                    f"mismatch_{table.set_id}_{table.vintage}_{table.relation}",
                    f"source={table.source_rows} loaded={table.loaded_rows}",
                )
            )
    for check in result.population:
        rows.append(
            KeyValueRow(
                f"bdc_population_{check.vintage}",
                f"dataset={check.dataset_ciks} report={check.report_ciks} "
                f"both={check.both} dataset_only={check.dataset_only} "
                f"report_only={check.report_only}",
            )
        )
    rows.append(KeyValueRow("ok", str(result.ok)))
    render_output(rows, title="Datasets Verify")
    return 0 if result.ok else 1


__all__ = ["cmd_verify"]
