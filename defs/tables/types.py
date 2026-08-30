"""Type inference, currency detection, and year extraction for table data."""

from __future__ import annotations

from .currencies import MAJOR_CURRENCIES
from .patterns import (
    BILLION_RE,
    MILLION_RE,
    NUMERIC_RE,
    NUMERIC_WITH_SYMBOLS,
    PARAGRAPH_THRESHOLD,
    PERCENT_HEADER_RE,
    TABLE_OF_CONTENTS_RE,
    THOUSAND_RE,
    UNIT_RE,
    YEAR_RE,
)
from .tokens import (
    PREFIX_SYMBOLS,
    SUFFIX_SYMBOLS,
    is_financial_placeholder,
    is_numeric_start,
)


def detect_table_currency(context: str) -> str:
    """Detect primary currency from context (defaults to 'USD')."""
    if not context:
        return "USD"

    context_lower = context.lower()

    for currency_code, currency_data in MAJOR_CURRENCIES.items():
        for name in currency_data.get("names", []):
            if name in context_lower:
                return currency_code

    for currency_code, currency_data in MAJOR_CURRENCIES.items():
        for symbol in currency_data.get("symbols", []):
            if symbol in context:
                return currency_code

    return "USD"


def scan_for_multiplier(text: str) -> float | None:
    """Detect thousand/million/billion multipliers."""
    if not text:
        return None
    if BILLION_RE.search(text):
        return 1_000_000_000.0
    if MILLION_RE.search(text):
        return 1_000_000.0
    if THOUSAND_RE.search(text):
        return 1_000.0
    return None


def is_numeric(val: str) -> bool:
    """Check if value is numeric."""
    clean = val.strip()
    if is_financial_placeholder(clean):
        return False
    clean = NUMERIC_WITH_SYMBOLS.sub("", clean).strip()
    clean = UNIT_RE.sub("", clean)
    return bool(NUMERIC_RE.match(clean))


def is_percentage_header(header_text: str) -> bool:
    if not header_text:
        return False
    return bool(PERCENT_HEADER_RE.search(header_text))


def detect_primitive_type(sample_cells: list[str]) -> str | None:
    """Detect primitive column type from sample data."""
    if not sample_cells:
        return None

    date_count = 0
    percent_count = 0
    dollar_count = 0
    value_count = 0
    text_count = 0

    for cell in sample_cells:
        if not cell:
            continue

        if YEAR_RE.search(cell):
            date_count += 1
        elif "%" in cell:
            percent_count += 1
        elif any(symbol in cell for symbol in PREFIX_SYMBOLS | SUFFIX_SYMBOLS):
            dollar_count += 1
        elif is_numeric(cell):
            value_count += 1
        else:
            text_count += 1

    total = len(sample_cells)
    if total == 0:
        return None

    if text_count > total * 0.5:
        return "text"

    has_date = date_count > total * 0.1
    has_percent = percent_count > total * 0.1
    has_numeric = (dollar_count + value_count) > total * 0.1

    if sum([has_date, has_percent, has_numeric]) > 1:
        return "mixed"

    if date_count > total * 0.5:
        return "date"
    if percent_count > total * 0.5:
        return "percentage"
    if dollar_count > total * 0.5:
        return "dollar"
    if value_count > total * 0.5:
        return "value"

    if (dollar_count + value_count) > total * 0.5:
        return "dollar" if dollar_count > value_count else "value"

    return "mixed"


def normalize_percentage_columns(
    rows: list[list[str]],
    col_map: dict[int, str | None],
    col_headers: dict[int, str],
) -> list[list[str]]:
    """Ensure numeric values carry '%' for percentage columns."""
    percent_cols = {
        idx
        for idx, header in col_headers.items()
        if is_percentage_header(header) or col_map.get(idx) == "percentage"
    }
    if not percent_cols:
        return rows

    normalized_rows: list[list[str]] = []
    for row in rows:
        new_row = list(row)
        for idx in percent_cols:
            if idx >= len(new_row):
                continue
            cell = new_row[idx].strip()
            if not cell or is_financial_placeholder(cell):
                continue
            if "%" in cell:
                continue
            if is_numeric(cell):
                new_row[idx] = f"{cell}%"
        normalized_rows.append(new_row)

    return normalized_rows


def detect_paragraph_masquerading_as_table(data: list[list[str]]) -> bool:
    """Check if this is actually a paragraph, not a table."""
    if not data:
        return False

    if TABLE_OF_CONTENTS_RE.search("\n".join(" ".join(row) for row in data)):
        return True

    first_col_max_length = max((len(row[0]) for row in data if row), default=0)
    return first_col_max_length > PARAGRAPH_THRESHOLD


def extract_years_from_headers(col_headers: dict[int, str]) -> dict[int, int]:
    """Detect column years from headers with forward-filling."""
    years_map = {}
    sorted_indices = sorted(col_headers.keys())
    last_year = None

    for idx in sorted_indices:
        header = col_headers[idx]
        detected_year = None

        if header:
            extracted_years = []
            matches = YEAR_RE.findall(header)

            for m in matches:
                groups = m if isinstance(m, tuple) else [m]
                for g in groups:
                    if g and g.isdigit():
                        y = int(g)
                        if y < 100:
                            y += 2000 if y < 50 else 1900
                        extracted_years.append(y)

            valid_years = [y for y in extracted_years if 1900 <= y <= 2100]
            if valid_years:
                detected_year = max(valid_years)

        if detected_year:
            years_map[idx] = detected_year
            last_year = detected_year
        elif last_year is not None:
            years_map[idx] = last_year

    return years_map


def extract_row_years(data: list[list[str]]) -> dict[int, int]:
    """Detect row years from transposed section headers."""
    row_years = {}
    current_year = None

    for idx, row in enumerate(data):
        if not row:
            continue

        first_cell = row[0].strip()
        is_header = False

        other_cells_empty = True
        for cell in row[1:]:
            if cell.strip():
                other_cells_empty = False
                break

        if other_cells_empty and first_cell:
            matches = YEAR_RE.findall(first_cell)
            valid_years_found = []
            for m in matches:
                groups = m if isinstance(m, tuple) else [m]
                for g in groups:
                    if g and g.isdigit():
                        y = int(g)
                        if y < 100:
                            y += 2000 if y < 50 else 1900
                        if 1900 <= y <= 2100:
                            valid_years_found.append(y)

            unique_years = set(valid_years_found)
            if len(unique_years) == 1:
                current_year = unique_years.pop()
                is_header = True

        if not is_header and current_year is not None:
            row_years[idx] = current_year

    return row_years


__all__ = [
    "detect_paragraph_masquerading_as_table",
    "detect_primitive_type",
    "detect_table_currency",
    "extract_row_years",
    "extract_years_from_headers",
    "is_numeric",
    "is_numeric_start",
    "is_percentage_header",
    "normalize_percentage_columns",
    "scan_for_multiplier",
]
