"""Scoped template repair for SEC Regulation S-K Item 703 repurchase schedules."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from defs.regex import build_alternation
from defs.tables.builder import HTMLTableConverter
from defs.tables.currencies import detect_currency_affix, format_currency
from defs.tables.tokens import ALL_CURRENCY_SYMBOLS
from defs.text.dates import MONTH_RE, extract_years, parse_date

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


def _is_footnote_marker(cell: str) -> bool:
    """Return whether a cell is only a parenthesized footnote marker."""
    return bool(re.fullmatch(r"\((?:[a-z]|\d{1,3})\)", cell.strip(), re.IGNORECASE))


def _compact_data_row(row: list[str]) -> list[str]:
    """Remove layout blanks and join standalone currency prefixes."""
    values = [cell.strip() for cell in row if cell.strip()]
    compact: list[str] = []
    index = 0
    while index < len(values):
        value = values[index]
        if value in ALL_CURRENCY_SYMBOLS and index + 1 < len(values):
            compact.append(value + values[index + 1])
            index += 2
        else:
            compact.append(value)
            index += 1
    return compact


def _is_period_or_total_cell(cell: str) -> bool:
    """Return whether a cell represents a period/date label or total summary."""
    if not cell:
        return False
    return bool(MONTH_RE.search(cell) or _TOTAL_RE.search(cell) or extract_years(cell))


def _looks_like_data_row(row: list[str]) -> bool:
    """Require a period/total label plus at least one value-like cell."""
    first = next((cell.strip() for cell in row if cell.strip()), "")
    if not first or not _is_period_or_total_cell(first):
        return False
    remaining = [cell.strip() for cell in row[1:] if cell.strip()]
    if _TOTAL_RE.search(first):
        return any(bool(re.search(r"\d", cell)) for cell in remaining)
    return any(
        cell in {"-", "--", "—", "–"}
        or parse_date(cell) is not None
        or bool(re.search(r"\d", cell))
        for cell in remaining
    )


def _header_role_cells(source_grid: list[list[str]]) -> list[set[str]]:
    """Return statutory roles matched by each populated header cell."""
    roles: list[set[str]] = []
    for row in source_grid[: min(4, len(source_grid))]:
        for cell in row:
            text = cell.strip().lower()
            if not text:
                continue
            matched = {
                role
                for role, alternatives in SHARES_PURCHASED_STATUTORY_PHRASES.items()
                if any(alt in text for alt in alternatives)
            }
            if "P3_announced_plans" in matched:
                matched.discard("P1_total_shares")
            if matched:
                roles.append(matched)
    return roles


def _matches_shares_purchased_headers(grid: list[list[str]]) -> bool:
    """Check if table header text matches at least two Item 703 statutory phrases."""
    header_rows = grid[: min(4, len(grid))]
    header_text = " ".join(c.lower() for r in header_rows for c in r if c.strip())

    phrase_matches = 0
    for alternatives in SHARES_PURCHASED_STATUTORY_PHRASES.values():
        if any(alt in header_text for alt in alternatives):
            phrase_matches += 1

    role_cells = _header_role_cells(grid)
    # A cell containing two roles usually means an unrepaired concatenated
    # header from another schedule, not a valid five-column Item 703 table.
    if any(len(matched) > 1 for matched in role_cells):
        return False
    return phrase_matches >= 3


def _extract_original_headers(
    source_grid: list[list[str]], split_idx: int
) -> list[str]:
    """Extract the table's exact original header text, falling back to canonical defaults."""
    header_rows = source_grid[:split_idx]
    if not header_rows:
        return list(CANONICAL_REPURCHASE_HEADERS)

    # Extract non-empty labels from the primary header row
    primary = [c.strip() for c in header_rows[0] if c.strip()]
    if primary and re.fullmatch(r"(?:19|20)\d{2}", primary[0]) and len(primary) == 5:
        # A filing year can be a super-header above the four statutory
        # measures; it is not the first data/period column.
        primary = ["Period", *primary[1:]]
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
        if _looks_like_data_row(row):
            split_idx = idx
            break

    raw_data_rows = source_grid[split_idx:]
    if not raw_data_rows:
        return None

    # Only repair if data rows exhibit column jitter (i.e. shifting column positions
    # due to empty spacer columns or split currency symbols).
    footnote_columns = {
        index
        for row in raw_data_rows
        for index, cell in enumerate(row)
        if _is_footnote_marker(cell)
    }
    cleaned_data_rows = [
        _compact_data_row(
            [cell for index, cell in enumerate(row) if index not in footnote_columns]
        )
        for row in raw_data_rows
    ]

    patterns: set[tuple[int, ...]] = set()
    for row in cleaned_data_rows:
        first_cell = row[0].strip() if row else ""
        if _TOTAL_RE.search(first_cell) or not first_cell:
            continue
        data_cells = row[1:] if len(row) > 1 else []
        indices = tuple(i for i, c in enumerate(data_cells, start=1) if c.strip())
        if indices:
            patterns.add(indices)

    has_footnote_cells = bool(footnote_columns)
    has_split_affix = any(
        cell.strip() in ALL_CURRENCY_SYMBOLS for row in raw_data_rows for cell in row
    )
    if (
        len(patterns) <= 1
        and not has_footnote_cells
        and not has_split_affix
        and split_idx <= 1
    ):
        return None

    currency_symbol, is_suffix = detect_currency_affix(source_grid)
    headers = _extract_original_headers(source_grid, split_idx)
    remaining_is_currency = "dollar value" in " ".join(headers).casefold()
    repaired_data_rows: list[list[str]] = []

    for row in cleaned_data_rows:
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
        positional_values = [c.strip() for c in data_cells]
        values = [c for c in positional_values if c and c not in ALL_CURRENCY_SYMBOLS]

        mapped_values = positional_values if footnote_columns else values
        if len(mapped_values) >= 4:
            if footnote_columns:
                shares, price, announced, remaining = mapped_values[:4]
            else:
                shares, price, announced, remaining = mapped_values[:4]
            if price in ALL_CURRENCY_SYMBOLS:
                price = ""
            if announced in ALL_CURRENCY_SYMBOLS:
                announced = ""
            if remaining in ALL_CURRENCY_SYMBOLS:
                remaining = ""

            if re.match(r"^\d+\.\d{2}$", price):
                price = format_currency(price, currency_symbol, is_suffix=is_suffix)
            if remaining_is_currency and re.match(r"^\d", remaining):
                remaining = format_currency(
                    remaining, currency_symbol, is_suffix=is_suffix
                )

            repaired_data_rows.append(
                [period_label, shares, price, announced, remaining]
            )
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
