"""Typed records served by earnings-exhibit extraction."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExhibitCandidate:
    """One filename-selected EX-99 exhibit, in selection order."""

    filename: str
    document_type: str
    exhibit_number: int
    family: str
    kind: str


@dataclass(frozen=True, slots=True)
class EarningsTableRow:
    """One logical table row: its label and its values as printed."""

    label: str
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EarningsTable:
    """One structured exhibit table riding the geometry machinery."""

    table_index: int
    caption: str | None
    periods: tuple[str, ...]
    rows: tuple[EarningsTableRow, ...]
    roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HeadlineFigure:
    """One headline figure as printed in its source table row."""

    label: str
    value: str


@dataclass(frozen=True, slots=True)
class HeadlineFigures:
    """Headline figures read from one table of the effective exhibit."""

    revenue: HeadlineFigure | None
    net_income: HeadlineFigure | None
    eps: HeadlineFigure | None
    source_table_index: int
    locus: str


@dataclass(frozen=True, slots=True)
class ReviewSignal:
    """Accounting for content the extractor did not structure."""

    kind: str
    specimen_class: str
    filename: str
    table_index: int | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class EarningsExhibitResult:
    """Extraction outcome for one filing's earnings exhibit."""

    accession: str
    form: str
    exhibit: ExhibitCandidate | None
    tables: tuple[EarningsTable, ...]
    headline: HeadlineFigures | None
    review_signals: tuple[ReviewSignal, ...]
    text: str
    image_exhibits: tuple[str, ...] = ()
    absence_reason: str | None = None


__all__ = [
    "EarningsExhibitResult",
    "EarningsTable",
    "EarningsTableRow",
    "ExhibitCandidate",
    "HeadlineFigure",
    "HeadlineFigures",
    "ReviewSignal",
]
