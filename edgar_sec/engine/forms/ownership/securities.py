"""Form 4 Table I (Non-Derivative) and Table II (Derivative) row extraction."""

from __future__ import annotations

from dataclasses import dataclass
import re

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
_INSTRUCTION_TOKEN_SETS = (
    frozenset({"filed", "pursuant", "section", "16"}),
    frozenset({"investment", "company", "act"}),
    frozenset({"check", "box", "longer", "subject"}),
    frozenset({"form", "obligations", "continue"}),
    frozenset({"affirmative", "defense", "10b5-1"}),
    frozenset({"written", "trading", "plan"}),
    frozenset({"reminder", "report", "separate", "line"}),
    frozenset({"intentional", "misstatements", "criminal"}),
    frozenset({"18", "u.s.c", "1001"}),
    frozenset({"15", "u.s.c", "78ff"}),
    frozenset({"omb", "approval"}),
    frozenset({"3235-0287"}),
    frozenset({"burden", "hours"}),
    frozenset({"print", "type", "responses"}),
)


def _is_table_header_row(row: tuple[str, ...], table_label: str) -> bool:
    lower_cells = [c.lower().strip() for c in row if c.strip()]
    if not lower_cells:
        return True
    if any(NUMERIC_DATE_RE.search(c) for c in lower_cells):
        return False
    row_str = " ".join(lower_cells)
    if any(
        k in row_str
        for k in (
            table_label,
            "title of security",
            "title of derivative",
            "title of class",
        )
    ):
        return True
    if any(
        k in row_str
        for k in (
            "transaction date",
            "conversion or exercise",
            "date of earliest",
            "deemed execution date",
        )
    ):
        return True
    header_keywords = sum(
        1
        for c in lower_cells
        if any(
            k in c
            for k in (
                "instr.",
                "month/day",
                "end of month",
                "exercise",
                "conversion",
                "expiration",
                "following",
                "underlying",
            )
        )
        or c in ("code", "v", "amount", "price", "(a) or (d)")
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


_TABLE_I_SCHEMA = TableSchema(
    name="ownership_table_i",
    columns=(
        CanonicalColumn(index=0, name="security_title", is_required=True),
        CanonicalColumn(
            index=1,
            name="transaction_date",
            is_required=False,
            is_anchor=True,
            anchor_validator=lambda s: bool(NUMERIC_DATE_RE.search(s)),
            data_extractor=lambda s: (
                m.group(0) if (m := NUMERIC_DATE_RE.search(s)) else None
            ),
        ),
        CanonicalColumn(index=2, name="deemed_execution_date", is_required=False),
        CanonicalColumn(
            index=3,
            name="transaction_code",
            is_required=False,
            is_anchor=True,
            anchor_validator=lambda s: bool(_TRANSACTION_CODE_RE.search(s)),
            data_extractor=lambda s: (
                m.group(1).upper() if (m := _TRANSACTION_CODE_RE.search(s)) else None
            ),
        ),
        CanonicalColumn(
            index=4,
            name="equity_swap",
            is_required=False,
            is_anchor=True,
            anchor_validator=lambda s: s.strip().upper() == "V",
            data_extractor=lambda s: True,
        ),
        CanonicalColumn(
            index=5,
            name="shares_amount",
            is_required=False,
            data_extractor=_extract_number,
        ),
        CanonicalColumn(
            index=6,
            name="acquired_disposed_code",
            is_required=False,
            is_anchor=True,
            anchor_validator=lambda s: bool(
                _ACQUIRED_DISPOSED_RE.fullmatch(s.strip("() "))
            ),
            data_extractor=lambda s: (
                m.group(1).upper()
                if (m := _ACQUIRED_DISPOSED_RE.fullmatch(s.strip("() ")))
                else None
            ),
        ),
        CanonicalColumn(
            index=7,
            name="price_per_share",
            is_required=False,
            is_anchor=True,
            anchor_validator=lambda s: "$" in s or "/sh" in s.lower(),
            data_extractor=_extract_number,
        ),
        CanonicalColumn(
            index=8,
            name="shares_owned_following",
            is_required=False,
            data_extractor=_extract_number,
        ),
        CanonicalColumn(
            index=9,
            name="direct_or_indirect",
            is_required=True,
            is_anchor=True,
            anchor_validator=lambda s: bool(
                _DIRECT_INDIRECT_RE.fullmatch(s.strip("() "))
            ),
            data_extractor=lambda s: (
                m.group(1).upper()
                if (m := _DIRECT_INDIRECT_RE.fullmatch(s.strip("() ")))
                else None
            ),
        ),
        CanonicalColumn(index=10, name="nature_of_ownership", is_required=False),
    ),
)


def parse_table_i_rows(
    section: ClassifiedSection | None,
) -> list[NonDerivativeTransaction]:
    """Parse Non-Derivative transaction and holding rows from Table I."""
    if section is None or len(section.resolved_grid.rows) <= 1:
        return []

    results: list[NonDerivativeTransaction] = []
    for row in section.resolved_grid.rows:
        if not any(c.strip() for c in row):
            continue

        row_str = " ".join(c.strip() for c in row if c.strip())
        row_lower = row_str.lower()

        if any(term in row_lower for term in _TABLE_TERMINATORS):
            break

        if _is_statutory_or_instruction(row_str):
            continue

        if _is_table_header_row(row, "table i"):
            continue

        footnotes = list(_extract_footnote_ids(row_str))
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
            if (
                sec_t
                and not is_numeric_cell(sec_t)
                and not NUMERIC_DATE_RE.fullmatch(sec_t)
                and not _FOOTNOTE_REF_RE.fullmatch(sec_t)
            ):
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
        if (
            not security_title
            or is_numeric_cell(security_title)
            or NUMERIC_DATE_RE.fullmatch(security_title)
            or _FOOTNOTE_REF_RE.fullmatch(security_title)
        ):
            continue

        direct_or_indirect: str | None = None
        nature: str | None = None
        form_idx = -1
        for idx, (_, cell) in reversed(list(enumerate(indexed_cells))):
            m = _DIRECT_INDIRECT_RE.fullmatch(cell.strip("() "))
            if m:
                direct_or_indirect = m.group(1).upper()
                form_idx = idx
                if idx + 1 < len(indexed_cells):
                    nature = indexed_cells[idx + 1][1]
                break

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

        trans_code: str | None = None
        equity_swap = False
        code_col_idx = -1
        for idx, (_, cell) in enumerate(indexed_cells[1:], start=1):
            if form_idx != -1 and idx >= form_idx:
                break
            if idx == date_col_idx:
                continue
            m = _TRANSACTION_CODE_RE.search(cell)
            if m:
                trans_code = m.group(1).upper()
                equity_swap = bool(m.group(2))
                code_col_idx = idx
                break

        ad_code: str | None = None
        for idx, (_, cell) in enumerate(indexed_cells[1:], start=1):
            if form_idx != -1 and idx >= form_idx:
                break
            if idx in (date_col_idx, code_col_idx):
                continue
            m = _ACQUIRED_DISPOSED_RE.fullmatch(cell.strip("() "))
            if m:
                ad_code = m.group(1).upper()
                break

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

        remaining_nums: list[float] = []
        for idx, (_, cell) in enumerate(indexed_cells[1:], start=1):
            if form_idx != -1 and idx >= form_idx:
                break
            if idx in (date_col_idx, code_col_idx):
                continue
            if "|" in cell or "$" in cell or "/sh" in cell.lower():
                continue
            if is_numeric_cell(cell):
                val = _extract_number(cell)
                if val is not None:
                    remaining_nums.append(val)

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
    if section is None or len(section.resolved_grid.rows) <= 1:
        return []

    results: list[DerivativeTransaction] = []
    for row in section.resolved_grid.rows:
        if not any(c.strip() for c in row):
            continue

        row_str = " ".join(c.strip() for c in row if c.strip())
        row_lower = row_str.lower()

        if any(term in row_lower for term in _TABLE_TERMINATORS):
            break

        if _is_statutory_or_instruction(row_str):
            continue

        if _is_table_header_row(row, "table ii"):
            continue

        indexed_cells = [(i, c.strip()) for i, c in enumerate(row) if c.strip()]
        if not indexed_cells:
            continue

        footnotes = list(_extract_footnote_ids(row_str))

        raw_title = indexed_cells[0][1]
        security_title = _clean_title(raw_title)
        if (
            not security_title
            or is_numeric_cell(security_title)
            or NUMERIC_DATE_RE.fullmatch(security_title)
            or _FOOTNOTE_REF_RE.fullmatch(security_title)
        ):
            continue

        direct_or_indirect: str | None = None
        nature: str | None = None
        form_idx = -1
        for idx, (_, cell) in reversed(list(enumerate(indexed_cells))):
            m = _DIRECT_INDIRECT_RE.fullmatch(cell.strip("() "))
            if m:
                direct_or_indirect = m.group(1).upper()
                form_idx = idx
                if idx + 1 < len(indexed_cells):
                    nature = indexed_cells[idx + 1][1]
                break

        exercise_price: float | None = None
        price_col_idx = -1
        for idx, (_, cell) in enumerate(indexed_cells[1:5], start=1):
            if "$" in cell or is_numeric_cell(cell):
                exercise_price = _extract_number(cell)
                price_col_idx = idx
                break

        trans_code: str | None = None
        equity_swap = False
        code_col_idx = -1
        for idx, (_, cell) in enumerate(indexed_cells[1:], start=1):
            if form_idx != -1 and idx >= form_idx:
                break
            if idx == price_col_idx:
                continue
            m = _TRANSACTION_CODE_RE.search(cell)
            if m:
                trans_code = m.group(1).upper()
                equity_swap = bool(m.group(2))
                code_col_idx = idx
                break

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

        ad_code: str | None = None
        if trans_code in ("M", "C", "D", "S", "F"):
            ad_code = "D"
        elif trans_code == "A":
            ad_code = "A"

        for idx, (_, cell) in enumerate(indexed_cells[1:], start=1):
            if form_idx != -1 and idx >= form_idx:
                break
            if idx in (price_col_idx, code_col_idx) or idx in date_col_indices:
                continue
            m = _ACQUIRED_DISPOSED_RE.fullmatch(cell.strip("() "))
            if m:
                ad_code = m.group(1).upper()
                break

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

        remaining_nums: list[float] = []
        for idx, (_, cell) in enumerate(indexed_cells[1:], start=1):
            if form_idx != -1 and idx >= form_idx:
                break
            if (
                idx in (price_col_idx, code_col_idx)
                or idx in date_col_indices
                or idx in underlying_col_indices
            ):
                continue
            if is_numeric_cell(cell):
                val = _extract_number(cell)
                if val is not None:
                    remaining_nums.append(val)

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
