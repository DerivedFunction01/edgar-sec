"""Targeting queries and execution configuration for high-throughput pipeline runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from edgar_sec.domain.filing_catalog.filters import (
    AbsoluteDateClause,
    DateInterval,
    DateRange,
    DateSelection,
    RecurringDateClause,
    format_date_selection,
    resolve_date_selection,
)

if TYPE_CHECKING:
    from edgar_sec.infra.sec_http.client import SecHttpClient

MaterializeMode = Literal["none", "specific", "all"]

DateFilterInput = (
    DateRange
    | DateInterval
    | DateSelection
    | AbsoluteDateClause
    | RecurringDateClause
    | date
    | tuple[date | None, date | None]
    | str
    | None
)


@dataclass(frozen=True, slots=True)
class FilingQuery:
    """Target selection and operation contract shared across fast and pipeline modes."""

    tickers: tuple[str, ...] = ()
    ciks: tuple[str, ...] = ()
    accessions: tuple[str, ...] = ()
    input_file: Path | str | None = None
    forms: tuple[str, ...] = ()
    dates: DateFilterInput = None
    roles: tuple[str, ...] = ("primary",)
    suffixes: tuple[str, ...] = ()
    limit: int | None = None
    operations: tuple[str, ...] = ("raw",)

    def resolved_date_selection(self) -> DateSelection:
        """Resolve dates into a canonical DateSelection tuple."""
        return resolve_date_selection(self.dates)

    def resolved_date_string(self) -> str | None:
        """Format the resolved date selection into a canonical date filter string."""
        sel = self.resolved_date_selection()
        return format_date_selection(sel) if sel else None


@dataclass(frozen=True, slots=True)
class PipelineConfig(FilingQuery):
    """End-to-end S6 pipeline orchestration specification adding execution policies."""

    materialize: MaterializeMode = "specific"
    sync_metadata: bool = True
    workers: int | None = None
    sec_client: SecHttpClient | None = None
    artifacts_root: Path | None = None


__all__ = [
    "DateFilterInput",
    "FilingQuery",
    "MaterializeMode",
    "PipelineConfig",
]
