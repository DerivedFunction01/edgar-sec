"""Shared ownership table alignment primitives for Table I and Table II rows."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
import re
from typing import Any

from edgar_sec.domain.forms.families.ownership.taxonomy import VALID_TRANSACTION_CODES
from edgar_sec.engine.forms.common.alignment import (
    CanonicalColumn,
    TableSchema,
)
from edgar_sec.engine.forms.common.numbers import (
    extract_schema_number,
    extract_schema_number_or_token,
)
from edgar_sec.engine.forms.common.row_extraction import scan_numeric_cells
from edgar_sec.engine.forms.common.statutory import (
    HEADER_LEAK_RE,
    STATUTORY_PAGE_ARTIFACT_RE,
)
from edgar_sec.engine.forms.common.tables import is_instruction_row
from edgar_sec.engine.forms.ownership.patterns import (
    EXACT_HEADER_CELLS,
    HEADER_LABELS,
    HEADER_SUB_KEYWORDS,
    INSTRUCTION_TOKEN_SETS,
    SUBHEADER_CELLS,
    TABLE_TERMINATORS,
)
from edgar_sec.engine.forms.ownership.sections import ClassifiedSection
from edgar_sec.engine.tables.numeric_cells import is_numeric_cell
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import NUMERIC_DATE_RE

_TRANSACTION_CODE_ALT = build_alternation(
    sorted(VALID_TRANSACTION_CODES), auto_escape=True
)
TRANSACTION_CODE_RE = re.compile(rf"\b({_TRANSACTION_CODE_ALT})\b(?:\s*\|\s*([Vv]))?")
_FOOTNOTE_REF_RE = re.compile(r"[\(\[](\d{1,3})[\)\]]")
ACQUIRED_DISPOSED_RE = re.compile(r"\b([AD])\b", re.IGNORECASE)
_DIRECT_INDIRECT_RE = re.compile(r"\b([DI])\b", re.IGNORECASE)
_INSTRUCTION_TOKEN_RE = re.compile(r"[a-z0-9\(\)]+")
_OWNERSHIP_FORM_VALUES = frozenset(("D", "I"))


def _is_table_header_row(row: tuple[str, ...], table_label: str) -> bool:
    for c in row:
        if c and NUMERIC_DATE_RE.search(c):
            return False
    lower_cells = [c.lower().strip() for c in row if c.strip()]
    if not lower_cells:
        return True
    row_str = " ".join(lower_cells)
    if table_label in row_str or any(k in row_str for k in HEADER_LABELS):
        return True
    header_keywords = sum(
        1
        for c in lower_cells
        if any(k in c for k in HEADER_SUB_KEYWORDS) or c in EXACT_HEADER_CELLS
    )
    hits = sum(
        1
        for c in lower_cells
        if c in SUBHEADER_CELLS
        or any(k in c for k in ("instr.", "month/day", "end of month"))
    )
    return header_keywords >= 1 and hits >= 2


def clean_title(text: str) -> str:
    cleaned = _FOOTNOTE_REF_RE.sub("", text).strip()
    if " - " in cleaned:
        parts = cleaned.rsplit(" - ", 1)
        if len(parts) == 2 and is_numeric_cell(parts[1]):
            cleaned = parts[0]
    return " ".join(cleaned.split())


def extract_ownership_number(text: str) -> str | None:
    """Extract a schema number, ignoring a footnote reference beside the value."""
    stripped = _FOOTNOTE_REF_RE.sub("", text).strip()
    if not stripped:
        return None
    if stripped.startswith(".") and stripped[1:2].isdigit():
        stripped = f"0{stripped}"
    return extract_schema_number_or_token(stripped)


def is_nonnegative_number(text: str) -> bool:
    """Report whether a cell can hold a nonnegative ownership amount."""
    value = extract_ownership_number(text)
    return value is None or not value.startswith("-")


def is_footnote_marker(cell: str, footnote_ids: frozenset[str] = frozenset()) -> bool:
    """Report whether a cell holds only a footnote reference.

    A reference listed among the row footnotes is certain; the low single-digit
    range is treated as an obvious marker because filers write it that way.
    """
    match = _FOOTNOTE_REF_RE.fullmatch(cell.strip())
    if not match:
        return False
    identifier = match.group(1)
    if identifier in footnote_ids:
        return True
    return identifier.isdigit() and 1 <= int(identifier) <= 99


def strip_footnote_refs(text: str) -> str:
    """Remove the footnote references a filer writes beside a value."""
    stripped = _FOOTNOTE_REF_RE.sub("", text).strip()
    return stripped or text.strip()


def split_ownership_row_cells(
    row: Sequence[str], footnote_ids: frozenset[str] = frozenset()
) -> tuple[str, ...]:
    """Split a row into cells, dropping cells that hold only a footnote marker.

    A footnote reference beside a value is metadata, so it is stripped from the
    cell that carries the value; the reference itself stays on the row.
    """
    parts: list[str] = []
    for cell in row:
        for part in cell.split("|"):
            text = part.strip()
            if not text or is_footnote_marker(text, footnote_ids):
                continue
            parts.append(strip_footnote_refs(text))
    return tuple(parts)


def is_valid_row_security_title(title: str) -> bool:
    if not title or is_numeric_cell(title) or _FOOTNOTE_REF_RE.fullmatch(title):
        return False
    lower = title.lower()
    if (
        "instr." in lower
        or "title of" in lower
        or "transaction" in lower
        or "beneficially owned" in lower
        or "disposed of" in lower
        or bool(HEADER_LEAK_RE.search(title))
    ):
        return False
    stripped = title.strip("*() AD-")
    if not stripped or stripped in ("0", "1-for"):
        return False
    if NUMERIC_DATE_RE.search(stripped) and "option" not in lower:
        return False
    return True


def is_nature_like(cell: str) -> bool:
    """Report whether a cell reads as a nature-of-ownership description."""
    text = cell.strip()
    if not text:
        return False
    if is_numeric_cell(text) or "$" in text or "/sh" in text.lower():
        return False
    if NUMERIC_DATE_RE.search(text):
        return False
    if TRANSACTION_CODE_RE.search(text):
        return False
    if ACQUIRED_DISPOSED_RE.fullmatch(text.strip("() ")):
        return False
    return text.strip("() ").upper() not in _OWNERSHIP_FORM_VALUES


def trailing_ownership_form(cells: Sequence[str]) -> tuple[int, str | None]:
    """Locate the ownership form that closes an ownership table row."""
    for index in range(len(cells) - 1, -1, -1):
        value = cells[index].strip("() ").upper()
        if value not in _OWNERSHIP_FORM_VALUES:
            continue
        if all(is_nature_like(cell) for cell in cells[index + 1 :]):
            return index, value
    return -1, None


def extract_ownership_form(
    indexed_cells: list[tuple[int, str]],
) -> tuple[str | None, str | None, int]:
    for idx in range(len(indexed_cells) - 1, -1, -1):
        clean = indexed_cells[idx][1].strip("() ").upper()
        if clean in _OWNERSHIP_FORM_VALUES:
            if not all(is_nature_like(cell) for _, cell in indexed_cells[idx + 1 :]):
                continue
            nature = indexed_cells[idx + 1][1] if idx + 1 < len(indexed_cells) else None
            return clean, nature, idx
    return None, None, -1


def find_trans_code(
    cells: list[tuple[int, str]], end_idx: int, exclude_idx: int
) -> tuple[str | None, bool, int]:
    for idx, (_, cell) in enumerate(cells[1:], start=1):
        if end_idx != -1 and idx >= end_idx:
            break
        if idx != exclude_idx and (m := TRANSACTION_CODE_RE.search(cell)):
            return m.group(1).upper(), bool(m.group(2)), idx
    return None, False, -1


def find_ad_code(
    cells: list[tuple[int, str]], end_idx: int, exclude_indices: set[int]
) -> str | None:
    for idx, (_, cell) in enumerate(cells[1:], start=1):
        if end_idx != -1 and idx >= end_idx:
            break
        if idx not in exclude_indices and (
            m := ACQUIRED_DISPOSED_RE.fullmatch(cell.strip("() "))
        ):
            return m.group(1).upper()
    return None


def find_remaining_numbers(
    cells: list[tuple[int, str]], end_idx: int, exclude_indices: set[int]
) -> list[str]:
    nums: list[str] = []
    for idx, cell in scan_numeric_cells(
        [cell for _, cell in cells[1:]],
        excluded=frozenset(
            index - 1
            for index in exclude_indices
            if index >= 1 and (end_idx == -1 or index < end_idx)
        ),
        deny=("|", "/sh"),
    ):
        if end_idx != -1 and idx >= end_idx - 1:
            break
        if (val := extract_ownership_number(cell)) is not None:
            nums.append(val)
    return nums


def _is_statutory_or_instruction(row_str: str) -> bool:
    low = row_str.lower().strip()
    if not low or low == "*":
        return True
    if is_instruction_row(low) or STATUTORY_PAGE_ARTIFACT_RE.search(low) is not None:
        return True
    if any(k in low for k in ("omb information", "sec 1474", "sec 2474")):
        return True
    tokens = frozenset(_INSTRUCTION_TOKEN_RE.findall(low))
    return any(sig.issubset(tokens) for sig in INSTRUCTION_TOKEN_SETS)


@dataclass(frozen=True, slots=True)
class NonDerivativeTransaction:
    security_title: str
    transaction_date: str | None = None
    transaction_code: str | None = None
    equity_swap_involved: bool = False
    shares_amount: str | None = None
    acquired_disposed_code: str | None = None
    price_per_share: str | None = None
    shares_owned_following: str | None = None
    direct_or_indirect: str | None = None
    nature_of_ownership: str | None = None
    footnote_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DerivativeTransaction:
    security_title: str
    conversion_or_exercise_price: str | None = None
    transaction_date: str | None = None
    transaction_code: str | None = None
    equity_swap_involved: bool = False
    shares_amount: str | None = None
    acquired_disposed_code: str | None = None
    exercisable_date: str | None = None
    expiration_date: str | None = None
    underlying_security_title: str | None = None
    underlying_shares_amount: str | None = None
    price_of_derivative: str | None = None
    derivative_shares_owned_following: str | None = None
    direct_or_indirect: str | None = None
    nature_of_ownership: str | None = None
    footnote_ids: tuple[str, ...] = ()


def extract_footnote_ids(text: str) -> tuple[str, ...]:
    return tuple(_FOOTNOTE_REF_RE.findall(text))


def _extract_date(s: str) -> str | None:
    return m.group(0) if (m := NUMERIC_DATE_RE.search(s)) else None


def _extract_code(s: str) -> str | None:
    return m.group(1).upper() if (m := TRANSACTION_CODE_RE.search(s)) else None


def _extract_ad(s: str) -> str | None:
    return (
        m.group(1).upper()
        if (m := ACQUIRED_DISPOSED_RE.fullmatch(s.strip("() ")))
        else None
    )


def _extract_di(s: str) -> str | None:
    clean = s.strip("() ").upper()
    return clean if clean in _OWNERSHIP_FORM_VALUES else None


def _col(
    index: int,
    name: str,
    is_required: bool = False,
    is_anchor: bool = False,
    anchor_validator: Callable[[str], bool] | None = None,
    data_extractor: Callable[[str], Any] | None = None,
    value_validator: Callable[[str], bool] | None = None,
) -> CanonicalColumn:
    return CanonicalColumn(
        index=index,
        name=name,
        is_required=is_required,
        is_anchor=is_anchor,
        anchor_validator=anchor_validator,
        data_extractor=data_extractor,
        value_validator=value_validator,
    )


def _is_date(s: str) -> bool:
    return bool(NUMERIC_DATE_RE.search(s))


def _is_code(s: str) -> bool:
    return bool(TRANSACTION_CODE_RE.search(s))


def _is_ad(s: str) -> bool:
    return bool(ACQUIRED_DISPOSED_RE.fullmatch(s.strip("() ")))


def _is_price(s: str) -> bool:
    return "$" in s or "/sh" in s.lower()


def _is_di(s: str) -> bool:
    return s.strip("() ").upper() in _OWNERSHIP_FORM_VALUES


def _is_underlying(s: str) -> bool:
    return any(
        k in s.lower()
        for k in (
            "common",
            "preferred",
            "class a",
            "class b",
            "ordinary",
            "stock",
            "shares",
        )
    )


_COMPOSITE_UNDERLYING_RE = re.compile(
    r"^(?P<title>[^-]+?)\s+-\s+(?P<amount>[\d,]+(?:\.\d+)?)$"
)


def split_composite_underlying_cell(cells: Sequence[str]) -> tuple[str, ...]:
    """Split a ``TITLE - AMOUNT`` cell so the amount reaches the amount column.

    A filer writes the underlying security and its share count in one cell; read
    as a title alone, the amount is lost.
    """
    out: list[str] = []
    for index, cell in enumerate(cells):
        match = _COMPOSITE_UNDERLYING_RE.match(cell) if index else None
        if match is not None and _is_underlying(match.group("title")):
            out.append(match.group("title"))
            out.append(match.group("amount"))
            continue
        out.append(cell)
    return tuple(out)


def _is_present(s: str) -> bool:
    return bool(s.strip())


TABLE_I_SCHEMA = TableSchema(
    name="ownership_table_i",
    columns=(
        _col(
            0,
            "security_title",
            is_required=True,
            is_anchor=True,
            anchor_validator=_is_present,
        ),
        _col(1, "transaction_date", False, True, _is_date, _extract_date),
        _col(2, "deemed_execution_date"),
        _col(3, "transaction_code", False, True, _is_code, _extract_code),
        _col(
            4,
            "equity_swap",
            False,
            True,
            lambda s: s.strip().upper() == "V",
            lambda s: True,
        ),
        _col(
            5,
            "shares_amount",
            False,
            False,
            None,
            extract_ownership_number,
            is_nonnegative_number,
        ),
        _col(6, "acquired_disposed_code", False, True, _is_ad, _extract_ad),
        _col(
            7,
            "price_per_share",
            False,
            True,
            _is_price,
            extract_ownership_number,
            is_nonnegative_number,
        ),
        _col(
            8,
            "shares_owned_following",
            False,
            False,
            None,
            extract_ownership_number,
            is_nonnegative_number,
        ),
        _col(9, "direct_or_indirect", True, True, _is_di, _extract_di),
        _col(10, "nature_of_ownership"),
    ),
)

_COMMON_TABLE_II_TAIL = (
    _col(0, "exercisable_date", False, True, _is_date, _extract_date),
    _col(1, "expiration_date", False, True, _is_date, _extract_date),
    _col(2, "underlying_security_title", False, True, _is_underlying, clean_title),
    _col(
        3,
        "underlying_shares_amount",
        False,
        False,
        None,
        extract_ownership_number,
        is_nonnegative_number,
    ),
    _col(
        4,
        "price_of_derivative",
        False,
        True,
        _is_price,
        extract_ownership_number,
        is_nonnegative_number,
    ),
    _col(
        5,
        "derivative_shares_owned_following",
        False,
        False,
        None,
        extract_ownership_number,
        is_nonnegative_number,
    ),
    _col(6, "direct_or_indirect", True, True, _is_di, _extract_di),
    _col(7, "nature_of_ownership"),
)

_TX_TABLE_II_PREFIX = (
    _col(
        0,
        "security_title",
        is_required=True,
        is_anchor=True,
        anchor_validator=_is_present,
    ),
    _col(
        1,
        "conversion_or_exercise_price",
        False,
        False,
        None,
        extract_ownership_number,
        is_nonnegative_number,
    ),
    _col(2, "transaction_date", False, True, _is_date, _extract_date),
    _col(3, "deemed_execution_date"),
    _col(4, "transaction_code", False, True, _is_code, _extract_code),
    _col(5, "equity_swap", False, False, lambda s: s.strip().upper() == "V"),
    _col(
        6,
        "shares_amount",
        False,
        False,
        None,
        extract_ownership_number,
        is_nonnegative_number,
    ),
    _col(7, "acquired_disposed_code", False, False, _is_ad, _extract_ad),
)

_HOLDING_TABLE_II_PREFIX = (
    _col(
        0,
        "security_title",
        is_required=True,
        is_anchor=True,
        anchor_validator=_is_present,
    ),
    _col(
        1,
        "conversion_or_exercise_price",
        False,
        False,
        None,
        extract_ownership_number,
        is_nonnegative_number,
    ),
)


def _build_table_ii_schema(
    prefix: tuple[CanonicalColumn, ...], name: str
) -> TableSchema:
    cols = tuple(
        replace(c, index=i) for i, c in enumerate(prefix + _COMMON_TABLE_II_TAIL)
    )
    return TableSchema(name=name, columns=cols)


TABLE_II_TX_SCHEMA = _build_table_ii_schema(
    _TX_TABLE_II_PREFIX, "ownership_table_ii_tx"
)
TABLE_II_HOLDING_SCHEMA = _build_table_ii_schema(
    _HOLDING_TABLE_II_PREFIX, "ownership_table_ii_holding"
)


def iter_clean_table_rows(
    section: ClassifiedSection | None, table_label: str
) -> list[tuple[tuple[str, ...], str, list[str]]]:
    if section is None or len(section.resolved_grid.rows) <= 1:
        return []
    out: list[tuple[tuple[str, ...], str, list[str]]] = []
    for row in section.resolved_grid.rows:
        if not any(c.strip() for c in row):
            continue
        row_str = " ".join(c.strip() for c in row if c.strip())
        if any(term in row_str.lower() for term in TABLE_TERMINATORS):
            break
        if _is_statutory_or_instruction(row_str) or _is_table_header_row(
            row, table_label
        ):
            continue
        out.append((row, row_str, list(extract_footnote_ids(row_str))))
    return out


__all__ = [
    "ACQUIRED_DISPOSED_RE",
    "TABLE_I_SCHEMA",
    "TABLE_II_HOLDING_SCHEMA",
    "TABLE_II_TX_SCHEMA",
    "TRANSACTION_CODE_RE",
    "clean_title",
    "extract_footnote_ids",
    "extract_ownership_form",
    "find_ad_code",
    "find_remaining_numbers",
    "find_trans_code",
    "is_valid_row_security_title",
    "iter_clean_table_rows",
]
