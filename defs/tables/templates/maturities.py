"""Scoped 2D template repair for ASC 842 / ASC 470 lease and debt maturity schedules."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from defs.tables.builder import HTMLTableConverter
from defs.tables.currencies import detect_currency_affix, format_currency
from defs.tables.tokens import ALL_CURRENCY_SYMBOLS
from defs.text.dates import extract_years

if TYPE_CHECKING:
    from defs.sec_forms.context import SectionContext

LEASE_MATURITY_PRIMARY_TERMS: tuple[str, ...] = (
    "total minimum lease payments",
    "present value of lease",
    "present value of lease liabilities",
    "imputed interest",
    "amount representing interest",
    "future minimum rent",
    "undiscounted lease liabilities",
    "maturities of lease liabilities",
    "undiscounted cash flows",
)

DEBT_MATURITY_PRIMARY_TERMS: tuple[str, ...] = (
    "principal maturities",
    "aggregate maturities",
    "maturities of long-term debt",
    "maturities of debt",
    "sinking fund requirements",
    "sinking fund",
    "annual maturities of long-term debt",
)

if TYPE_CHECKING:
    from defs.sec_forms.context import SectionContext

_THEREAFTER_RE = re.compile(r"\bthereafter\b", re.IGNORECASE)
_TOTAL_RE = re.compile(r"\b(?:total|subtotal)\b", re.IGNORECASE)


def _is_maturity_schedule(grid: list[list[str]]) -> bool:
    """Check if table text contains lease or debt maturity primary terms."""
    full_text = " ".join(c.lower() for r in grid for c in r if c.strip())
    has_lease = any(p in full_text for p in LEASE_MATURITY_PRIMARY_TERMS)
    has_debt = any(p in full_text for p in DEBT_MATURITY_PRIMARY_TERMS)
    has_thereafter = bool(_THEREAFTER_RE.search(full_text))
    return (has_lease or has_debt) and has_thereafter


def maturity_schedule_template(
    source_grid: list[list[str]],
    *,
    section_context: SectionContext | None = None,
) -> str | None:
    """Repair and project jittered lease/debt maturity schedules into clean 2D tabular layout."""
    _ = section_context
    if len(source_grid) < 4 or len(source_grid) > 35:
        return None

    if not _is_maturity_schedule(source_grid):
        return None

    # Detect header row boundary
    split_idx = 1
    for idx, row in enumerate(source_grid[:4]):
        first = row[0].strip() if row else ""
        if extract_years(first) or _THEREAFTER_RE.search(first):
            split_idx = idx
            break

    raw_data = source_grid[split_idx:]
    if not raw_data:
        return None

    # Check for column jitter across multi-cell data rows
    patterns: set[tuple[int, ...]] = set()
    for row in raw_data:
        first = row[0].strip() if row else ""
        if _TOTAL_RE.search(first) or not first or first.endswith(":"):
            continue
        data_cells = row[1:] if len(row) > 1 else []
        indices = tuple(i for i, c in enumerate(data_cells, start=1) if c.strip())
        if len(indices) >= 1:
            patterns.add(indices)

    if len(patterns) <= 1:
        return None

    currency_symbol, is_suffix = detect_currency_affix(source_grid)
    headers = [c.strip() for c in source_grid[0] if c.strip()]
    if len(headers) < 2:
        headers = ["Maturity / Fiscal Year", "Amount"]

    repaired_rows: list[list[str]] = []
    for row in raw_data:
        non_empty = [c.strip() for c in row if c.strip()]
        if not non_empty:
            continue

        label = non_empty[0]
        numeric_vals = [c for c in non_empty[1:] if c not in ALL_CURRENCY_SYMBOLS]

        if numeric_vals:
            val = numeric_vals[0]
            if re.match(r"^\d", val) and not extract_years(val):
                val = format_currency(val, currency_symbol, is_suffix=is_suffix)
            repaired_rows.append([label, val])
        else:
            repaired_rows.append([label, ""])

    if not repaired_rows:
        return None

    clean_grid = [headers[:2]] + repaired_rows
    return (
        HTMLTableConverter(grid=clean_grid, header_row_count=1)
        .to_generic_table()
        .build()
    )
