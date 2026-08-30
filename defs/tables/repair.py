"""Row healing, column merging, split-number repair, and symbol spacing fixes."""

from __future__ import annotations

import re

from defs.regex import build_alternation

from .currencies import PREFIX_SYMBOLS, SUFFIX_SYMBOLS
from .patterns import (
    CLOSE_PAREN_SPACE_RE,
    COMMA_SPACE_RE,
    CURRENCY_SPACE_RE,
    OPEN_PAREN_SPACE_RE,
    PERCENT_SPACE_RE,
    SPACE_COMMA_RE,
    YEAR_RE,
)
from .types import is_numeric, is_numeric_start


def merge_sparse_columns(
    raw_rows: list[list[str]], single_width_cols: set[int] | None = None
) -> tuple[list[list[str]], dict[int, int]]:
    """Merge sparse columns (high empty percentage or single-width markers)."""
    if not raw_rows:
        return [], {}

    if single_width_cols is None:
        single_width_cols = set()

    num_rows = len(raw_rows)
    num_cols = max(len(row) for row in raw_rows) if raw_rows else 0
    col_sparsity = {}

    for col_idx in range(num_cols):
        empty_count = sum(
            1 for row in raw_rows if col_idx >= len(row) or not row[col_idx]
        )
        sparsity = empty_count / num_rows if num_rows > 0 else 0
        col_sparsity[col_idx] = sparsity

    sparse_columns = {idx for idx, s in col_sparsity.items() if s > 0.8}
    sparse_columns.update(single_width_cols)

    if not sparse_columns:
        return raw_rows, {i: i for i in range(num_cols)}

    merge_directions = detect_merge_patterns(raw_rows, sparse_columns)

    merged_rows = []
    col_mapping = {}

    for row in raw_rows:
        merged_row = []
        skip_next = False
        row_col_mapping = {}

        for col_idx in range(len(row)):
            if skip_next:
                skip_next = False
                continue

            cell = row[col_idx]
            strategy = merge_directions.get(col_idx, "keep")
            new_col_idx = len(merged_row)

            if strategy == "merge_right":
                if col_idx + 1 < len(row):
                    next_cell = row[col_idx + 1]
                    merged_row.append((cell + next_cell).strip())
                    skip_next = True
                    row_col_mapping[col_idx] = new_col_idx
                    row_col_mapping[col_idx + 1] = new_col_idx
                else:
                    merged_row.append(cell)
                    row_col_mapping[col_idx] = new_col_idx

            elif strategy == "merge_left":
                if merged_row:
                    merged_row[-1] = (merged_row[-1] + cell).strip()
                    row_col_mapping[col_idx] = len(merged_row) - 1
                else:
                    merged_row.append(cell)
                    row_col_mapping[col_idx] = new_col_idx

            else:
                merged_row.append(cell)
                row_col_mapping[col_idx] = new_col_idx

        if not col_mapping:
            col_mapping = row_col_mapping

        merged_rows.append(merged_row)

    return merged_rows, col_mapping


def detect_merge_patterns(
    raw_rows: list[list[str]], sparse_columns: set[int]
) -> dict[int, str]:
    """Detect if sparse columns should merge left or right."""
    merge_directions = {}

    for col_idx in sparse_columns:
        col_patterns = set()

        for row in raw_rows:
            if col_idx < len(row) and row[col_idx].strip():
                val = row[col_idx].strip()
                if val in PREFIX_SYMBOLS:
                    col_patterns.add("prefix")
                elif val in SUFFIX_SYMBOLS:
                    col_patterns.add("suffix")
                elif val == "(":
                    col_patterns.add("prefix_paren")
                elif val == ")":
                    col_patterns.add("suffix_paren")
                elif val == "%":
                    col_patterns.add("suffix_percent")
                else:
                    col_patterns.add("other")

        if not col_patterns:
            continue

        has_prefix = "prefix" in col_patterns or "prefix_paren" in col_patterns
        has_suffix = (
            "suffix" in col_patterns
            or "suffix_paren" in col_patterns
            or "suffix_percent" in col_patterns
        )
        has_other = "other" in col_patterns

        if has_prefix and not has_suffix and not has_other:
            merge_directions[col_idx] = "merge_right"
        elif has_suffix and not has_prefix and not has_other:
            merge_directions[col_idx] = "merge_left"
        else:
            merge_directions[col_idx] = "skip"

    return merge_directions


def clean_and_merge_symbols(row: list[str]) -> list[str]:
    """Clean internal spacing and merge adjacent symbols with numbers."""
    cleaned_row = []
    for cell in row:
        if not cell:
            cleaned_row.append("")
            continue
        c = CURRENCY_SPACE_RE.sub(r"\1", cell)
        c = OPEN_PAREN_SPACE_RE.sub("(", c)
        c = CLOSE_PAREN_SPACE_RE.sub(")", c)
        c = PERCENT_SPACE_RE.sub("%", c)
        c = COMMA_SPACE_RE.sub(",", c)
        c = SPACE_COMMA_RE.sub(",", c)
        cleaned_row.append(c)

    final_row = []
    skip_idx = -1

    for i, cell in enumerate(cleaned_row):
        if i <= skip_idx:
            continue

        current_val = cell

        if i + 1 < len(cleaned_row):
            next_val = cleaned_row[i + 1]

            if (
                (next_val in SUFFIX_SYMBOLS or (next_val in [")", "%"] and current_val))
                and is_numeric_start(current_val)
                or (current_val in PREFIX_SYMBOLS or (current_val == "(" and next_val))
                and is_numeric_start(next_val)
            ):
                current_val = current_val + next_val
                skip_idx = i + 1

        final_row.append(current_val)

    return final_row


def heal_data_rows(rows: list[list[str]]) -> list[list[str]]:
    """Fix rows where text has shifted into data columns."""
    healed_rows = []
    prev_text_row = None

    for row in rows:
        if not row or not any(row):
            continue

        if not row[0].strip() and len(row) > 1:
            first_content_idx = -1
            for idx, cell in enumerate(row):
                if cell.strip():
                    first_content_idx = idx
                    break

            if first_content_idx > 0:
                val = row[first_content_idx]
                if not is_numeric(val) and not YEAR_RE.match(val):
                    row[0] = val
                    row[first_content_idx] = ""

        has_text = bool(row[0].strip())
        has_data = any(is_numeric(cell) for cell in row[1:])

        if has_text and not has_data:
            if prev_text_row:
                healed_rows.append(prev_text_row)
            prev_text_row = row
            continue

        elif not has_text and has_data:
            if prev_text_row:
                row[0] = prev_text_row[0]
                prev_text_row = None
            healed_rows.append(row)
            continue

        else:
            if prev_text_row:
                healed_rows.append(prev_text_row)
                prev_text_row = None
            healed_rows.append(row)

    if prev_text_row:
        healed_rows.append(prev_text_row)

    return healed_rows


def repair_split_numbers(rows: list[list[str]]) -> list[list[str]]:
    """Stitch numbers split across columns (e.g., '33' + ',252' -> '33,252')."""
    repaired_rows = []
    for row in rows:
        new_row = list(row)

        i = 0
        while i < len(new_row) - 1:
            curr = new_row[i].strip()
            next_val = new_row[i + 1].strip()

            if (
                curr
                and next_val
                and curr[-1].isdigit()
                and next_val.startswith(",")
                and len(next_val) > 1
                and next_val[1].isdigit()
            ) or (curr and next_val and curr.endswith(",") and next_val[0].isdigit()):
                new_row[i] = curr + next_val
                new_row[i + 1] = ""
                i += 1

            i += 1

        repaired_rows.append(new_row)
    return repaired_rows


def repair_shifted_currency(rows: list[list[str]]) -> list[list[str]]:
    """Fix currency symbol wrongly concatenated to current column."""
    cleaned_rows = []

    symbols = [s for s in (PREFIX_SYMBOLS | SUFFIX_SYMBOLS) if s]
    if symbols:
        symbol_pattern = build_alternation(
            symbols, auto_escape=True, sort_longest_first=True
        )
        pattern = re.compile(rf"^(.*?)\s+({symbol_pattern})$")
    else:
        pattern = re.compile(r"^(.*?)\s+(\$)$")

    for row in rows:
        for i in range(len(row) - 1):
            current_cell = row[i].strip()
            match = pattern.search(current_cell)

            if match:
                real_value = match.group(1)
                symbol = match.group(2)
                row[i] = real_value
                next_cell = row[i + 1].strip()
                row[i + 1] = f"{symbol}{next_cell}"

        row = [x.replace("$$", "$").strip() for x in row]
        cleaned_rows.append(row)

    return cleaned_rows


__all__ = [
    "clean_and_merge_symbols",
    "detect_merge_patterns",
    "heal_data_rows",
    "merge_sparse_columns",
    "repair_shifted_currency",
    "repair_split_numbers",
]
