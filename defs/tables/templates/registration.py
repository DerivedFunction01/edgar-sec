"""Section 12(b) registered securities table templates (2-col, 3-col, 4-col)."""

from __future__ import annotations

import re

from defs.regex import build_alternation
from defs.tables.builder import HTMLTableConverter
from defs.tables.tokens import is_numeric_cell

_REG_TITLE_TOKENS = [f"title of {prefix}class".strip() for prefix in ("each ", "")] + [
    "class of securities",
    "security class",
]

_REG_EXCHANGE_TOKENS = [
    f"{prefix}exchange {suffix}".strip()
    for prefix in ("name of each ", "name of ", "")
    for suffix in ("on which registered", "")
]

_REG_SYMBOL_TOKENS = [
    f"{prefix}symbol{suffix}".strip()
    for prefix in ("trading ", "ticker ", "")
    for suffix in ("(s)", "s", "")
]

_REG_REGISTRANT_TOKENS = [
    f"{prefix}name of {reg}".strip()
    for prefix in ("exact ", "")
    for reg in ("registrant", "co-registrant")
] + ["registrant", "co-registrant"]

REG_TITLE_RE = re.compile(build_alternation(_REG_TITLE_TOKENS), re.IGNORECASE)
REG_EXCHANGE_RE = re.compile(build_alternation(_REG_EXCHANGE_TOKENS), re.IGNORECASE)
REG_SYMBOL_RE = re.compile(build_alternation(_REG_SYMBOL_TOKENS), re.IGNORECASE)
REG_REGISTRANT_RE = re.compile(build_alternation(_REG_REGISTRANT_TOKENS), re.IGNORECASE)


def registration_table_template(source_grid: list[list[str]]) -> str | None:
    """Format Section 12(b) registered securities tables into structured ASCII <TABLE> grids."""
    if len(source_grid) < 2:
        return None

    compact = [[cell for cell in row if cell.strip()] for row in source_grid]
    if not compact or not compact[0]:
        return None

    header = " ".join(compact[0]).lower()
    has_title = bool(REG_TITLE_RE.search(header))
    has_exchange = bool(REG_EXCHANGE_RE.search(header))
    has_symbol = bool(REG_SYMBOL_RE.search(header))
    has_registrant = bool(REG_REGISTRANT_RE.search(header))

    # Match 2-col (Title + Exchange), 3-col (+ Symbol), or 4-col (+ Registrant)
    is_12b = (
        (has_title and has_exchange)
        or (has_symbol and (has_title or has_exchange))
        or (has_registrant and has_title)
    )
    if not is_12b:
        return None

    header_cols = len(compact[0])
    if header_cols not in (2, 3, 4):
        return None

    for row in compact[1:]:
        if len(row) != header_cols:
            return None
        if any(is_numeric_cell(cell) for cell in row):
            return None

    return (
        HTMLTableConverter(grid=compact, header_row_count=1).to_generic_table().build()
    )


__all__ = ["registration_table_template"]
