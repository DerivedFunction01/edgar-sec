"""Shared tabular row extraction: declarative columns, cell scans, and evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TypeVar

from edgar_sec.engine.forms.common.extraction import (
    ExtractedValue,
    FieldSpec,
    extract_value,
)
from edgar_sec.engine.tables.currencies import ALL_CURRENCY_SYMBOLS
from edgar_sec.engine.tables.numeric_cells import is_numeric_cell
from edgar_sec.foundation.text.dates import NUMERIC_DATE_RE

_Record = TypeVar("_Record")


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """A table column bound to a shared field specification."""

    name: str
    field: FieldSpec


@dataclass(frozen=True, slots=True)
class RowSpec:
    """Declarative column set describing one tabular schema."""

    name: str
    columns: tuple[ColumnSpec, ...]

    def column(self, name: str) -> ColumnSpec | None:
        for column in self.columns:
            if column.name == name:
                return column
        return None


@dataclass(frozen=True, slots=True)
class RowExtraction:
    """Canonical row values alongside their per-column extraction results."""

    values: dict[str, str | None]
    results: tuple[ExtractedValue, ...]
    normalized: dict[str, str | None]

    def evidence(self) -> tuple[dict[str, object], ...]:
        records: list[dict[str, object]] = []
        for result in self.results:
            if result.issue is None or not (result.raw_value or "").strip():
                continue
            record = result.unresolved_record()
            if record is not None:
                records.append(record)
        return tuple(records)


def extract_row(
    values: Mapping[str, object],
    spec: RowSpec,
    *,
    reference_year: int | None = None,
    path_prefix: str = "",
) -> RowExtraction:
    """Normalize aligned cell values through the shared field contract."""
    canonical: dict[str, str | None] = {}
    normalized_values: dict[str, str | None] = {}
    results: list[ExtractedValue] = []
    for column in spec.columns:
        raw = values.get(column.name)
        text = raw if isinstance(raw, str) else (None if raw is None else str(raw))
        result = extract_value(text, column.field, reference_year=reference_year)
        results.append(replace(result, path=f"{path_prefix}{column.field.path}"))
        canonical[column.name] = (
            result.normalized if result.normalized is not None else text
        )
        normalized_values[column.name] = result.normalized
    return RowExtraction(canonical, tuple(results), normalized_values)


def as_integer(value: str | int | None) -> int | str | None:
    """Return an integer for integral text, retaining the raw text otherwise."""
    if isinstance(value, int) or value is None:
        return value
    text = value.strip()
    return int(text) if text.isdigit() else value


def normalize_row_record(
    record: _Record,
    spec: RowSpec,
    *,
    reference_year: int | None = None,
    path_prefix: str = "",
) -> tuple[_Record, RowExtraction]:
    """Return a record with spec-normalized fields plus its extraction results."""
    values = {
        column.name: getattr(record, column.name, None) for column in spec.columns
    }
    extraction = extract_row(
        values,
        spec,
        reference_year=reference_year,
        path_prefix=path_prefix,
    )
    updates = {
        column.name: extraction.values[column.name]
        for column in spec.columns
        if hasattr(record, column.name)
    }
    return replace(record, **updates), extraction


def split_row_cells(row: Sequence[str]) -> tuple[str, ...]:
    """Split a raw row into cells, expanding pipe-delimited compound cells."""
    return tuple(
        part.strip()
        for cell in row
        if cell.strip()
        for part in cell.split("|")
        if part.strip()
    )


def scan_date_cells(cells: Sequence[str]) -> tuple[tuple[int, str], ...]:
    """Locate numeric date cells with their index and matched text."""
    return tuple(
        (index, match.group(0))
        for index, cell in enumerate(cells)
        if (match := NUMERIC_DATE_RE.search(cell))
    )


def scan_numeric_cells(
    cells: Sequence[str],
    *,
    excluded: frozenset[int] = frozenset(),
    currency: bool = False,
    deny: tuple[str, ...] = ("|",),
) -> tuple[tuple[int, str], ...]:
    """Locate numeric cells with their index and raw text."""
    found: list[tuple[int, str]] = []
    for index, cell in enumerate(cells):
        if index in excluded:
            continue
        lowered = cell.lower()
        if any(marker in lowered for marker in deny):
            continue
        has_currency = any(symbol in cell for symbol in ALL_CURRENCY_SYMBOLS)
        if has_currency and not currency:
            continue
        if is_numeric_cell(cell) or has_currency:
            found.append((index, cell))
    return tuple(found)


__all__ = [
    "ColumnSpec",
    "RowExtraction",
    "RowSpec",
    "as_integer",
    "extract_row",
    "normalize_row_record",
    "scan_date_cells",
    "scan_numeric_cells",
    "split_row_cells",
]
