"""Scoped template repair for SEC Regulation S-K Item 703 repurchase schedules."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from defs.regex import build_alternation
from defs.tables.builder import HTMLTableConverter
from defs.tables.currencies import detect_currency_affix, format_currency
from defs.tables.tokens import ALL_CURRENCY_SYMBOLS
from defs.text.dates import MONTH_RE, extract_years

if TYPE_CHECKING:
    from defs.sec_forms.context import SectionContext

SHARES_PURCHASED_STATUTORY_PHRASES: dict[str, tuple[str, ...]] = {
    "P1_total_shares": (
        "total number of shares purchased",
        "total number of shares repurchased",
        "total number of shares (or units) purchased",
        "total number of shares (or units) repurchased",
        "total shares purchased",
        "total shares repurchased",
    ),
    "P2_average_price": (
        "average price paid per share",
        "average price paid per common share",
        "average price paid per share (or unit)",
        "average price per share",
        "average price per share paid",
    ),
    "P3_announced_plans": (
        "shares purchased as part of publicly announced plans or programs",
        "shares repurchased as part of publicly announced plans or programs",
        "total number of shares purchased as part of publicly announced",
        "total number of shares repurchased as part of publicly announced",
        "part of publicly announced plans or programs",
        "publicly announced plans or programs",
        "publicly announced share repurchase",
    ),
    "P4_yet_purchased": (
        "dollar value of shares that may yet be purchased",
        "dollar value of shares that may yet be repurchased",
        "approximate dollar value of shares that may yet be purchased",
        "maximum number (or approximate dollar value) of shares",
        "maximum number of shares that may yet be purchased",
        "may yet be purchased under the plans or programs",
        "may yet be purchased",
        "may yet be repurchased",
    ),
}

CANONICAL_REPURCHASE_HEADERS: tuple[str, ...] = (
    "Period",
    "Total Number of Shares Purchased",
    "Average Price Paid Per Share",
    "Total Number of Shares Purchased as Part of Publicly Announced Plans or Programs",
    "Approximate Dollar Value of Shares That May Yet Be Purchased Under the Plans or Programs",
)

_TOTAL_RE = re.compile(
    rf"\b{build_alternation(['total', 'subtotal'], auto_escape=True)}\b",
    re.IGNORECASE,
)


def _is_period_or_total_cell(cell: str) -> bool:
    """Return whether a cell represents a period/date label or total summary."""
    if not cell:
        return False
    return bool(MONTH_RE.search(cell) or _TOTAL_RE.search(cell) or extract_years(cell))


def _matches_shares_purchased_headers(grid: list[list[str]]) -> bool:
    """Check if table header text matches at least two Item 703 statutory phrases."""
    header_rows = grid[: min(4, len(grid))]
    header_text = " ".join(c.lower() for r in header_rows for c in r if c.strip())

    phrase_matches = 0
    for alternatives in SHARES_PURCHASED_STATUTORY_PHRASES.values():
        if any(alt in header_text for alt in alternatives):
            phrase_matches += 1

    return phrase_matches >= 2


def _extract_original_headers(
    source_grid: list[list[str]], split_idx: int
) -> list[str]:
    """Extract the table's exact original header text, falling back to canonical defaults."""
    header_rows = source_grid[:split_idx]
    if not header_rows:
        return list(CANONICAL_REPURCHASE_HEADERS)

    # Extract non-empty labels from the primary header row
    primary = [c.strip() for c in header_rows[0] if c.strip()]
    if len(primary) == 5:
        # Check if second header row contains units (e.g. "(In millions)")
        if len(header_rows) > 1:
            second = [c.strip() for c in header_rows[1] if c.strip()]
            if len(second) == 1 and any(
                unit in second[0].lower()
                for unit in ("million", "thousand", "share", "dollar")
            ):
                primary[1] = f"{primary[1]}\n{second[0]}"
        return primary

    return list(CANONICAL_REPURCHASE_HEADERS)


def shares_purchased_template(
    source_grid: list[list[str]],
    *,
    section_context: SectionContext | None = None,
) -> str | None:
    """Repair and project jittered Item 703 repurchase tables into 5 canonical columns."""
    _ = section_context
    if len(source_grid) < 3 or len(source_grid) > 30:
        return None

    if not _matches_shares_purchased_headers(source_grid):
        return None

    # Find the split index where header rows end and data rows begin
    split_idx = 1
    for idx, row in enumerate(source_grid):
        # Look for month names, years, or "total" in the first cell
        first_cell = next((c.strip() for c in row if c.strip()), "")
        if _is_period_or_total_cell(first_cell):
            split_idx = idx
            break

    raw_data_rows = source_grid[split_idx:]
    if not raw_data_rows:
        return None

    # Only repair if data rows exhibit column jitter (i.e. shifting column positions
    # due to empty spacer columns or split currency symbols).
    patterns: set[tuple[int, ...]] = set()
    for row in raw_data_rows:
        first_cell = row[0].strip() if row else ""
        if _TOTAL_RE.search(first_cell) or not first_cell:
            continue
        data_cells = row[1:] if len(row) > 1 else []
        indices = tuple(i for i, c in enumerate(data_cells, start=1) if c.strip())
        if indices:
            patterns.add(indices)

    if len(patterns) <= 1:
        return None

    currency_symbol, is_suffix = detect_currency_affix(source_grid)
    headers = _extract_original_headers(source_grid, split_idx)
    repaired_data_rows: list[list[str]] = []

    for row in raw_data_rows:
        non_empty = [c.strip() for c in row if c.strip()]
        if not non_empty:
            continue

        # Detect period label
        first_cell = row[0].strip() if row else ""
        if not first_cell:
            first_cell = non_empty[0]

        is_total = bool(_TOTAL_RE.search(first_cell) or not row[0].strip())
        period_label = "Total" if is_total else first_cell

        # Extract numeric values across the remaining cells (skipping isolated currency tokens)
        start_cell_idx = 0 if is_total and not row[0].strip() else 1
        data_cells = row[start_cell_idx:] if len(row) > start_cell_idx else []
        values = [
            c.strip()
            for c in data_cells
            if c.strip() and c.strip() not in ALL_CURRENCY_SYMBOLS
        ]

        if len(values) >= 4:
            shares = values[0]
            price = values[1]
            announced = values[2]
            remaining = values[3]

            if re.match(r"^\d+\.\d{2}$", price):
                price = format_currency(price, currency_symbol, is_suffix=is_suffix)
            if re.match(r"^\d", remaining):
                remaining = format_currency(
                    remaining, currency_symbol, is_suffix=is_suffix
                )

            repaired_data_rows.append(
                [period_label, shares, price, announced, remaining]
            )
        elif len(values) == 2 and is_total:
            repaired_data_rows.append(["Total", values[0], "", values[1], ""])
        elif values:
            padded = [period_label] + values[:4] + [""] * max(0, 4 - len(values))
            repaired_data_rows.append(padded)

    if not repaired_data_rows:
        return None

    clean_grid = [headers] + repaired_data_rows
    return (
        HTMLTableConverter(grid=clean_grid, header_row_count=1)
        .to_generic_table()
        .build()
    )
