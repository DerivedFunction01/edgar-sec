"""Table extraction, marker repair, column merging, row healing, and type detection."""

from __future__ import annotations

import re
from typing import Any

from .currencies import MAJOR_CURRENCIES, PREFIX_SYMBOLS, SUFFIX_SYMBOLS
from .patterns import (
    C_MARKER_RE,
    CAPTION_RE,
    HTML_TAG_RE,
    LAST_HEADER_PATTERN,
    S_MARKER_RE,
    TABLE_TAG_RE,
    WHITESPACE_RE,
    YEAR_RE,
)
from .repair import (
    clean_and_merge_symbols,
    heal_data_rows,
    merge_sparse_columns,
    repair_shifted_currency,
    repair_split_numbers,
)
from .table_definitions import GenericTable
from .types import (
    detect_paragraph_masquerading_as_table,
    detect_primitive_type,
    detect_table_currency,
    extract_row_years,
    extract_years_from_headers,
    is_percentage_header,
    normalize_percentage_columns,
    scan_for_multiplier,
)


class SimpleTableProcessor:
    """Process tables: repair invalid ones, merge sparse columns, heal data rows."""

    def __init__(self, table_text: str) -> None:
        self.raw_text = table_text
        self.caption = self._extract_caption(table_text)
        self.table_currency = detect_table_currency(self.caption)
        self.global_multiplier = scan_for_multiplier(self.caption) or 1.0
        self.col_multipliers: dict[int, float] = {}

        # Extract data
        self.data, self.col_map, self.col_headers = self._extract_data_driven(
            CAPTION_RE.sub("", table_text)
        )

        self.invalid_table = len(self.data) == 0
        if self.invalid_table:
            self._repair_invalid_table()

        if detect_paragraph_masquerading_as_table(self.data):
            self.invalid_table = True

    def _extract_caption(self, text: str) -> str:
        """Extract caption from <caption> tags."""
        match = CAPTION_RE.search(text)
        if match:
            caption_text = match.group(1).strip()
            caption_text = re.sub(
                r"</?caption[^>]*>", "", caption_text, flags=re.IGNORECASE
            )
            caption_text = WHITESPACE_RE.sub(" ", caption_text).strip()
            return caption_text
        return ""

    def _repair_invalid_table(self) -> None:
        """Repair table by relocating <S> marker to actual header row."""
        table_text = CAPTION_RE.sub("", self.raw_text)
        table_text = TABLE_TAG_RE.sub("", table_text)
        table_text = table_text.expandtabs(8)
        lines = table_text.split("\n")

        # Find current marker
        old_marker_idx = None
        old_marker_line = None
        for i, line in enumerate(lines):
            if S_MARKER_RE.search(line):
                old_marker_idx = i
                old_marker_line = line
                break

        if old_marker_idx is None:
            return

        # Score lines before marker
        best_header_idx = old_marker_idx
        best_score = 0

        for i in range(old_marker_idx):
            line = lines[i].strip()
            if not line or line.startswith("<"):
                continue

            matches = LAST_HEADER_PATTERN.findall(line)
            score = len(matches)

            if score > best_score:
                best_score = score
                best_header_idx = i

        # Relocate marker if better location found
        if best_header_idx != old_marker_idx and best_score > 0:
            lines[old_marker_idx] = (
                lines[old_marker_idx].replace("<S>", "").replace("<C>", "").strip()
            )
            if not lines[old_marker_idx]:
                lines[old_marker_idx] = ""

            assert old_marker_line is not None
            lines[best_header_idx] = old_marker_line
            corrected_table = "\n".join(lines)

            # Re-extract with corrected table
            corrected_data, corrected_col_map, corrected_col_headers = (
                self._extract_data_driven(CAPTION_RE.sub("", corrected_table))
            )

            if corrected_data:
                self.data = corrected_data
                self.col_map = corrected_col_map
                self.col_headers = corrected_col_headers
                self.invalid_table = False

    def _extract_data_driven(
        self, table_text: str
    ) -> tuple[list[list[str]], dict[int, str | None], dict[int, str]]:
        """Extract table data by detecting column boundaries via <S> and <C> markers."""
        table_text = TABLE_TAG_RE.sub("", table_text)
        table_text = table_text.expandtabs(8)
        lines = table_text.split("\n")

        # Find marker line
        marker_line = None
        marker_line_idx = 0
        for i, line in enumerate(lines):
            if S_MARKER_RE.search(line):
                marker_line = line
                marker_line_idx = i
                break

        if not marker_line:
            return [], {}, {}

        # Parse column boundaries from <C> positions
        c_positions = [m.start() for m in C_MARKER_RE.finditer(marker_line)]
        if not c_positions:
            return [], {}, {}

        # Group nearby <C> positions
        grouped_positions = []
        current_group = [c_positions[0]]
        for pos in c_positions[1:]:
            if pos - current_group[-1] <= 5:
                current_group.append(pos)
            else:
                grouped_positions.append(current_group)
                current_group = [pos]
        grouped_positions.append(current_group)

        # Build column boundaries
        column_boundaries: list[tuple[int, int | None]] = []
        single_width_col_indices = set()
        first_c_pos = grouped_positions[0][0]
        column_boundaries.append((0, first_c_pos))

        for i, group in enumerate(grouped_positions):
            start = group[0]
            end = (
                grouped_positions[i + 1][0] if i + 1 < len(grouped_positions) else None
            )
            width = (end - start) if end is not None else 80
            col_idx = len(column_boundaries)
            if width < 2:
                single_width_col_indices.add(col_idx)
            column_boundaries.append((start, end))

        # Extract data rows
        data_lines = lines[marker_line_idx + 1 :]
        raw_rows = []
        for line in data_lines:
            if not line.strip():
                continue
            row_cells = []
            for start, end in column_boundaries:
                if start < len(line):
                    cell = (
                        line[start : min(end, len(line))].strip()
                        if end is not None
                        else line[start:].strip()
                    )
                else:
                    cell = ""
                cell = HTML_TAG_RE.sub("", cell)
                row_cells.append(cell)
            if any(row_cells):
                raw_rows.append(row_cells)

        # Extract header rows
        header_lines = lines[:marker_line_idx]
        raw_header_rows = []
        for line in header_lines:
            clean_line = line.strip()
            if not clean_line or "<CAPTION>" in clean_line or "<TABLE>" in clean_line:
                continue
            if all(c in "-= " for c in clean_line) and any(
                c in "-=" for c in clean_line
            ):
                continue

            h_cells = []
            for start, end in column_boundaries:
                if start < len(line):
                    cell = (
                        line[start : min(end, len(line))].strip()
                        if end is not None
                        else line[start:].strip()
                    )
                else:
                    cell = ""
                h_cells.append(cell)

            if any(h_cells):
                raw_header_rows.append(h_cells)

        # Merge sparse columns
        merged_rows, col_mapping = merge_sparse_columns(
            raw_rows, single_width_col_indices
        )

        # Apply merge to headers
        merged_headers_map: dict[int, list[str]] = {}
        for h_row in raw_header_rows:
            for old_idx, text in enumerate(h_row):
                if not text:
                    continue
                new_idx = col_mapping.get(old_idx, old_idx)
                if new_idx not in merged_headers_map:
                    merged_headers_map[new_idx] = []
                merged_headers_map[new_idx].append(text)

        final_physical_headers = {}
        for idx, parts in merged_headers_map.items():
            final_physical_headers[idx] = " ".join(parts).strip()

        # Clean and repair rows
        cleaned_rows = []
        for row in merged_rows:
            cleaned_row = clean_and_merge_symbols(row)
            cleaned_rows.append(cleaned_row)

        cleaned_rows = heal_data_rows(cleaned_rows)
        cleaned_rows = repair_split_numbers(cleaned_rows)
        cleaned_rows = repair_shifted_currency(cleaned_rows)

        # Filter to active columns
        active_col_indices = set()
        for row in cleaned_rows:
            for col_idx, cell in enumerate(row):
                if cell and len(cell) > 1:
                    active_col_indices.add(col_idx)
        sorted_active_indices = sorted(active_col_indices)

        filtered_rows = []
        for row in cleaned_rows:
            filtered_row = [
                row[i] if i < len(row) else "" for i in sorted_active_indices
            ]
            if any(filtered_row):
                filtered_rows.append(filtered_row)

        # Build column headers with primitive type detection
        col_headers = {}
        col_map: dict[int, str | None] = {}

        for local_idx, global_col_idx in enumerate(sorted_active_indices):
            header_text = final_physical_headers.get(global_col_idx, "")
            col_headers[local_idx] = header_text

            sample_cells = [
                row[local_idx]
                for row in filtered_rows
                if local_idx < len(row) and row[local_idx]
            ]
            col_type = detect_primitive_type(sample_cells)

            # Refine "value" type using header hints
            if col_type == "value" and header_text:
                header_lower = header_text.lower()
                if any(s in header_text for s in PREFIX_SYMBOLS | SUFFIX_SYMBOLS):
                    col_type = "dollar"
                else:
                    for code, props in MAJOR_CURRENCIES.items():
                        if code.lower() in header_lower or any(
                            n in header_lower for n in props.get("names", [])
                        ):
                            col_type = "dollar"
                            break

            if is_percentage_header(header_text) and col_type in {
                "value",
                "mixed",
                None,
            }:
                col_type = "percentage"

            col_map[local_idx] = col_type

        filtered_rows = normalize_percentage_columns(
            filtered_rows, col_map, col_headers
        )

        return filtered_rows, col_map, col_headers

    def get_data(self) -> list[list[str]]:
        """Return extracted table data."""
        return self.data if not self.invalid_table else []

    def get_headers(self) -> dict[int, str]:
        """Return column headers."""
        return self.col_headers if not self.invalid_table else {}

    def get_types(self) -> dict[int, str | None]:
        """Return column types."""
        return self.col_map if not self.invalid_table else {}

    def get_years(self) -> dict[int, int]:
        """Return column years detected from headers, with forward filling."""
        if self.invalid_table:
            return {}
        return extract_years_from_headers(self.col_headers)

    def get_row_years(self) -> dict[int, int]:
        """Return row years detected from section headers (transposed tables)."""
        if self.invalid_table:
            return {}
        return extract_row_years(self.data)

    def get_info(self) -> dict[str, Any]:
        """Return table metadata."""
        caption_year = None
        if self.caption:
            matches = YEAR_RE.findall(self.caption)
            years = []
            for m in matches:
                if isinstance(m, tuple):
                    for g in m:
                        if g:
                            years.append(int(g))
                else:
                    years.append(int(m))

            valid_years = sorted({y for y in years if 1900 <= y <= 2100})
            if len(valid_years) == 1:
                caption_year = valid_years[0]

        return {
            "caption": self.caption,
            "caption_year": caption_year,
            "currency": self.table_currency,
            "global_multiplier": self.global_multiplier,
            "invalid": self.invalid_table,
            "num_rows": len(self.data),
            "num_cols": len(self.col_headers),
            "column_types": self.col_map if not self.invalid_table else {},
        }

    def to_string(self) -> str:
        """Reconstruct the table string with SEC tags (<S>, <C>)."""
        if self.invalid_table or not self.data:
            return ""

        if not self.col_headers:
            num_cols = len(self.data[0]) if self.data else 0
            headers = [""] * num_cols
        else:
            num_cols = len(self.col_headers)
            headers = [self.col_headers.get(i, "") for i in range(num_cols)]

        data_rows = self.data

        if data_rows:
            max_data_cols = max(len(r) for r in data_rows)
            if max_data_cols > num_cols:
                headers.extend([""] * (max_data_cols - num_cols))
                num_cols = max_data_cols

        widths = [0] * num_cols
        for i, h in enumerate(headers):
            widths[i] = max(widths[i], len(h))

        for row in data_rows:
            for i, cell in enumerate(row):
                if i < num_cols:
                    widths[i] = max(widths[i], len(cell))

        widths = [max(w, 1) for w in widths]

        alignments = []
        for i in range(num_cols):
            ctype = self.col_map.get(i, "text")
            alignments.append("l" if ctype == "text" else "r")

        return GenericTable(
            headers=headers,
            data_rows=data_rows,
            widths=widths,
            alignments=alignments,
            title=self.caption or "",
        ).build()


def process_table(table_text: str) -> dict[str, Any]:
    """Standalone function to process a table."""
    processor = SimpleTableProcessor(table_text)

    return {
        "data": processor.get_data(),
        "headers": processor.get_headers(),
        "types": processor.get_types(),
        "years": processor.get_years(),
        "row_years": processor.get_row_years(),
        "info": processor.get_info(),
        "fixed_table": processor.to_string(),
    }


__all__ = [
    "SimpleTableProcessor",
    "process_table",
]
