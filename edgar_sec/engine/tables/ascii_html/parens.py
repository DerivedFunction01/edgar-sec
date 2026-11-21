"""Split-parenthesis reunification for built geometry rows.
Filings print accounting negatives as `(digits` in the value column with the closing paren in a
narrow column of its own, so the geometry canonicalizes the pair back into one balanced cell.
"""

from __future__ import annotations

_BENIGN_SUFFIXES = frozenset({"%", "*", "†", "‡"})
_DIGITS = frozenset("0123456789")


def _is_value_open(text: str) -> bool:
    """Return True for a stripped cell that opens a digit-bearing value and never closes it."""
    return text.startswith("(") and ")" not in text and not _DIGITS.isdisjoint(text)


def merge_split_paren_cells(rows: list[list[str]]) -> list[list[str]]:
    """Reunite split closing parens with their value-open cells, row by row.
    A close is the next cell, or the cell after one empty cell: a bare `)` is consumed,
    and a `)` plus one benign suffix leaves the suffix standing as its own cell.
    """
    merged_rows: list[list[str]] = []
    for row in rows:
        cells = list(row)
        for c_idx, raw_text in enumerate(cells):
            text = raw_text.strip()
            if not _is_value_open(text):
                continue
            close_idx = c_idx + 1
            if close_idx < len(cells) and not cells[close_idx].strip():
                close_idx += 1
            if close_idx >= len(cells):
                continue
            close_text = cells[close_idx].strip()
            if close_text == ")":
                cells[c_idx] = f"{text})"
                cells[close_idx] = ""
            elif (
                len(close_text) == 2
                and close_text.startswith(")")
                and close_text[1] in _BENIGN_SUFFIXES
            ):
                cells[c_idx] = f"{text})"
                cells[close_idx] = close_text[1]
        merged_rows.append(cells)
    return merged_rows


__all__ = [
    "merge_split_paren_cells",
]
