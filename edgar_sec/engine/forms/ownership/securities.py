"""Form 4 Table I (Non-Derivative) and Table II (Derivative) row extraction."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import re
from typing import Any

from edgar_sec.domain.forms.families.ownership.models import VALID_TRANSACTION_CODES
from edgar_sec.engine.forms.common.alignment import (
    CanonicalColumn,
    TableSchema,
    align_row_to_schema,
)
from edgar_sec.engine.forms.common.numbers import clean_numeric
from edgar_sec.engine.forms.common.statutory import STATUTORY_PAGE_ARTIFACT_RE
from edgar_sec.engine.forms.common.tables import is_instruction_row
from edgar_sec.engine.forms.ownership.sections import ClassifiedSection
from edgar_sec.engine.tables.numeric_cells import is_numeric_cell
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import NUMERIC_DATE_RE

_TRANSACTION_CODE_ALT = build_alternation(
    sorted(VALID_TRANSACTION_CODES), auto_escape=True
)
_TRANSACTION_CODE_RE = re.compile(rf"\b({_TRANSACTION_CODE_ALT})\b(?:\s*\|\s*([Vv]))?")
_FOOTNOTE_REF_RE = re.compile(r"[\(\[](\d{1,3})[\)\]]")
_FOOTNOTE_ENTRY_RE = re.compile(
    r"^\s*(?:[\(\[]\s*(\d{1,3})\s*[\)\]]|(\d{1,3})\.)\s*(.+)", re.MULTILINE
)
_ACQUIRED_DISPOSED_RE = re.compile(r"\b([AD])\b", re.IGNORECASE)
_DIRECT_INDIRECT_RE = re.compile(r"\b([DI])\b", re.IGNORECASE)

_TABLE_TERMINATORS = (
    "/s/",
    "** signature",
    "signature of reporting person",
    "explanation of responses",
)
_SUBHEADER_CELLS = frozenset(
    {
        "code",
        "v",
        "amount",
        "price",
        "(a) or (d)",
        "(a)",
        "(d)",
        "instr. 3",
        "instr. 4",
        "instr. 5",
        "instr. 8",
        "date",
        "title",
        "exercise",
        "conversion",
        "exercisable",
        "expiration",
        "following",
    }
)
_INSTRUCTION_TOKEN_SETS = tuple(
    frozenset(s.split())
    for s in (
        "filed pursuant section 16",
        "investment company act",
        "check box longer subject",
        "form obligations continue",
        "affirmative defense 10b5-1",
        "written trading plan",
        "reminder report separate line",
        "intentional misstatements criminal",
        "18 u.s.c 1001",
        "15 u.s.c 78ff",
        "omb approval",
        "3235-0287",
        "burden hours",
        "print type responses",
    )
)


_HEADER_LABELS = (
    "title of security",
    "title of derivative",
    "title of class",
    "transaction date",
    "conversion or exercise",
    "date of earliest",
    "deemed execution date",
)
_HEADER_SUB_KEYWORDS = (
    "instr.",
    "month/day",
    "end of month",
    "exercise",
    "conversion",
    "expiration",
    "following",
    "underlying",
)
_EXACT_HEADER_CELLS = ("code", "v", "amount", "price", "(a) or (d)")


def _is_table_header_row(row: tuple[str, ...], table_label: str) -> bool:
    lower_cells = [c.lower().strip() for c in row if c.strip()]
    if not lower_cells:
        return True
    if any(NUMERIC_DATE_RE.search(c) for c in lower_cells):
        return False
    row_str = " ".join(lower_cells)
    if table_label in row_str or any(k in row_str for k in _HEADER_LABELS):
        return True
    header_keywords = sum(
        1
        for c in lower_cells
        if any(k in c for k in _HEADER_SUB_KEYWORDS) or c in _EXACT_HEADER_CELLS
    )
    hits = sum(
        1
        for c in lower_cells
        if c in _SUBHEADER_CELLS
        or any(k in c for k in ("instr.", "month/day", "end of month"))
    )
    return header_keywords >= 1 and hits >= 2


def _clean_title(text: str) -> str:
    cleaned = _FOOTNOTE_REF_RE.sub("", text).strip()
    return " ".join(cleaned.split())


def _is_valid_row_security_title(title: str) -> bool:
    return bool(
        title
        and not is_numeric_cell(title)
        and not NUMERIC_DATE_RE.fullmatch(title)
        and not _FOOTNOTE_REF_RE.fullmatch(title)
    )


def _extract_ownership_form(
    indexed_cells: list[tuple[int, str]],
) -> tuple[str | None, str | None, int]:
    for idx, (_, cell) in reversed(list(enumerate(indexed_cells))):
        m = _DIRECT_INDIRECT_RE.fullmatch(cell.strip("() "))
        if m:
            nature = indexed_cells[idx + 1][1] if idx + 1 < len(indexed_cells) else None
            return m.group(1).upper(), nature, idx
    return None, None, -1


def _find_trans_code(
    cells: list[tuple[int, str]], end_idx: int, exclude_idx: int
) -> tuple[str | None, bool, int]:
    for idx, (_, cell) in enumerate(cells[1:], start=1):
        if end_idx != -1 and idx >= end_idx:
            break
        if idx != exclude_idx and (m := _TRANSACTION_CODE_RE.search(cell)):
            return m.group(1).upper(), bool(m.group(2)), idx
    return None, False, -1


def _find_ad_code(
    cells: list[tuple[int, str]], end_idx: int, exclude_indices: set[int]
) -> str | None:
    for idx, (_, cell) in enumerate(cells[1:], start=1):
        if end_idx != -1 and idx >= end_idx:
            break
        if idx not in exclude_indices and (
            m := _ACQUIRED_DISPOSED_RE.fullmatch(cell.strip("() "))
        ):
            return m.group(1).upper()
    return None


def _find_remaining_numbers(
    cells: list[tuple[int, str]], end_idx: int, exclude_indices: set[int]
) -> list[float]:
    nums: list[float] = []
    for idx, (_, cell) in enumerate(cells[1:], start=1):
        if end_idx != -1 and idx >= end_idx:
            break
        if (
            idx not in exclude_indices
            and "|" not in cell
            and "$" not in cell
            and "/sh" not in cell.lower()
            and is_numeric_cell(cell)
        ):
            if (val := _extract_number(cell)) is not None:
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
    tokens = frozenset(re.findall(r"[a-z0-9\(\)]+", low))
    return any(sig.issubset(tokens) for sig in _INSTRUCTION_TOKEN_SETS)


@dataclass(frozen=True, slots=True)
class NonDerivativeTransaction:
    security_title: str
    transaction_date: str | None = None
    transaction_code: str | None = None
    equity_swap_involved: bool = False
    shares_amount: float | None = None
    acquired_disposed_code: str | None = None
    price_per_share: float | None = None
    shares_owned_following: float | None = None
    direct_or_indirect: str | None = None
    nature_of_ownership: str | None = None
    footnote_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DerivativeTransaction:
    security_title: str
    conversion_or_exercise_price: float | None = None
    transaction_date: str | None = None
    transaction_code: str | None = None
    equity_swap_involved: bool = False
    shares_amount: float | None = None
    acquired_disposed_code: str | None = None
    exercisable_date: str | None = None
    expiration_date: str | None = None
    underlying_security_title: str | None = None
    underlying_shares_amount: float | None = None
    price_of_derivative: float | None = None
    derivative_shares_owned_following: float | None = None
    direct_or_indirect: str | None = None
    nature_of_ownership: str | None = None
    footnote_ids: tuple[str, ...] = ()


def _extract_number(text: str) -> float | None:
    num = clean_numeric(text)
    return float(num) if num is not None else None


def _extract_footnote_ids(text: str) -> tuple[str, ...]:
    return tuple(_FOOTNOTE_REF_RE.findall(text))


def _extract_date(s: str) -> str | None:
    return m.group(0) if (m := NUMERIC_DATE_RE.search(s)) else None


def _extract_code(s: str) -> str | None:
    return m.group(1).upper() if (m := _TRANSACTION_CODE_RE.search(s)) else None


def _extract_ad(s: str) -> str | None:
    return (
        m.group(1).upper()
        if (m := _ACQUIRED_DISPOSED_RE.fullmatch(s.strip("() ")))
        else None
    )


def _extract_di(s: str) -> str | None:
    return (
        m.group(1).upper()
        if (m := _DIRECT_INDIRECT_RE.fullmatch(s.strip("() ")))
        else None
    )


def _col(
    index: int,
    name: str,
    is_required: bool = False,
    is_anchor: bool = False,
    anchor_validator: Callable[[str], bool] | None = None,
    data_extractor: Callable[[str], Any] | None = None,
) -> CanonicalColumn:
    return CanonicalColumn(
        index=index,
        name=name,
        is_required=is_required,
        is_anchor=is_anchor,
        anchor_validator=anchor_validator,
        data_extractor=data_extractor,
    )


def _is_date(s: str) -> bool:
    return bool(NUMERIC_DATE_RE.search(s))


def _is_code(s: str) -> bool:
    return bool(_TRANSACTION_CODE_RE.search(s))


def _is_ad(s: str) -> bool:
    return bool(_ACQUIRED_DISPOSED_RE.fullmatch(s.strip("() ")))


def _is_price(s: str) -> bool:
    return "$" in s or "/sh" in s.lower()


def _is_di(s: str) -> bool:
    return bool(_DIRECT_INDIRECT_RE.fullmatch(s.strip("() ")))


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


_TABLE_I_SCHEMA = TableSchema(
    name="ownership_table_i",
    columns=(
        _col(0, "security_title", is_required=True),
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
        _col(5, "shares_amount", False, False, None, _extract_number),
        _col(6, "acquired_disposed_code", False, True, _is_ad, _extract_ad),
        _col(7, "price_per_share", False, True, _is_price, _extract_number),
        _col(8, "shares_owned_following", False, False, None, _extract_number),
        _col(9, "direct_or_indirect", True, True, _is_di, _extract_di),
        _col(10, "nature_of_ownership"),
    ),
)

_COMMON_TABLE_II_TAIL = (
    _col(0, "exercisable_date", False, True, _is_date, _extract_date),
    _col(1, "expiration_date", False, True, _is_date, _extract_date),
    _col(2, "underlying_security_title", False, True, _is_underlying, _clean_title),
    _col(3, "underlying_shares_amount", False, False, None, _extract_number),
    _col(4, "price_of_derivative", False, True, _is_price, _extract_number),
    _col(5, "derivative_shares_owned_following", False, False, None, _extract_number),
    _col(6, "direct_or_indirect", True, True, _is_di, _extract_di),
    _col(7, "nature_of_ownership"),
)

_TX_TABLE_II_PREFIX = (
    _col(0, "security_title", is_required=True),
    _col(1, "conversion_or_exercise_price", False, True, _is_price, _extract_number),
    _col(2, "transaction_date", False, True, _is_date, _extract_date),
    _col(3, "deemed_execution_date"),
    _col(4, "transaction_code", False, True, _is_code, _extract_code),
    _col(5, "equity_swap", False, False, lambda s: s.strip().upper() == "V"),
    _col(6, "shares_amount", False, False, None, _extract_number),
    _col(7, "acquired_disposed_code", False, False, _is_ad, _extract_ad),
)

_HOLDING_TABLE_II_PREFIX = (
    _col(0, "security_title", is_required=True),
    _col(1, "conversion_or_exercise_price", False, True, _is_price, _extract_number),
)


def _build_table_ii_schema(
    prefix: tuple[CanonicalColumn, ...], name: str
) -> TableSchema:
    cols = tuple(
        replace(c, index=i) for i, c in enumerate(prefix + _COMMON_TABLE_II_TAIL)
    )
    return TableSchema(name=name, columns=cols)


_TABLE_II_TX_SCHEMA = _build_table_ii_schema(
    _TX_TABLE_II_PREFIX, "ownership_table_ii_tx"
)
_TABLE_II_HOLDING_SCHEMA = _build_table_ii_schema(
    _HOLDING_TABLE_II_PREFIX, "ownership_table_ii_holding"
)


def _iter_clean_table_rows(
    section: ClassifiedSection | None, table_label: str
) -> list[tuple[tuple[str, ...], str, list[str]]]:
    if section is None or len(section.resolved_grid.rows) <= 1:
        return []
    out: list[tuple[tuple[str, ...], str, list[str]]] = []
    for row in section.resolved_grid.rows:
        if not any(c.strip() for c in row):
            continue
        row_str = " ".join(c.strip() for c in row if c.strip())
        if any(term in row_str.lower() for term in _TABLE_TERMINATORS):
            break
        if _is_statutory_or_instruction(row_str) or _is_table_header_row(
            row, table_label
        ):
            continue
        out.append((row, row_str, list(_extract_footnote_ids(row_str))))
    return out


def parse_table_i_rows(
    section: ClassifiedSection | None,
) -> list[NonDerivativeTransaction]:
    """Parse Non-Derivative transaction and holding rows from Table I."""
    results: list[NonDerivativeTransaction] = []
    for row, row_str, footnotes in _iter_clean_table_rows(section, "table i"):
        split_cells = tuple(
            part.strip()
            for c in row
            if c.strip()
            for part in c.split("|")
            if part.strip()
        )
        aligned = align_row_to_schema(split_cells, _TABLE_I_SCHEMA)
        if aligned is not None and (
            aligned.get("transaction_date")
            or aligned.get("transaction_code")
            or aligned.get("shares_amount")
            or aligned.get("shares_owned_following")
        ):
            sec_t = _clean_title(aligned.get("security_title") or "")
            if _is_valid_row_security_title(sec_t):
                code_raw = aligned.get("transaction_code")
                eq_swap = bool(code_raw and any("v" in p.lower() for p in split_cells))
                results.append(
                    NonDerivativeTransaction(
                        security_title=sec_t,
                        transaction_date=aligned.get("transaction_date"),
                        transaction_code=code_raw,
                        equity_swap_involved=eq_swap,
                        shares_amount=aligned.get("shares_amount"),
                        acquired_disposed_code=aligned.get("acquired_disposed_code"),
                        price_per_share=aligned.get("price_per_share"),
                        shares_owned_following=aligned.get("shares_owned_following"),
                        direct_or_indirect=aligned.get("direct_or_indirect"),
                        nature_of_ownership=aligned.get("nature_of_ownership"),
                        footnote_ids=tuple(footnotes),
                    )
                )
                continue

        indexed_cells = [(i, c.strip()) for i, c in enumerate(row) if c.strip()]
        if not indexed_cells:
            continue

        footnotes = list(_extract_footnote_ids(row_str))

        raw_title = indexed_cells[0][1]
        security_title = _clean_title(raw_title)
        if not _is_valid_row_security_title(security_title):
            continue

        direct_or_indirect, nature, form_idx = _extract_ownership_form(indexed_cells)

        trans_date: str | None = None
        date_col_idx = -1
        for idx, (_, cell) in enumerate(indexed_cells[1:], start=1):
            if form_idx != -1 and idx >= form_idx:
                break
            m = NUMERIC_DATE_RE.search(cell)
            if m:
                trans_date = m.group(0)
                date_col_idx = idx
                break

        trans_code, equity_swap, code_col_idx = _find_trans_code(
            indexed_cells, form_idx, date_col_idx
        )
        ad_code = _find_ad_code(indexed_cells, form_idx, {date_col_idx, code_col_idx})

        shares_amount: float | None = None
        price_per_share: float | None = None
        shares_owned_following: float | None = None

        for idx, (_, cell) in enumerate(indexed_cells[1:], start=1):
            if form_idx != -1 and idx >= form_idx:
                break
            if "|" in cell:
                parts = [p.strip() for p in cell.split("|")]
                if len(parts) >= 1 and parts[0]:
                    shares_amount = _extract_number(parts[0])
                if len(parts) >= 2 and parts[1]:
                    ad_m = _ACQUIRED_DISPOSED_RE.search(parts[1])
                    if ad_m:
                        ad_code = ad_m.group(1).upper()
                if len(parts) >= 3 and parts[2]:
                    price_per_share = _extract_number(parts[2])

        if price_per_share is None:
            for idx, (_, cell) in enumerate(indexed_cells[1:], start=1):
                if form_idx != -1 and idx >= form_idx:
                    break
                if "$" in cell or "/sh" in cell.lower():
                    price_per_share = _extract_number(cell)
                    break

        remaining_nums = _find_remaining_numbers(
            indexed_cells, form_idx, {date_col_idx, code_col_idx}
        )

        if trans_code is not None or trans_date is not None:
            if shares_amount is None and remaining_nums:
                shares_amount = remaining_nums.pop(0)
            if remaining_nums:
                shares_owned_following = remaining_nums.pop(0)
        else:
            if remaining_nums:
                shares_owned_following = remaining_nums.pop(0)

        if (
            trans_code is None
            and trans_date is None
            and shares_amount is None
            and shares_owned_following is None
        ):
            continue

        results.append(
            NonDerivativeTransaction(
                security_title=security_title,
                transaction_date=trans_date,
                transaction_code=trans_code,
                equity_swap_involved=equity_swap,
                shares_amount=shares_amount,
                acquired_disposed_code=ad_code,
                price_per_share=price_per_share,
                shares_owned_following=shares_owned_following,
                direct_or_indirect=direct_or_indirect,
                nature_of_ownership=nature if nature else None,
                footnote_ids=tuple(footnotes),
            )
        )
    return results


def parse_table_ii_rows(
    section: ClassifiedSection | None,
) -> list[DerivativeTransaction]:
    """Parse Derivative transaction and holding rows from Table II."""
    results: list[DerivativeTransaction] = []
    for row, row_str, footnotes in _iter_clean_table_rows(section, "table ii"):
        split_cells = tuple(
            part.strip()
            for c in row
            if c.strip()
            for part in c.split("|")
            if part.strip()
        )
        if split_cells:
            has_tx = any(_TRANSACTION_CODE_RE.search(c) for c in split_cells[1:])
            schema = _TABLE_II_TX_SCHEMA if has_tx else _TABLE_II_HOLDING_SCHEMA
            aligned = align_row_to_schema(split_cells, schema)
            if aligned is not None and (
                aligned.get("transaction_date")
                or aligned.get("transaction_code")
                or aligned.get("shares_amount")
                or aligned.get("derivative_shares_owned_following")
                or aligned.get("exercisable_date")
                or aligned.get("expiration_date")
            ):
                sec_t = _clean_title(aligned.get("security_title") or "")
                if _is_valid_row_security_title(sec_t):
                    code_raw = aligned.get("transaction_code")
                    eq_swap = bool(
                        code_raw and any("v" in p.lower() for p in split_cells)
                    )
                    ad_code = aligned.get("acquired_disposed_code")
                    if not ad_code and code_raw:
                        ad_code = (
                            "D"
                            if code_raw in ("M", "C", "D", "S", "F")
                            else ("A" if code_raw == "A" else None)
                        )
                    results.append(
                        DerivativeTransaction(
                            security_title=sec_t,
                            conversion_or_exercise_price=aligned.get(
                                "conversion_or_exercise_price"
                            ),
                            transaction_date=aligned.get("transaction_date"),
                            transaction_code=code_raw,
                            equity_swap_involved=eq_swap,
                            shares_amount=aligned.get("shares_amount"),
                            acquired_disposed_code=ad_code,
                            exercisable_date=aligned.get("exercisable_date"),
                            expiration_date=aligned.get("expiration_date"),
                            underlying_security_title=aligned.get(
                                "underlying_security_title"
                            ),
                            underlying_shares_amount=aligned.get(
                                "underlying_shares_amount"
                            ),
                            price_of_derivative=aligned.get("price_of_derivative"),
                            derivative_shares_owned_following=aligned.get(
                                "derivative_shares_owned_following"
                            ),
                            direct_or_indirect=aligned.get("direct_or_indirect"),
                            nature_of_ownership=aligned.get("nature_of_ownership"),
                            footnote_ids=tuple(footnotes),
                        )
                    )
                    continue

        indexed_cells = [(i, c.strip()) for i, c in enumerate(row) if c.strip()]
        if not indexed_cells:
            continue

        raw_title = indexed_cells[0][1]
        security_title = _clean_title(raw_title)
        if not _is_valid_row_security_title(security_title):
            continue

        direct_or_indirect, nature, form_idx = _extract_ownership_form(indexed_cells)

        exercise_price: float | None = None
        price_col_idx = -1
        for idx, (_, cell) in enumerate(indexed_cells[1:5], start=1):
            if "$" in cell or is_numeric_cell(cell):
                exercise_price = _extract_number(cell)
                price_col_idx = idx
                break

        trans_code, equity_swap, code_col_idx = _find_trans_code(
            indexed_cells, form_idx, price_col_idx
        )

        trans_date: str | None = None
        exercisable_date: str | None = None
        expiration_date: str | None = None
        date_col_indices: set[int] = set()

        for idx, (_, cell) in enumerate(indexed_cells[1:], start=1):
            if form_idx != -1 and idx >= form_idx:
                break
            if "|" in cell:
                dates = NUMERIC_DATE_RE.findall(cell)
                if len(dates) >= 2:
                    exercisable_date = dates[0]
                    expiration_date = dates[1]
                    date_col_indices.add(idx)

        found_dates: list[tuple[int, str]] = []
        for idx, (_, cell) in enumerate(indexed_cells[1:], start=1):
            if form_idx != -1 and idx >= form_idx:
                break
            if idx in date_col_indices:
                continue
            m = NUMERIC_DATE_RE.fullmatch(cell.strip())
            if m:
                found_dates.append((idx, m.group(0)))
                date_col_indices.add(idx)

        if code_col_idx != -1:
            before_code = [d for d in found_dates if d[0] < code_col_idx]
            after_code = [d for d in found_dates if d[0] > code_col_idx]
            if before_code:
                trans_date = before_code[0][1]
            if not exercisable_date and len(after_code) >= 2:
                exercisable_date = after_code[0][1]
                expiration_date = after_code[1][1]
            elif not exercisable_date and len(after_code) == 1:
                exercisable_date = after_code[0][1]
        else:
            if not exercisable_date and len(found_dates) >= 2:
                exercisable_date = found_dates[0][1]
                expiration_date = found_dates[1][1]
            elif not exercisable_date and len(found_dates) == 1:
                exercisable_date = found_dates[0][1]

        ad_code = (
            "D"
            if trans_code in ("M", "C", "D", "S", "F")
            else ("A" if trans_code == "A" else None)
        )
        if not ad_code:
            ad_code = _find_ad_code(
                indexed_cells,
                form_idx,
                {price_col_idx, code_col_idx} | date_col_indices,
            )

        underlying_title: str | None = None
        underlying_shares: float | None = None
        underlying_col_indices: set[int] = set()

        for idx, (_, cell) in enumerate(indexed_cells[1:], start=1):
            if form_idx != -1 and idx >= form_idx:
                break
            if idx in (price_col_idx, code_col_idx) or idx in date_col_indices:
                continue
            if "-" in cell:
                parts = [p.strip() for p in cell.rsplit("-", 1)]
                if len(parts) == 2 and is_numeric_cell(parts[1]):
                    underlying_title = _clean_title(parts[0])
                    underlying_shares = _extract_number(parts[1])
                    underlying_col_indices.add(idx)
                    break
            elif any(
                k in cell.lower()
                for k in ("common stock", "preferred stock", "class a", "class b")
            ):
                underlying_title = _clean_title(cell)
                underlying_col_indices.add(idx)
                if idx + 1 < len(indexed_cells) and is_numeric_cell(
                    indexed_cells[idx + 1][1]
                ):
                    underlying_shares = _extract_number(indexed_cells[idx + 1][1])
                    underlying_col_indices.add(idx + 1)
                break

        remaining_nums = _find_remaining_numbers(
            indexed_cells,
            form_idx,
            {price_col_idx, code_col_idx} | date_col_indices | underlying_col_indices,
        )

        shares_amount: float | None = None
        following_shares: float | None = None

        if trans_code is not None or trans_date is not None:
            if remaining_nums:
                shares_amount = remaining_nums.pop(0)
            if remaining_nums:
                following_shares = remaining_nums.pop(0)
        else:
            if remaining_nums:
                following_shares = remaining_nums.pop(0)

        if (
            trans_code is None
            and trans_date is None
            and shares_amount is None
            and exercisable_date is None
            and underlying_title is None
        ):
            continue

        results.append(
            DerivativeTransaction(
                security_title=security_title,
                conversion_or_exercise_price=exercise_price,
                transaction_date=trans_date,
                transaction_code=trans_code,
                equity_swap_involved=equity_swap,
                shares_amount=shares_amount,
                acquired_disposed_code=ad_code,
                exercisable_date=exercisable_date,
                expiration_date=expiration_date,
                underlying_security_title=underlying_title,
                underlying_shares_amount=underlying_shares,
                price_of_derivative=None,
                derivative_shares_owned_following=following_shares,
                direct_or_indirect=direct_or_indirect,
                nature_of_ownership=nature if nature else None,
                footnote_ids=tuple(footnotes),
            )
        )
    return results


def parse_footnotes(sections: list[ClassifiedSection]) -> dict[str, str]:
    """Extract footnote id to text mappings."""
    footnotes: dict[str, str] = {}
    for section in sections:
        for row in section.resolved_grid.rows:
            for cell in row:
                for match in _FOOTNOTE_ENTRY_RE.finditer(cell or ""):
                    fn_id = match.group(1) or match.group(2)
                    text = match.group(3).strip()
                    if fn_id and text:
                        footnotes[fn_id] = text
    return footnotes


__all__ = [
    "DerivativeTransaction",
    "NonDerivativeTransaction",
    "parse_footnotes",
    "parse_table_i_rows",
    "parse_table_ii_rows",
]
