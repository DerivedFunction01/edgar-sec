"""Ownership Table II (Derivative) row extraction."""

from __future__ import annotations

from edgar_sec.engine.forms.common.alignment import align_row_to_schema
from edgar_sec.engine.forms.common.numbers import extract_schema_number
from edgar_sec.engine.forms.common.row_extraction import (
    normalize_row_record,
    split_row_cells,
)
from edgar_sec.engine.forms.ownership.row_specs import OWNERSHIP_TABLE_II_ROW_SPEC
from edgar_sec.engine.forms.ownership.sections import ClassifiedSection
from edgar_sec.engine.forms.ownership.table_common import (
    ACQUIRED_DISPOSED_RE,
    TABLE_II_HOLDING_SCHEMA,
    TRANSACTION_CODE_RE,
    DerivativeTransaction,
    TABLE_II_TX_SCHEMA,
    clean_title,
    extract_footnote_ids,
    extract_ownership_form,
    find_ad_code,
    find_remaining_numbers,
    find_trans_code,
    is_valid_row_security_title,
    iter_clean_table_rows,
)
from edgar_sec.engine.tables.numeric_cells import is_numeric_cell
from edgar_sec.foundation.text.dates import NUMERIC_DATE_RE


def parse_table_ii_rows(
    section: ClassifiedSection | None,
    reference_year: int | None = None,
    holding_only: bool = False,
) -> list[DerivativeTransaction]:
    """Parse Derivative transaction and holding rows from Table II."""
    results: list[DerivativeTransaction] = []
    for row, row_str, footnotes in iter_clean_table_rows(section, "table ii"):
        split_cells = split_row_cells(row)
        if split_cells:
            has_tx = any(TRANSACTION_CODE_RE.search(c) for c in split_cells[1:])
            schema = TABLE_II_TX_SCHEMA if has_tx else TABLE_II_HOLDING_SCHEMA
            aligned = align_row_to_schema(split_cells, schema)
            if aligned is not None and (
                aligned.get("transaction_date")
                or aligned.get("transaction_code")
                or aligned.get("shares_amount")
                or aligned.get("derivative_shares_owned_following")
                or aligned.get("exercisable_date")
                or aligned.get("expiration_date")
            ):
                sec_t = clean_title(aligned.get("security_title") or "")
                if is_valid_row_security_title(sec_t):
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
        security_title = clean_title(raw_title)
        if not is_valid_row_security_title(security_title):
            continue

        direct_or_indirect, nature, form_idx = extract_ownership_form(indexed_cells)

        exercise_price: str | None = None
        price_col_idx = -1
        for idx, (_, cell) in enumerate(indexed_cells[1:5], start=1):
            if "$" in cell or is_numeric_cell(cell):
                exercise_price = extract_schema_number(cell)
                price_col_idx = idx
                break

        trans_code, equity_swap, code_col_idx = find_trans_code(
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
            ad_code = find_ad_code(
                indexed_cells,
                form_idx,
                {price_col_idx, code_col_idx} | date_col_indices,
            )

        underlying_title: str | None = None
        underlying_shares: str | None = None
        underlying_col_indices: set[int] = set()

        for idx, (_, cell) in enumerate(indexed_cells[1:], start=1):
            if form_idx != -1 and idx >= form_idx:
                break
            if idx in (price_col_idx, code_col_idx) or idx in date_col_indices:
                continue
            if "-" in cell:
                parts = [p.strip() for p in cell.rsplit("-", 1)]
                if len(parts) == 2 and is_numeric_cell(parts[1]):
                    cand_title = clean_title(parts[0])
                    if cand_title and is_valid_row_security_title(cand_title):
                        underlying_title = cand_title
                        underlying_shares = extract_schema_number(parts[1])
                        underlying_col_indices.add(idx)
                        break
            elif any(
                k in cell.lower()
                for k in ("common stock", "preferred stock", "class a", "class b")
            ):
                underlying_title = clean_title(cell)
                underlying_col_indices.add(idx)
                if idx + 1 < len(indexed_cells) and is_numeric_cell(
                    indexed_cells[idx + 1][1]
                ):
                    underlying_shares = extract_schema_number(indexed_cells[idx + 1][1])
                    underlying_col_indices.add(idx + 1)
                break

        remaining_nums = find_remaining_numbers(
            indexed_cells,
            form_idx,
            {price_col_idx, code_col_idx} | date_col_indices | underlying_col_indices,
        )

        shares_amount: str | None = None
        following_shares: str | None = None

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
    if holding_only:
        results = [
            row
            for row in results
            if not row.transaction_date
            and not row.transaction_code
            and (
                row.derivative_shares_owned_following is not None
                or row.shares_amount is not None
            )
        ]
    return [
        normalize_row_record(
            row,
            OWNERSHIP_TABLE_II_ROW_SPEC,
            reference_year=reference_year,
        )[0]
        for row in results
    ]
