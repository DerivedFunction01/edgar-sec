"""Rollforward grid features: the priced grid derivation shared by the
restructuring and inventory separators — span, bookend, movement,
balance, percentage and component reads over the table grid."""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.numeric_cells import DIGIT_RE, GROUPED_INTEGER_FRAGMENT
from edgar_sec.foundation.text.dates import STRICT_YEAR_TOKEN_PATTERN

_YEAR_RE = re.compile(rf"\b(?:{STRICT_YEAR_TOKEN_PATTERN})\b")
_NON_ALPHA_RE = re.compile(r"[^a-z# ]")
_RATE_RE = re.compile(r"\brate\b")
# _NUM_RE recomposed from the homed digit/comma fragment; the %? tail
# is dead on the call path (_cell_value rstrips "%" first), so the
# verdicts match _NUM_RE exactly, leading-minus rejection included.
_ROLLFORWARD_NUM_RE = re.compile(rf"^\(?\$?{GROUPED_INTEGER_FRAGMENT}(?:\.\d+)?\)?$")
# Word lists ported verbatim from the priced g1 instrument.
_ANCHOR_WORDS = (
    "balance",
    "accrual",
    "accrued",
    "liability",
    "liabilities",
    "reserve",
    "obligation",
    "obligations",
)
_MOVE_WORDS = (
    "beginning",
    "ending",
    "granted",
    "exercised",
    "forfeited",
    "expired",
    "outstanding",
    "provision",
    "charge",
    "payment",
    "paid",
    "adjustment",
    "addition",
    "settlement",
    "incurred",
    "accrued",
    "deduction",
    "vested",
)
_INVENTORY_COMPONENTS = (
    "raw material",
    "work in process",
    "work-in-process",
    "in process",
    "finished good",
    "finished product",
    "fuel",
    "merchandise",
    "parts",
    "supplies",
    "product",
    "materials",
)


@dataclass(frozen=True)
class RollforwardGridText:
    """One table's grid text (plus caption) for the grid derivation."""

    table_text: str
    caption: str = ""

    @classmethod
    def from_rows(cls, rows) -> "RollforwardGridText":
        """Build from production geometry rows."""
        return cls("\n".join(" | ".join(row) for row in rows))

    @classmethod
    def from_packet(cls, packet: dict) -> "RollforwardGridText":
        """Build from a census packet record."""
        caption = " ".join(packet.get("caption_stack") or [])
        return cls(str(packet.get("table_text") or ""), caption)


@dataclass(frozen=True)
class RollforwardGridFeatures:
    """The priced grid derivation's reads over one table."""

    rows: int
    span: int
    header_span: int
    bare_year_stubs: int
    name_year_stubs: int
    bookend_f2: bool
    rate_header: bool
    balances_unchanged: bool
    movement_nonzero: int
    prose_cells: int
    pct_density: float
    inventory_components: int
    inventory_core: bool
    total_line: bool
    shares_stub: bool


def _norm_phrase(text: str) -> str:
    text = DIGIT_RE.sub("#", text.lower())
    text = _NON_ALPHA_RE.sub(" ", text)
    return " ".join(text.split())


def _cell_value(cell: str) -> float | None:
    token = cell.strip()
    if not token or token in {"—", "-", "*", "–"}:
        return None
    core = token.rstrip("%").strip()
    if not _ROLLFORWARD_NUM_RE.match(core):
        return None
    negative = core.startswith("(") and core.endswith(")")
    token = core.strip("()$").replace(",", "")
    try:
        value = float(token)
    except ValueError:
        return None
    return -value if negative else value


def grid_features(text: RollforwardGridText) -> RollforwardGridFeatures:
    """Derive the grid features over one table's text."""
    lines = []
    for line in text.table_text.split("\n"):
        cells = [cell.strip() for cell in line.split("|")]
        if any(cells):
            lines.append(cells)
    years: set[str] = set()
    numeric = pct_cells = prose_cells = 0
    movement_nonzero = 0
    balance_vectors: list[list[float]] = []
    stub_phrases: list[str] = []
    bare_year_stubs = 0
    name_year_stubs = 0
    total_line = False
    shares_stub = False
    first_numeric_idx = None
    anchor_lines: list[tuple[int, set[str]]] = []
    anchor_begin = anchor_end = False
    for idx, cells in enumerate(lines):
        joined = " ".join(cells).lower()
        line_years = set(_YEAR_RE.findall(joined))
        years |= line_years
        first = next((cell for cell in cells if cell), "")
        stub_phrases.append(_norm_phrase(first))
        if _YEAR_RE.fullmatch(first.strip()):
            bare_year_stubs += 1
        if _YEAR_RE.search(first) and any(ch.isalpha() for ch in first):
            name_year_stubs += 1
        if "shares" in first.lower():
            shares_stub = True
        if "total" in first.lower():
            total_line = True
        is_move = any(word in joined for word in _MOVE_WORDS)
        if any(word in joined for word in _ANCHOR_WORDS):
            keys = set(line_years)
            for month in (
                "january",
                "february",
                "march",
                "april",
                "may",
                "june",
                "july",
                "august",
                "september",
                "october",
                "november",
                "december",
                "beginning",
                " end",
            ):
                if month in joined:
                    keys.add(month)
            anchor_lines.append((idx, keys))
            if "beginning" in joined:
                anchor_begin = True
            if "ending" in joined or "end of" in joined:
                anchor_end = True
        line_values: list[float] = []
        for pos, cell in enumerate(cells):
            value = _cell_value(cell)
            if value is not None:
                numeric += 1
                if first_numeric_idx is None:
                    first_numeric_idx = idx
                if "%" in cell or (
                    pos + 1 < len(cells) and cells[pos + 1].strip() == "%"
                ):
                    pct_cells += 1
                line_values.append(value)
                if is_move and value != 0:
                    movement_nonzero += 1
            if len(cell.split()) >= 6:
                prose_cells += 1
        if "balance" in joined:
            balance_vectors.append(line_values)
    header_zone = " ".join(
        " ".join(cells) for cells in lines[: min(first_numeric_idx or 0, 8)]
    ).lower()
    header_years = set(_YEAR_RE.findall(header_zone))
    all_keys: set[str] = set()
    for _, keys in anchor_lines:
        all_keys |= keys
    anchor_pair = len(anchor_lines) >= 2 and len(all_keys) >= 2
    first_line = " ".join(lines[0]).lower() if lines else ""
    horizontal = bool(
        lines
        and any(word in first_line for word in _ANCHOR_WORDS)
        and _YEAR_RE.search(first_line)
        and (
            "beginning" in first_line
            or " end" in first_line
            # Year occurrences, not distinct years — verbatim the
            # priced g1 instrument (a repeated year bookends).
            or len(_YEAR_RE.findall(first_line)) >= 2
        )
    )
    bookend_f2 = bool((anchor_begin and anchor_end) or anchor_pair or horizontal)
    balances_unchanged = bool(
        len(balance_vectors) >= 2
        and balance_vectors[0] == balance_vectors[-1]
        and any(balance_vectors)
    )
    inventory_components = sum(
        1
        for phrase in stub_phrases
        if any(term in phrase for term in _INVENTORY_COMPONENTS)
    )
    return RollforwardGridFeatures(
        rows=len(lines),
        span=len(years),
        header_span=len(header_years),
        bare_year_stubs=bare_year_stubs,
        name_year_stubs=name_year_stubs,
        bookend_f2=bookend_f2,
        rate_header=bool(_RATE_RE.search(header_zone)),
        balances_unchanged=balances_unchanged,
        movement_nonzero=movement_nonzero,
        prose_cells=prose_cells,
        pct_density=(pct_cells / numeric) if numeric else 0.0,
        inventory_components=inventory_components,
        inventory_core=bool(inventory_components >= 2 and total_line),
        total_line=total_line,
        shares_stub=shares_stub,
    )
