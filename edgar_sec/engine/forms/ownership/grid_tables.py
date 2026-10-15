"""Grid table parsing for Form 4 Table I (Non-Derivative) and Table II (Derivative)."""

from __future__ import annotations

from dataclasses import dataclass
import re

from edgar_sec.engine.forms.ownership.sections import ClassifiedSection
from edgar_sec.engine.tables.numeric_cells import (
    CURRENCY_TOKEN_RE,
    is_numeric_cell,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import NUMERIC_DATE_RE

_TRANSACTION_CODES = (
    "P",
    "S",
    "A",
    "D",
    "F",
    "I",
    "M",
    "C",
    "E",
    "H",
    "O",
    "X",
    "G",
    "L",
    "W",
    "Z",
    "J",
    "U",
    "K",
)
_TRANSACTION_CODE_ALT = build_alternation(sorted(_TRANSACTION_CODES), auto_escape=True)
_TRANSACTION_CODE_RE = re.compile(rf"\b({_TRANSACTION_CODE_ALT})\b(?:\s*\|\s*([Vv]))?")
_FOOTNOTE_REF_RE = re.compile(r"[\(\[](\d{1,3})[\)\]]")
_FOOTNOTE_ENTRY_RE = re.compile(
    r"^\s*(?:[\(\[]\s*(\d{1,3})\s*[\)\]]|(\d{1,3})\.)\s*(.+)", re.MULTILINE
)
_CLEAN_NUMERIC_RE = re.compile(r"[\$,\s\(\)]")
_ACQUIRED_DISPOSED_RE = re.compile(r"\b([AD])\b", re.IGNORECASE)


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
    cleaned = _CLEAN_NUMERIC_RE.sub("", text)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_footnote_ids(text: str) -> tuple[str, ...]:
    return tuple(_FOOTNOTE_REF_RE.findall(text))


def _table_i_column_mapping(
    grid_rows: tuple[tuple[str, ...], ...], header_count: int
) -> dict[str, int]:
    num_cols = len(grid_rows[0]) if grid_rows else 0
    header_text = " ".join(
        " ".join(grid_rows[r]) for r in range(min(header_count, len(grid_rows)))
    ).lower()
    has_3a = "3a" in header_text or "deemed" in header_text or num_cols >= 8
    if has_3a:
        return {
            "title": 0,
            "date": 1,
            "code": 3,
            "amount": 4,
            "following": 5,
            "form": 6,
            "nature": 7,
        }
    return {
        "title": 0,
        "date": 1,
        "code": 2,
        "amount": 3,
        "following": 4,
        "form": 5,
        "nature": 6,
    }


def _table_ii_column_mapping(
    grid_rows: tuple[tuple[str, ...], ...], header_count: int
) -> dict[str, int]:
    num_cols = len(grid_rows[0]) if grid_rows else 0
    header_text = " ".join(
        " ".join(grid_rows[r]) for r in range(min(header_count, len(grid_rows)))
    ).lower()
    has_3a = "3a" in header_text or "deemed" in header_text or num_cols >= 12
    if has_3a:
        return {
            "title": 0,
            "price": 1,
            "date": 2,
            "code": 4,
            "amount": 5,
            "dates": 6,
            "underlying": 7,
            "deriv_price": 8,
            "following": 9,
            "form": 10,
            "nature": 11,
        }
    return {
        "title": 0,
        "price": 1,
        "date": 2,
        "code": 3,
        "amount": 4,
        "dates": 5,
        "underlying": 6,
        "deriv_price": 7,
        "following": 8,
        "form": 9,
        "nature": 10,
    }


def parse_table_i_rows(
    section: ClassifiedSection | None,
) -> list[NonDerivativeTransaction]:
    """Parse Non-Derivative transaction rows from Table I."""
    if section is None or len(section.resolved_grid.rows) <= 1:
        return []

    header_count = max(1, section.resolved_grid.header_row_count)
    cols = _table_i_column_mapping(section.resolved_grid.rows, header_count)
    results: list[NonDerivativeTransaction] = []
    for row in section.resolved_grid.rows[header_count:]:
        if not any(c.strip() for c in row):
            continue

        security_title = row[cols["title"]].strip() if len(row) > cols["title"] else ""
        if (
            not security_title
            or "title of" in security_title.lower()
            or "instr." in security_title.lower()
        ):
            continue

        date_col = cols["date"]
        date_cell = row[date_col].strip() if len(row) > date_col else ""
        date_match = NUMERIC_DATE_RE.search(date_cell)
        trans_date = date_match.group(0) if date_match else None
        footnotes = list(_extract_footnote_ids(date_cell))

        code_col = cols["code"]
        code_cell = row[code_col].strip() if len(row) > code_col else ""
        code_match = _TRANSACTION_CODE_RE.search(code_cell)
        trans_code = code_match.group(1) if code_match else None
        equity_swap = bool(code_match and code_match.group(2))

        amt_col = cols["amount"]
        amount_cell = row[amt_col].strip() if len(row) > amt_col else ""
        shares_amount: float | None = None
        ad_code: str | None = None
        price: float | None = None

        if "|" in amount_cell:
            parts = [p.strip() for p in amount_cell.split("|")]
            if len(parts) >= 1 and parts[0]:
                shares_amount = _extract_number(parts[0])
            if len(parts) >= 2 and parts[1]:
                ad_code = parts[1].upper() if parts[1].upper() in ("A", "D") else None
            if len(parts) >= 3 and parts[2]:
                price = _extract_number(parts[2])
        elif is_numeric_cell(amount_cell):
            shares_amount = _extract_number(amount_cell)

        foll_col = cols["following"]
        following_cell = row[foll_col].strip() if len(row) > foll_col else ""
        shares_owned_following = _extract_number(following_cell)

        form_col = cols["form"]
        form_cell = row[form_col].strip().upper() if len(row) > form_col else ""
        direct_or_indirect = form_cell if form_cell in ("D", "I") else None

        nat_col = cols["nature"]
        nature = row[nat_col].strip() if len(row) > nat_col else ""

        results.append(
            NonDerivativeTransaction(
                security_title=security_title,
                transaction_date=trans_date,
                transaction_code=trans_code,
                equity_swap_involved=equity_swap,
                shares_amount=shares_amount,
                acquired_disposed_code=ad_code,
                price_per_share=price,
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
    if section is None or len(section.resolved_grid.rows) <= 1:
        return []

    header_count = max(1, section.resolved_grid.header_row_count)
    cols = _table_ii_column_mapping(section.resolved_grid.rows, header_count)
    results: list[DerivativeTransaction] = []
    for row in section.resolved_grid.rows[header_count:]:
        if not any(c.strip() for c in row):
            continue

        security_title = row[cols["title"]].strip() if len(row) > cols["title"] else ""
        if (
            not security_title
            or "title of" in security_title.lower()
            or "instr." in security_title.lower()
        ):
            continue

        price_col = cols["price"]
        price_cell = row[price_col].strip() if len(row) > price_col else ""
        exercise_price = _extract_number(price_cell)

        date_col = cols["date"]
        date_cell = row[date_col].strip() if len(row) > date_col else ""
        date_match = NUMERIC_DATE_RE.search(date_cell)
        trans_date = date_match.group(0) if date_match else None
        footnotes = list(_extract_footnote_ids(date_cell))

        code_col = cols["code"]
        code_cell = row[code_col].strip() if len(row) > code_col else ""
        code_match = _TRANSACTION_CODE_RE.search(code_cell)
        trans_code = code_match.group(1) if code_match else None
        equity_swap = bool(code_match and code_match.group(2))

        amt_col = cols["amount"]
        amount_cell = row[amt_col].strip() if len(row) > amt_col else ""
        shares_amount = _extract_number(amount_cell)
        ad_match = _ACQUIRED_DISPOSED_RE.search(amount_cell)
        ad_code = ad_match.group(1).upper() if ad_match else None

        dates_col = cols["dates"]
        dates_cell = row[dates_col].strip() if len(row) > dates_col else ""
        exercisable_date: str | None = None
        expiration_date: str | None = None
        date_matches = NUMERIC_DATE_RE.findall(dates_cell)
        if len(date_matches) >= 2:
            exercisable_date = date_matches[0]
            expiration_date = date_matches[1]
        elif len(date_matches) == 1:
            exercisable_date = date_matches[0]

        u_col = cols["underlying"]
        underlying_cell = row[u_col].strip() if len(row) > u_col else ""
        underlying_title: str | None = None
        underlying_shares: float | None = None
        if "-" in underlying_cell:
            u_parts = [p.strip() for p in underlying_cell.rsplit("-", 1)]
            underlying_title = u_parts[0]
            if len(u_parts) > 1:
                underlying_shares = _extract_number(u_parts[1])
        elif underlying_cell:
            underlying_title = underlying_cell

        if underlying_title and (
            bool(NUMERIC_DATE_RE.search(underlying_title)) or "|" in underlying_title
        ):
            date_matches = NUMERIC_DATE_RE.findall(underlying_title)
            if not exercisable_date and len(date_matches) >= 1:
                exercisable_date = date_matches[0]
            if not expiration_date and len(date_matches) >= 2:
                expiration_date = date_matches[1]
            underlying_title = None
            underlying_shares = None

        deriv_col = cols["deriv_price"]
        deriv_price_cell = row[deriv_col].strip() if len(row) > deriv_col else ""
        deriv_price = _extract_number(deriv_price_cell)

        foll_col = cols["following"]
        following_cell = row[foll_col].strip() if len(row) > foll_col else ""
        following_shares = _extract_number(following_cell)

        form_col = cols["form"]
        form_cell = row[form_col].strip().upper() if len(row) > form_col else ""
        direct_or_indirect = form_cell if form_cell in ("D", "I") else None

        nat_col = cols["nature"]
        nature = row[nat_col].strip() if len(row) > nat_col else ""

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
                price_of_derivative=deriv_price,
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
                for line in cell.splitlines():
                    match = _FOOTNOTE_ENTRY_RE.search(line.strip())
                    if match:
                        fn_id = match.group(1) or match.group(2)
                        text = match.group(3).strip() if match.group(3) else ""
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
