"""Tabular grid partitioning for SEC forms into header, data, and instructions."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.common.entities import (
    INSTRUCTION_SIGNATURE_PHRASES,
    TABULAR_STOPWORDS,
)
from edgar_sec.engine.tables.ascii_html.converter import ResolvedGrid

_STOPWORDS_SET = frozenset(TABULAR_STOPWORDS)


@dataclass(frozen=True, slots=True)
class GridPartition:
    """Segmented rows and header index from a table grid."""

    header_index: int | None
    data_rows: tuple[tuple[str, ...], ...]
    instruction_rows: tuple[tuple[str, ...], ...]


def is_instruction_row(row_text: str) -> bool:
    """Detect whether a row is instructional prose or statutory boilerplate."""
    lower = row_text.lower()
    if any(phrase in lower for phrase in INSTRUCTION_SIGNATURE_PHRASES):
        return True
    tokens = [w for w in lower.split() if w.isalpha()]
    if len(tokens) >= 10:
        stop_count = sum(1 for w in tokens if w in _STOPWORDS_SET)
        if stop_count >= 7 and (stop_count / len(tokens)) >= 0.35:
            return True
    return False


def partition_grid_rows(
    grid: ResolvedGrid,
    header_keywords: set[str] | frozenset[str],
    *,
    min_header_score: int = 6,
) -> GridPartition:
    """Partition table rows into header, clean data rows, and instruction rows."""
    header_idx: int | None = None
    data_rows: list[tuple[str, ...]] = []
    instruction_rows: list[tuple[str, ...]] = []

    for idx, row in enumerate(grid.rows):
        row_str = " ".join(c.strip() for c in row if c.strip())
        if not row_str:
            continue
        lower = row_str.lower().replace("(", " ").replace(")", " ")
        tokens = set(lower.split())
        h_score = len(tokens & header_keywords)

        if h_score >= min_header_score and header_idx is None:
            header_idx = idx
            continue

        if is_instruction_row(row_str):
            instruction_rows.append(row)
            continue

        if header_idx is not None:
            data_rows.append(row)

    return GridPartition(
        header_index=header_idx,
        data_rows=tuple(data_rows),
        instruction_rows=tuple(instruction_rows),
    )


__all__ = [
    "GridPartition",
    "is_instruction_row",
    "partition_grid_rows",
]
