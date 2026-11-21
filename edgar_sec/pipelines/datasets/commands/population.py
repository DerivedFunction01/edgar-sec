"""Population command: load the BDC Report register and publish the index."""

from __future__ import annotations

from datetime import UTC, datetime

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.infra.sec_http.client import SecHttpClient

from ..ingest import import_bdc_population
from ..options import DatasetsOptions
from ..publish import publish_index
from ..specs import BDC_POPULATION_YEARS

from .client import build_client


def population_years(
    *, latest_year: int, count: int = BDC_POPULATION_YEARS
) -> tuple[int, ...]:
    """The report years the register unions: the latest ``count`` years."""
    return tuple(range(latest_year, latest_year - count, -1))


def cmd_population(
    options: DatasetsOptions,
    *,
    years: tuple[int, ...] | None = None,
    http: SecHttpClient | None = None,
) -> int:
    """Load the BDC population relation from the report years and publish."""
    client = http or build_client()
    paths = options.datasets_paths()
    chosen = years or population_years(latest_year=datetime.now(UTC).year)
    loaded = import_bdc_population(paths, chosen, http=client)
    outcome = publish_index(paths, branch=options.branch)
    render_output(
        [
            KeyValueRow("command", "population"),
            KeyValueRow("years", ",".join(str(year) for year in chosen)),
            KeyValueRow("report_rows", str(loaded)),
            KeyValueRow("published", str(outcome.published)),
            KeyValueRow("snapshot_id", outcome.snapshot_id or "none"),
        ],
        title="Datasets Population",
    )
    return 0


__all__ = ["cmd_population", "population_years"]
