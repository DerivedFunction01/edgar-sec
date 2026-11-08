"""Import command: download and load dataset vintages, then publish the index."""

from __future__ import annotations

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.infra.sec_http.client import SecHttpClient

from ..ingest import import_vintage
from ..options import DatasetsOptions
from ..publish import publish_index
from ..specs import spec_for

from .client import build_client


def cmd_import(
    options: DatasetsOptions,
    *,
    set_id: str,
    vintages: tuple[str, ...],
    http: SecHttpClient | None = None,
) -> int:
    """Import each named vintage of one set and publish the index snapshot."""
    spec = spec_for(set_id)
    client = http or build_client()
    paths = options.datasets_paths()
    rows: list[KeyValueRow] = [
        KeyValueRow("command", "import"),
        KeyValueRow("set", set_id),
    ]
    for vintage in vintages:
        result = import_vintage(paths, spec, vintage, http=client)
        total = sum(table.loaded_rows for table in result.load.tables)
        rows.append(KeyValueRow(f"vintage_{vintage}", result.archive_sha[:12]))
        rows.append(KeyValueRow(f"rows_{vintage}", str(total)))
    outcome = publish_index(paths, branch=options.branch)
    rows.append(KeyValueRow("published", str(outcome.published)))
    rows.append(KeyValueRow("snapshot_id", outcome.snapshot_id or "none"))
    render_output(rows, title="Datasets Import")
    return 0


__all__ = ["cmd_import"]
