"""Series/class command: refresh the reference relation from SEC sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.domain.browse_urls import browse_series_url
from edgar_sec.domain.sec_urls import SEC_DATASETS_BASE, normalize_cik
from edgar_sec.engine.index_pages.parser_browse import (
    BrowsePageInput,
    ParsedBrowseSeriesPage,
    UnrecognizedBrowsePage,
    parse_browse_series_page,
)
from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.infra.sec_http.client import SecHttpClient

from ..paths import resolve_metadata_paths
from ..series_class import (
    MF_TICKER_SOURCE_NAME,
    SeriesClassPublishOutcome,
    SeriesClassReconciliation,
    ingest_mf_ticker_payload,
    publish_series_class,
    read_tickered_rows,
    reconcile_series_class,
    series_class_tip,
)
from ..series_class_browse import (
    ingest_browse_page,
    read_browse_rows,
    read_browse_series_rows,
)
from .client import build_client

__all__ = [
    "MF_TICKER_URL",
    "SeriesClassRefreshOutcome",
    "SeriesClassStatus",
    "cmd_series_class_refresh",
    "read_series_class_reconciliation",
    "read_series_class_status",
    "refresh_series_class",
]

MF_TICKER_URL = f"{SEC_DATASETS_BASE}/{MF_TICKER_SOURCE_NAME}.json"
_SAMPLE_LIMIT = 10


@dataclass(frozen=True, slots=True)
class SeriesClassRefreshOutcome:
    """One refresh drive: per-CIK accounting, publication, reconciliation."""

    population: int
    parsed_ingested: int
    parse_failures: int
    unrecognized: int
    fetch_failures: int
    publish: SeriesClassPublishOutcome
    tip_after: str | None
    reconciliation: SeriesClassReconciliation
    symbol_disagreement_samples: tuple[tuple[str, str, str], ...]
    failure_samples: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class SeriesClassStatus:
    """The published series/class tip and its per-layer row counts."""

    tip: str | None
    tickered_rows: int
    browse_class_rows: int
    browse_series_rows: int


def _population(paths, ciks: tuple[str, ...]) -> list[str]:
    if ciks:
        return sorted({normalize_cik(cik) for cik in ciks})
    return sorted({row.cik for row in read_tickered_rows(paths)})


def _disagreement_samples(paths) -> tuple[tuple[str, str, str], ...]:
    file_symbols = {row.class_id: row.symbol for row in read_tickered_rows(paths)}
    samples: list[tuple[str, str, str]] = []
    for row in read_browse_rows(paths):
        file_symbol = file_symbols.get(row.class_id)
        if (
            file_symbol is not None
            and row.symbol is not None
            and row.symbol != file_symbol
        ):
            samples.append((row.class_id, file_symbol, row.symbol))
            if len(samples) >= _SAMPLE_LIMIT:
                break
    return tuple(samples)


def refresh_series_class(
    *,
    artifacts_root: str | Path | None = None,
    branch: str = "main",
    ciks: tuple[str, ...] = (),
    force_refresh: bool = False,
    workers: int | None = None,
    http: SecHttpClient | None = None,
) -> SeriesClassRefreshOutcome:
    """Fetch the MF payload and the population's series pages; publish.

    Fetches run sequentially through the one client, whose rate limiter
    owns pacing; ``workers`` never multiplies HTTP clients.
    """
    paths = resolve_metadata_paths(artifacts_root)
    client = http or build_client().http
    payload = client.get_bytes(MF_TICKER_URL, mutable=True, force_refresh=force_refresh)
    ingest_mf_ticker_payload(payload, paths)
    population = _population(paths, ciks)
    parsed = parse_failures = unrecognized = fetch_failures = 0
    failure_samples: list[tuple[str, str]] = []
    for cik in population:
        url = browse_series_url(cik)
        try:
            page_bytes = client.get_bytes(url, force_refresh=force_refresh)
        except Exception:  # noqa: BLE001 - one CIK's failure is accounted, not fatal
            fetch_failures += 1
            if len(failure_samples) < _SAMPLE_LIMIT:
                failure_samples.append((cik, "fetch_failure"))
            continue
        outcome = parse_browse_series_page(
            BrowsePageInput(cik=cik, source_url=url, response_bytes=page_bytes)
        )
        if isinstance(outcome, ParsedBrowseSeriesPage):
            ingest_browse_page(outcome, paths)
            parsed += 1
        elif isinstance(outcome, UnrecognizedBrowsePage):
            unrecognized += 1
            if len(failure_samples) < _SAMPLE_LIMIT:
                failure_samples.append((cik, "unrecognized"))
        else:
            parse_failures += 1
            if len(failure_samples) < _SAMPLE_LIMIT:
                failure_samples.append((cik, "parse_failure"))
    publish = publish_series_class(paths, branch=branch)
    return SeriesClassRefreshOutcome(
        population=len(population),
        parsed_ingested=parsed,
        parse_failures=parse_failures,
        unrecognized=unrecognized,
        fetch_failures=fetch_failures,
        publish=publish,
        tip_after=series_class_tip(paths, branch),
        reconciliation=reconcile_series_class(paths),
        symbol_disagreement_samples=_disagreement_samples(paths),
        failure_samples=tuple(failure_samples),
    )


def read_series_class_status(
    *, artifacts_root: str | Path | None = None, branch: str = "main"
) -> SeriesClassStatus:
    """The series/class tip and per-layer row counts, read-only."""
    paths = resolve_metadata_paths(artifacts_root)
    return SeriesClassStatus(
        tip=series_class_tip(paths, branch),
        tickered_rows=len(read_tickered_rows(paths)),
        browse_class_rows=len(read_browse_rows(paths)),
        browse_series_rows=len(read_browse_series_rows(paths)),
    )


def read_series_class_reconciliation(
    *, artifacts_root: str | Path | None = None
) -> SeriesClassReconciliation:
    """The two stored layers counted against each other, read-only."""
    return reconcile_series_class(resolve_metadata_paths(artifacts_root))


def cmd_series_class_refresh(
    *,
    artifacts_root: str | Path | None = None,
    branch: str = "main",
    ciks: tuple[str, ...] = (),
    force_refresh: bool = False,
    workers: int | None = None,
    http: SecHttpClient | None = None,
) -> int:
    """Refresh the series/class relation and render the drive's counts."""
    outcome = refresh_series_class(
        artifacts_root=artifacts_root,
        branch=branch,
        ciks=ciks,
        force_refresh=force_refresh,
        workers=workers,
        http=http,
    )
    publish = outcome.publish
    counts = outcome.reconciliation
    render_output(
        [
            KeyValueRow("command", "series-class-refresh"),
            KeyValueRow("population", str(outcome.population)),
            KeyValueRow("parsed_ingested", str(outcome.parsed_ingested)),
            KeyValueRow("parse_failures", str(outcome.parse_failures)),
            KeyValueRow("unrecognized", str(outcome.unrecognized)),
            KeyValueRow("fetch_failures", str(outcome.fetch_failures)),
            KeyValueRow("published", str(publish.published)),
            KeyValueRow("snapshot_id", publish.snapshot_id or "none"),
            KeyValueRow("tip_before", publish.tip_before or "none"),
            KeyValueRow("tip_after", outcome.tip_after or "none"),
            KeyValueRow("series_in_both", str(counts.series_in_both)),
            KeyValueRow("series_browse_only", str(counts.series_browse_only)),
            KeyValueRow("series_file_only", str(counts.series_file_only)),
            KeyValueRow("classes_in_both", str(counts.classes_in_both)),
            KeyValueRow("classes_browse_only", str(counts.classes_browse_only)),
            KeyValueRow("classes_file_only", str(counts.classes_file_only)),
            KeyValueRow("symbol_agreements", str(counts.symbol_agreements)),
            KeyValueRow("symbol_disagreements", str(counts.symbol_disagreements)),
            KeyValueRow(
                "shared_browse_untickered",
                str(counts.shared_classes_browse_untickered),
            ),
        ],
        title="Series/Class Refresh",
    )
    return 0
