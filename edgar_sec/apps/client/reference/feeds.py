"""Facade read surface over the structured-disclosure feed ledger.

Read-only over the published feeds store: it resolves the ledger tip,
reads its active parts, and never fetches. An unstored ledger is an
honest absence, reported as such rather than repaired with a live call.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from edgar_sec.infra.storage.duckdb import connect, sql_literal, sql_path_list
from edgar_sec.pipelines.feeds.ledger import active_part_paths, ledger_tip
from edgar_sec.pipelines.feeds.paths import resolve_feeds_paths


@dataclass(frozen=True, slots=True)
class FeedLedgerEvent:
    """One ledger event: a filing as served, with every source that listed it."""

    accession: str
    cik: str
    form: str
    company_name: str
    filing_date: date
    acceptance_datetime: datetime | None
    link: str
    sources: tuple[str, ...]
    fetched_at: str


@dataclass(frozen=True, slots=True)
class FeedEventsResult:
    """Events read from one ledger tip; ``ledger_present`` marks absence."""

    events: tuple[FeedLedgerEvent, ...]
    snapshot_id: str | None
    ledger_present: bool


def _as_date(value: date | str | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def read_feed_events(
    artifacts_root: str | Path | None = None,
    *,
    forms: Sequence[str] = (),
    sources: Sequence[str] = (),
    filed_from: date | str | None = None,
    filed_to: date | str | None = None,
    limit: int | None = None,
) -> FeedEventsResult:
    """Read ledger events filtered by form, source, and filing-date range."""
    paths = resolve_feeds_paths(artifacts_root)
    tip = ledger_tip(paths)
    if tip is None:
        return FeedEventsResult(events=(), snapshot_id=None, ledger_present=False)
    parts = active_part_paths(paths, tip)
    table = f"read_parquet({sql_path_list([str(part) for part in parts])})"
    conditions: list[str] = []
    if forms:
        listed = ", ".join(sql_literal(str(form)) for form in forms)
        conditions.append(f"form IN ({listed})")
    start = _as_date(filed_from)
    if start is not None:
        conditions.append(f"filing_date >= {sql_literal(start.isoformat())}")
    end = _as_date(filed_to)
    if end is not None:
        conditions.append(f"filing_date <= {sql_literal(end.isoformat())}")
    if sources:
        listed = ", ".join(sql_literal(str(source)) for source in sources)
        conditions.append(
            "accession_normalized IN "
            f"(SELECT accession_normalized FROM {table} WHERE source IN ({listed}))"
        )
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    limit_sql = f" LIMIT {int(limit)}" if limit is not None else ""
    query = (
        "SELECT accession, cik, form, company_name, filing_date, "
        "acceptance_datetime, link, string_agg(DISTINCT source, ',') AS sources, "
        f"max(fetched_at) AS fetched_at FROM {table} {where} "
        "GROUP BY accession_normalized, accession, cik, form, company_name, "
        "filing_date, acceptance_datetime, link "
        f"ORDER BY filing_date DESC, accession {limit_sql}"
    )
    con = connect()
    try:
        rows = con.execute(query).fetchall()
    finally:
        con.close()
    events = tuple(
        FeedLedgerEvent(
            accession=str(row[0]),
            cik=str(row[1]),
            form=str(row[2]),
            company_name=str(row[3]),
            filing_date=row[4],
            acceptance_datetime=(
                datetime.fromisoformat(str(row[5])) if row[5] is not None else None
            ),
            link=str(row[6]),
            sources=tuple(sorted(str(row[7]).split(","))) if row[7] else (),
            fetched_at=str(row[8]),
        )
        for row in rows
    )
    return FeedEventsResult(events=events, snapshot_id=tip, ledger_present=True)


__all__ = ["FeedEventsResult", "FeedLedgerEvent", "read_feed_events"]
