"""Grid table parsing for Form 4 Table I (Non-Derivative) and Table II (Derivative)."""

from __future__ import annotations

from dataclasses import dataclass
import re

from edgar_sec.engine.forms.ownership.patterns import HEADER_LEAK_RE, TEMPLATE_LABELS
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
_NUMERIC_TOKEN_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_ACQUIRED_DISPOSED_RE = re.compile(r"\b([AD])\b", re.IGNORECASE)
_DIRECT_INDIRECT_RE = re.compile(r"\b([DI])\b", re.IGNORECASE)
_TABLE_ARTIFACT_PHRASES = (
    "reminder:",
    "reminder report on a separate",
    "potential persons who are to respond",
    "form 4 (continued)",
    "form 5 (continued)",
    "form 3 (continued)",
    "date exercisable",
    "expiration date",
    "title and amount of underlying",
    "underlying securities",
    "intentional misstatements",
    "see 18 u.s.c.",
    "file three copies",
    "currently valid omb",
    "explanation of responses",
    "no unreported activity",
    "see instruction",
    "if the form is filed by more than one",
)
_TABLE_I_HEADER_MARKERS = (
    "title of security",
    "transaction date",
    "transaction code",
    "securities acquired",
    "beneficially owned",
    "ownership form",
    "direct (d)",
    "nature of indirect",
    "deemed execution date",
)
_TABLE_II_HEADER_MARKERS = (
    "title of derivative",
    "conversion or exercise",
    "transaction date",
    "deemed execution date",
    "transaction code",
    "number of derivative securities",
    "date exercisable",
    "expiration date",
    "title and amount of underlying",
    "price of derivative",
    "beneficially owned following",
    "ownership form",
    "nature of indirect",
)
_TABLE_I_HEADER_CELLS = frozenset({"code", "amount", "price", "(a) or (d)"})
_TABLE_II_HEADER_CELLS = frozenset({"code", "v", "(a)", "(d)", "title"})
_TEMPLATE_TITLE_MARKERS = tuple(f"({label.lower()})" for label in TEMPLATE_LABELS)


def _normalized_header_text(text: str) -> str:
    return " ".join(text.replace("-\r\n", "").replace("-\n", "").split()).lower()


def _normalized_header_rows(
    grid_rows: tuple[tuple[str, ...], ...], limit: int
) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(_normalized_header_text(cell) for cell in row)
        for row in grid_rows[:limit]
    )


def _header_rows(
    grid_rows: tuple[tuple[str, ...], ...],
    markers: tuple[str, ...],
    exact_cells: frozenset[str],
    excluded_phrases: tuple[str, ...] = (),
) -> list[tuple[str, ...]]:
    selected = []
    for row in _normalized_header_rows(grid_rows, 8):
        row_text = " ".join(row)
        if any(phrase in row_text for phrase in excluded_phrases):
            continue
        has_header_marker = any(marker in row_text for marker in markers)
        has_numeric_value = any(
            NUMERIC_DATE_RE.search(cell) or is_numeric_cell(cell) for cell in row
        )
        if has_header_marker or (
            not has_numeric_value and any(cell in exact_cells for cell in row)
        ):
            selected.append(row)
    return selected


def _is_artifact_title(title: str, table_label: str) -> bool:
    lower = " ".join(title.lower().split())
    return (
        not title
        or not title.strip(" *_-=")
        or bool(NUMERIC_DATE_RE.fullmatch(lower.strip()))
        or any(phrase in lower for phrase in _TABLE_ARTIFACT_PHRASES)
        or "title of" in lower
        or "instr." in lower
        or "month/day" in lower
        or table_label in lower
        or any(marker in lower for marker in _TEMPLATE_TITLE_MARKERS)
        or HEADER_LEAK_RE.search(lower) is not None
    )


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
    if text.isascii() and text.isdigit():
        return float(text)
    cleaned = _CLEAN_NUMERIC_RE.sub("", text)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        match = _NUMERIC_TOKEN_RE.search(cleaned)
        return float(match.group(0).replace(",", "")) if match else None


def _extract_footnote_ids(text: str) -> tuple[str, ...]:
    return tuple(_FOOTNOTE_REF_RE.findall(text))


def _table_i_column_mapping(
    grid_rows: tuple[tuple[str, ...], ...],
) -> dict[str, int | None]:
    num_cols = len(grid_rows[0]) if grid_rows else 0
    header_rows = _header_rows(
        grid_rows,
        _TABLE_I_HEADER_MARKERS,
        _TABLE_I_HEADER_CELLS,
        excluded_phrases=("table i -",),
    )
    header_text = " ".join(" ".join(row) for row in header_rows)
    has_3a = "3a" in header_text or "deemed execution date" in header_text
    is_holding = (
        num_cols <= 5
        and "transaction date" not in header_text
        and "transaction code" not in header_text
    )
    mapping = {
        "title": 0,
        "date": None if is_holding else 1,
        "code": None if is_holding else (3 if has_3a else 2),
        "amount": None if is_holding else (4 if has_3a else 3),
        "ad": None,
        "price": None,
        "following": 1 if is_holding else (5 if has_3a else 4),
        "form": 2 if is_holding else (6 if has_3a else 5),
        "nature": 3 if is_holding else (7 if has_3a else 6),
    }
    if header_rows:
        for c in range(num_cols):
            col_text = " ".join(row[c] for row in header_rows if len(row) > c)
            if "title of security" in col_text or (c == 0 and "title" in col_text):
                mapping["title"] = c
            elif "transaction date" in col_text:
                mapping["date"] = c
            elif "transaction code" in col_text or "instr. 8" in col_text:
                mapping["code"] = c
            elif (
                "securities acquired" in col_text
                and "beneficially owned" not in col_text
            ):
                mapping["amount"] = c
            elif "(a) or (d)" in col_text and "securities acquired" not in col_text:
                mapping["ad"] = c
            elif "price" in col_text:
                mapping["price"] = c
            elif "beneficially owned" in col_text or "following" in col_text:
                mapping["following"] = c
            elif "ownership form" in col_text or "direct (d)" in col_text:
                mapping["form"] = c
            elif "nature of indirect" in col_text:
                mapping["nature"] = c
    return mapping


def _table_ii_column_mapping(
    grid_rows: tuple[tuple[str, ...], ...],
) -> dict[str, int | None]:
    num_cols = len(grid_rows[0]) if grid_rows else 0
    header_rows = _header_rows(
        grid_rows,
        _TABLE_II_HEADER_MARKERS,
        _TABLE_II_HEADER_CELLS,
        excluded_phrases=("table ii", "form 4 (continued)"),
    )
    header_text = " ".join(" ".join(row) for row in header_rows)
    has_3a = "deemed execution date" in header_text or "3a." in header_text
    mapping = {
        "title": 0,
        "price": 1,
        "date": 2,
        "code": 4 if has_3a else 3,
        "amount": 5 if has_3a else 4,
        "acquired": None,
        "disposed": None,
        "equity_swap": None,
        "dates": 6 if has_3a else 5,
        "exercisable": None,
        "expiration": None,
        "underlying": 7 if has_3a else 6,
        "underlying_shares": None,
        "deriv_price": 8 if has_3a else 7,
        "following": 9 if has_3a else 8,
        "form": 10 if has_3a else 9,
        "nature": 11 if has_3a else 10,
    }
    for c in range(num_cols):
        cells = [row[c] for row in header_rows if len(row) > c]
        col_text = " ".join(cells)
        if "title of derivative" in col_text:
            mapping["title"] = c
        elif "conversion or exercise" in col_text or (
            c == 1 and "price" in col_text and "derivative" not in col_text
        ):
            mapping["price"] = c
        elif "transaction date" in col_text and "deemed" not in col_text:
            mapping["date"] = c
        elif "transaction code" in col_text or "instr. 8" in col_text:
            mapping["code"] = c
        elif any("v" == cell for cell in cells):
            mapping["equity_swap"] = c
        elif any(cell in {"(a)", "a"} for cell in cells):
            mapping["acquired"] = c
        elif any(cell in {"(d)", "d"} for cell in cells):
            mapping["disposed"] = c
        elif any(cell == "date exercisable" for cell in cells):
            mapping["exercisable"] = c
        elif any(cell in {"expiration date", "exp date"} for cell in cells):
            mapping["expiration"] = c
        elif "date exercisable" in col_text and (
            "expiration date" in col_text or "exp date" in col_text
        ):
            mapping["dates"] = c
        elif "date exercisable" in col_text:
            mapping["exercisable"] = c
        elif "expiration date" in col_text or "exp date" in col_text:
            mapping["expiration"] = c
        elif "amount or number of shares" in col_text:
            mapping["underlying_shares"] = c
        elif "title and amount of underlying" in col_text or (
            "underlying" in col_text and any(cell == "title" for cell in cells)
        ):
            mapping["underlying"] = c
        elif "price of derivative" in col_text:
            mapping["deriv_price"] = c
        elif "beneficially owned following" in col_text or "following" in col_text:
            mapping["following"] = c
        elif "ownership form" in col_text or "direct (d)" in col_text:
            mapping["form"] = c
        elif "nature of indirect" in col_text:
            mapping["nature"] = c
        elif "number of derivative securities" in col_text:
            mapping["amount"] = c
    return mapping


def parse_table_i_rows(
    section: ClassifiedSection | None,
) -> list[NonDerivativeTransaction]:
    """Parse Non-Derivative transaction rows from Table I."""
    if section is None or len(section.resolved_grid.rows) <= 1:
        return []

    header_count = max(1, section.resolved_grid.header_row_count)
    cols = _table_i_column_mapping(section.resolved_grid.rows)
    title_col = cols["title"]
    date_col = cols["date"]
    code_col = cols["code"]
    amount_col = cols["amount"]
    ad_col = cols["ad"]
    price_col = cols["price"]
    following_col = cols["following"]
    form_col = cols["form"]
    nature_col = cols["nature"]
    results: list[NonDerivativeTransaction] = []
    for row in section.resolved_grid.rows[header_count:]:
        if not any(c.strip() for c in row):
            continue

        security_title = row[title_col].strip() if len(row) > title_col else ""
        if _is_artifact_title(security_title, "table i"):
            continue

        date_cell = (
            row[date_col].strip()
            if date_col is not None and len(row) > date_col
            else ""
        )
        date_match = NUMERIC_DATE_RE.search(date_cell)
        trans_date = date_match.group(0) if date_match else None
        footnotes = list(_extract_footnote_ids(date_cell))

        code_cell = (
            row[code_col].strip()
            if code_col is not None and len(row) > code_col
            else ""
        )
        code_match = _TRANSACTION_CODE_RE.search(code_cell)
        trans_code = code_match.group(1) if code_match else None
        equity_swap = bool(code_match and code_match.group(2))

        amount_cell = (
            row[amount_col].strip()
            if amount_col is not None and len(row) > amount_col
            else ""
        )
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

        if ad_code is None and ad_col is not None and len(row) > ad_col:
            ad_match = _ACQUIRED_DISPOSED_RE.search(row[ad_col])
            ad_code = ad_match.group(1).upper() if ad_match else None

        if price is None and price_col is not None and price_col != amount_col:
            price_cell = row[price_col].strip() if len(row) > price_col else ""
            price = _extract_number(price_cell)

        following_cell = (
            row[following_col].strip()
            if following_col is not None and len(row) > following_col
            else ""
        )
        shares_owned_following = _extract_number(following_cell)

        form_cell = (
            row[form_col].strip().upper()
            if form_col is not None and len(row) > form_col
            else ""
        )
        form_match = _DIRECT_INDIRECT_RE.search(form_cell)
        direct_or_indirect = form_match.group(1).upper() if form_match else None

        nature = (
            row[nature_col].strip()
            if nature_col is not None and len(row) > nature_col
            else ""
        )

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
    cols = _table_ii_column_mapping(section.resolved_grid.rows)
    title_col = cols["title"]
    price_col = cols["price"]
    date_col = cols["date"]
    code_col = cols["code"]
    swap_col = cols.get("equity_swap")
    amount_col = cols["amount"]
    acquired_col = cols.get("acquired")
    disposed_col = cols.get("disposed")
    acquired_disposed_columns = ((acquired_col, "A"), (disposed_col, "D"))
    dates_col = cols["dates"]
    exercisable_col = cols.get("exercisable")
    expiration_col = cols.get("expiration")
    underlying_col = cols["underlying"]
    underlying_shares_col = cols.get("underlying_shares")
    derivative_price_col = cols["deriv_price"]
    following_col = cols["following"]
    form_col = cols["form"]
    nature_col = cols["nature"]
    results: list[DerivativeTransaction] = []
    for row in section.resolved_grid.rows[header_count:]:
        if not any(c.strip() for c in row):
            continue

        security_title = row[title_col].strip() if len(row) > title_col else ""
        if _is_artifact_title(security_title, "table ii"):
            continue

        price_cell = row[price_col].strip() if len(row) > price_col else ""
        exercise_price = _extract_number(price_cell)

        date_cell = row[date_col].strip() if len(row) > date_col else ""
        date_match = NUMERIC_DATE_RE.search(date_cell)
        trans_date = date_match.group(0) if date_match else None
        footnotes = list(_extract_footnote_ids(date_cell))

        code_cell = row[code_col].strip() if len(row) > code_col else ""
        code_match = _TRANSACTION_CODE_RE.search(code_cell)
        trans_code = code_match.group(1) if code_match else None
        equity_swap = bool(code_match and code_match.group(2))
        if swap_col is not None and len(row) > swap_col:
            equity_swap = equity_swap or bool(row[swap_col].strip())

        amount_cell = row[amount_col].strip() if len(row) > amount_col else ""
        shares_amount = _extract_number(amount_cell)
        ad_match = _ACQUIRED_DISPOSED_RE.search(amount_cell)
        ad_code = ad_match.group(1).upper() if ad_match else None
        for column, transaction_type in acquired_disposed_columns:
            if column is not None and len(row) > column:
                column_amount = _extract_number(row[column])
                if column_amount is not None:
                    shares_amount = column_amount
                    ad_code = transaction_type
                    break

        dates_cell = (
            row[dates_col].strip()
            if dates_col is not None and len(row) > dates_col
            else ""
        )
        exercisable_date: str | None = None
        expiration_date: str | None = None
        if exercisable_col is not None:
            exercisable_cell = row[exercisable_col].strip()
            exercisable_match = NUMERIC_DATE_RE.search(exercisable_cell)
            exercisable_date = exercisable_match.group(0) if exercisable_match else None
        if expiration_col is not None:
            expiration_cell = row[expiration_col].strip()
            expiration_match = NUMERIC_DATE_RE.search(expiration_cell)
            expiration_date = expiration_match.group(0) if expiration_match else None
        if exercisable_col is None and expiration_col is None:
            date_matches = NUMERIC_DATE_RE.findall(dates_cell)
            if len(date_matches) >= 2:
                exercisable_date = date_matches[0]
                expiration_date = date_matches[1]
            elif len(date_matches) == 1:
                exercisable_date = date_matches[0]

        underlying_cell = (
            row[underlying_col].strip()
            if underlying_col is not None and len(row) > underlying_col
            else ""
        )
        underlying_title: str | None = None
        underlying_shares: float | None = None
        if (
            underlying_shares_col is not None
            and len(row) > underlying_shares_col
            and row[underlying_shares_col].strip()
        ):
            underlying_shares = _extract_number(row[underlying_shares_col].strip())
            underlying_title = underlying_cell if underlying_cell else None
        elif "-" in underlying_cell:
            u_parts = [p.strip() for p in underlying_cell.rsplit("-", 1)]
            underlying_title = u_parts[0]
            if len(u_parts) > 1:
                underlying_shares = _extract_number(u_parts[1])
        elif underlying_cell:
            underlying_title = underlying_cell

        if underlying_title and is_numeric_cell(underlying_title):
            if not underlying_shares:
                underlying_shares = _extract_number(underlying_title)
            underlying_title = None

        underlying_dates = (
            NUMERIC_DATE_RE.findall(underlying_title) if underlying_title else []
        )
        if underlying_title and (underlying_dates or "|" in underlying_title):
            date_matches = underlying_dates
            if not exercisable_date and len(date_matches) >= 1:
                exercisable_date = date_matches[0]
            if not expiration_date and len(date_matches) >= 2:
                expiration_date = date_matches[1]
            underlying_title = None
            underlying_shares = None

        if underlying_title:
            u_low = underlying_title.lower()
            if (
                HEADER_LEAK_RE.search(u_low) is not None
                or "instr." in u_low
                or "month/day" in u_low
            ):
                underlying_title = None
                underlying_shares = None

        deriv_price_cell = (
            row[derivative_price_col].strip() if len(row) > derivative_price_col else ""
        )
        deriv_price = _extract_number(deriv_price_cell)

        following_cell = row[following_col].strip() if len(row) > following_col else ""
        following_shares = _extract_number(following_cell)

        form_cell = row[form_col].strip().upper() if len(row) > form_col else ""
        form_match = _DIRECT_INDIRECT_RE.search(form_cell)
        direct_or_indirect = form_match.group(1).upper() if form_match else None

        nature = row[nature_col].strip() if len(row) > nature_col else ""

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
                if not cell:
                    continue
                for match in _FOOTNOTE_ENTRY_RE.finditer(cell):
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
