"""Ownership Table I (Non-Derivative) row extraction."""

from __future__ import annotations

from edgar_sec.engine.forms.common.alignment import align_row_to_schema
from edgar_sec.engine.forms.common.row_extraction import (
    normalize_row_record,
    split_row_cells,
)
from edgar_sec.engine.forms.ownership.row_specs import OWNERSHIP_TABLE_I_ROW_SPEC
from edgar_sec.engine.forms.ownership.sections import ClassifiedSection
from edgar_sec.engine.forms.ownership.table_common import (
    ACQUIRED_DISPOSED_RE,
    TABLE_I_SCHEMA,
    TRANSACTION_CODE_RE,
    NonDerivativeTransaction,
    clean_title,
    extract_footnote_ids,
    extract_ownership_form,
    extract_ownership_number,
    is_footnote_marker,
    is_valid_row_security_title,
    iter_clean_table_rows,
    split_ownership_row_cells,
    strip_footnote_refs,
)
from edgar_sec.engine.tables.numeric_cells import is_numeric_cell
from edgar_sec.foundation.text.dates import NUMERIC_DATE_RE


def parse_table_i_rows(
    section: ClassifiedSection | None,
    reference_year: int | None = None,
    holding_only: bool = False,
) -> list[NonDerivativeTransaction]:
    """Parse Non-Derivative transaction and holding rows from Table I."""
    results: list[NonDerivativeTransaction] = []
    for row, row_str, footnotes in iter_clean_table_rows(section, "table i"):
        split_cells = split_ownership_row_cells(row, frozenset(footnotes))
        aligned = align_row_to_schema(split_cells, TABLE_I_SCHEMA)
        if aligned is not None and (
            aligned.get("transaction_date")
            or aligned.get("transaction_code")
            or aligned.get("shares_amount")
            or aligned.get("shares_owned_following")
        ):
            sec_t = clean_title(aligned.get("security_title") or "")
            if is_valid_row_security_title(sec_t):
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

        footnote_set = frozenset(footnotes)
        indexed_cells = [
            (i, stripped)
            for i, cell in enumerate(row)
            if not is_footnote_marker(cell.strip(), footnote_set)
            and (stripped := strip_footnote_refs(cell))
        ]
        if not indexed_cells:
            continue

        footnotes = list(extract_footnote_ids(row_str))

        raw_title = indexed_cells[0][1]
        security_title = clean_title(raw_title)
        if not is_valid_row_security_title(security_title):
            continue

        direct_or_indirect, nature, form_idx = extract_ownership_form(indexed_cells)

        trans_date: str | None = None
        date_col_idx = -1
        trans_code: str | None = None
        equity_swap = False
        code_col_idx = -1
        ad_code: str | None = None
        shares_amount: str | None = None
        price_per_share: str | None = None
        remaining_nums: list[str] = []

        for idx, (_, cell) in enumerate(indexed_cells[1:], start=1):
            if form_idx != -1 and idx >= form_idx:
                break
            if "|" in cell:
                parts = [p.strip() for p in cell.split("|")]
                if len(parts) >= 1 and parts[0]:
                    shares_amount = extract_ownership_number(parts[0])
                if len(parts) >= 2 and parts[1]:
                    ad_m = ACQUIRED_DISPOSED_RE.search(parts[1])
                    if ad_m:
                        ad_code = ad_m.group(1).upper()
                if len(parts) >= 3 and parts[2]:
                    price_per_share = extract_ownership_number(parts[2])
                continue

            if trans_date is None and (m := NUMERIC_DATE_RE.search(cell)):
                trans_date = m.group(0)
                date_col_idx = idx
                continue

            if (
                trans_code is None
                and idx != date_col_idx
                and (m := TRANSACTION_CODE_RE.search(cell))
            ):
                trans_code = m.group(1).upper()
                equity_swap = bool(m.group(2))
                code_col_idx = idx
                continue

            if ad_code is None and (
                m := ACQUIRED_DISPOSED_RE.fullmatch(cell.strip("() "))
            ):
                ad_code = m.group(1).upper()
                continue

            if price_per_share is None and ("$" in cell or "/sh" in cell.lower()):
                price_per_share = extract_ownership_number(cell)
                continue

            if (
                "|" not in cell
                and "$" not in cell
                and "/sh" not in cell.lower()
                and is_numeric_cell(cell)
            ):
                if (val := extract_ownership_number(cell)) is not None:
                    remaining_nums.append(val)

        shares_owned_following: str | None = None
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
    if holding_only:
        results = [
            row
            for row in results
            if not row.transaction_date
            and not row.transaction_code
            and (
                row.shares_owned_following is not None or row.shares_amount is not None
            )
        ]
    return [
        normalize_row_record(
            row, OWNERSHIP_TABLE_I_ROW_SPEC, reference_year=reference_year
        )[0]
        for row in results
    ]
