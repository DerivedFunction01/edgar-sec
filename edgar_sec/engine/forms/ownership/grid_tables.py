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


def parse_table_i_rows(
    section: ClassifiedSection | None,
) -> list[NonDerivativeTransaction]:
    """Parse Non-Derivative transaction rows from Table I."""
    if section is None or len(section.resolved_grid.rows) <= 1:
        return []

    results: list[NonDerivativeTransaction] = []
    for row in section.resolved_grid.rows[1:]:
        if not any(c.strip() for c in row):
            continue

        security_title = row[0].strip() if len(row) > 0 else ""
        if not security_title or "title of security" in security_title.lower():
            continue

        # Date & footnotes
        date_cell = row[1].strip() if len(row) > 1 else ""
        date_match = NUMERIC_DATE_RE.search(date_cell)
        trans_date = date_match.group(0) if date_match else None
        footnotes = list(_extract_footnote_ids(date_cell))

        # Code & voluntary flag
        code_cell = row[2].strip() if len(row) > 2 else ""
        code_match = _TRANSACTION_CODE_RE.search(code_cell)
        trans_code = code_match.group(1) if code_match else None
        equity_swap = bool(code_match and code_match.group(2))

        # Amount, A/D, Price
        amount_cell = row[3].strip() if len(row) > 3 else ""
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

        # End of Month
        following_cell = row[4].strip() if len(row) > 4 else ""
        shares_owned_following = _extract_number(following_cell)

        # Ownership Form
        form_cell = row[5].strip().upper() if len(row) > 5 else ""
        direct_or_indirect = form_cell if form_cell in ("D", "I") else None

        # Nature
        nature = row[6].strip() if len(row) > 6 else ""

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

    results: list[DerivativeTransaction] = []
    for row in section.resolved_grid.rows[1:]:
        if not any(c.strip() for c in row):
            continue

        security_title = row[0].strip() if len(row) > 0 else ""
        if not security_title or "title of derivative" in security_title.lower():
            continue

        # Exercise Price
        price_cell = row[1].strip() if len(row) > 1 else ""
        exercise_price = _extract_number(price_cell)

        # Trans Date
        date_cell = row[2].strip() if len(row) > 2 else ""
        date_match = NUMERIC_DATE_RE.search(date_cell)
        trans_date = date_match.group(0) if date_match else None
        footnotes = list(_extract_footnote_ids(date_cell))

        # Code
        code_cell = row[3].strip() if len(row) > 3 else ""
        code_match = _TRANSACTION_CODE_RE.search(code_cell)
        trans_code = code_match.group(1) if code_match else None
        equity_swap = bool(code_match and code_match.group(2))

        # Amount & A/D
        amount_cell = row[4].strip() if len(row) > 4 else ""
        shares_amount = _extract_number(amount_cell)
        ad_match = re.search(r"\b([AD])\b", amount_cell, re.IGNORECASE)
        ad_code = ad_match.group(1).upper() if ad_match else None

        # Exercisable and Expiration Dates
        dates_cell = row[5].strip() if len(row) > 5 else ""
        exercisable_date: str | None = None
        expiration_date: str | None = None
        date_matches = NUMERIC_DATE_RE.findall(dates_cell)
        if len(date_matches) >= 2:
            exercisable_date = date_matches[0]
            expiration_date = date_matches[1]
        elif len(date_matches) == 1:
            exercisable_date = date_matches[0]

        # Underlying Securities
        underlying_cell = row[6].strip() if len(row) > 6 else ""
        underlying_title: str | None = None
        underlying_shares: float | None = None
        if "-" in underlying_cell:
            u_parts = [p.strip() for p in underlying_cell.rsplit("-", 1)]
            underlying_title = u_parts[0]
            if len(u_parts) > 1:
                underlying_shares = _extract_number(u_parts[1])
        elif underlying_cell:
            underlying_title = underlying_cell

        # Price of derivative
        deriv_price_cell = row[7].strip() if len(row) > 7 else ""
        deriv_price = _extract_number(deriv_price_cell)

        # Following shares
        following_cell = row[8].strip() if len(row) > 8 else ""
        following_shares = _extract_number(following_cell)

        # Ownership Form
        form_cell = row[9].strip().upper() if len(row) > 9 else ""
        direct_or_indirect = form_cell if form_cell in ("D", "I") else None

        # Nature
        nature = row[10].strip() if len(row) > 10 else ""

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
