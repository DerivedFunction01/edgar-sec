"""Form 144 Table I (Securities to Be Sold) and Table II (Securities Sold) row extraction."""

from __future__ import annotations

import re
from dataclasses import replace

from edgar_sec.domain.forms.families.form144.evidence import (
    FORM144_TABLE_I_DECISIVE_PHRASES,
    FORM144_TABLE_I_SUPPORT_TERMS,
    FORM144_TABLE_II_DECISIVE_PHRASES,
    FORM144_TABLE_II_SUPPORT_TERMS,
)
from edgar_sec.domain.forms.families.form144.models import (
    TableISecurityItem,
    TableIISecuritySoldItem,
)
from edgar_sec.engine.forms.common.alignment import (
    CanonicalColumn,
    TableSchema,
    align_row_to_schema,
)
from edgar_sec.engine.forms.common.statutory import STATUTORY_PAGE_ARTIFACT_RE
from edgar_sec.engine.forms.common.tables import is_instruction_row
from edgar_sec.engine.forms.common.numbers import (
    NUMERIC_TOKEN_RE,
    extract_schema_number_or_token,
    normalize_decimal_stripping_currency,
    normalize_integer_stripping_units,
)
from edgar_sec.engine.forms.common.row_extraction import (
    as_integer,
    normalize_row_record,
    scan_date_cells,
    split_row_cells,
)
from edgar_sec.engine.forms.form144.patterns import form144_instruction_matches
from edgar_sec.engine.forms.form144.row_specs import (
    FORM144_TABLE_I_ROW_SPEC,
    FORM144_TABLE_II_ROW_SPEC,
)
from edgar_sec.engine.forms.form144.sections import ClassifiedSection
from edgar_sec.engine.tables.numeric_cells import is_numeric_cell
from edgar_sec.engine.tables.currencies import ALL_CURRENCY_SYMBOLS
from edgar_sec.foundation.text.dates import NUMERIC_DATE_RE, RE_FULL_DATE


def _integer_or_token(text: str) -> int | str | None:
    """Return the policy-conformant integer, or the raw token it rejects."""
    value = normalize_integer_stripping_units(text)
    if value is not None:
        return value
    return extract_schema_number_or_token(text)


_TABLE_TERMINATORS = (
    "/s/",
    "** signature",
    "signature of person",
    "date of notice",
    "remarks:",
)


def _is_form144_instruction(row_str: str) -> bool:
    low = row_str.lower().strip()
    if not low or low == "*":
        return True
    if is_instruction_row(low) or STATUTORY_PAGE_ARTIFACT_RE.search(low) is not None:
        return True
    return form144_instruction_matches(low)


def _is_table_i_header(row: tuple[str, ...]) -> bool:
    lower_cells = [" ".join(c.lower().split()) for c in row if c.strip()]
    if not lower_cells:
        return True
    if any(NUMERIC_DATE_RE.search(c) or RE_FULL_DATE.search(c) for c in lower_cells):
        return False
    row_str = " ".join(lower_cells)
    if "table i" in row_str or "securities to be sold" in row_str:
        return True
    decisive_hits = sum(
        1 for c in lower_cells if any(k in c for k in FORM144_TABLE_I_DECISIVE_PHRASES)
    )
    if decisive_hits >= 2:
        return True
    if not all(len(c) <= 40 for c in lower_cells):
        return False
    support_hits = sum(
        1 for c in lower_cells if any(k in c for k in FORM144_TABLE_I_SUPPORT_TERMS)
    )
    return support_hits >= 2 or (decisive_hits >= 1 and support_hits >= 1)


def _is_table_ii_header(row: tuple[str, ...]) -> bool:
    lower_cells = [" ".join(c.lower().split()) for c in row if c.strip()]
    if not lower_cells:
        return True
    if any(NUMERIC_DATE_RE.search(c) or RE_FULL_DATE.search(c) for c in lower_cells):
        return False
    row_str = " ".join(lower_cells)
    if "table ii" in row_str or "sold during the past" in row_str:
        return True
    decisive_hits = sum(
        1 for c in lower_cells if any(k in c for k in FORM144_TABLE_II_DECISIVE_PHRASES)
    )
    if decisive_hits >= 2:
        return True
    if not all(len(c) <= 40 for c in lower_cells):
        return False
    support_hits = sum(
        1 for c in lower_cells if any(k in c for k in FORM144_TABLE_II_SUPPORT_TERMS)
    )
    return support_hits >= 2 or (decisive_hits >= 1 and support_hits >= 1)


_TABLE_I_SCHEMA = TableSchema(
    name="form144_table_i",
    columns=(
        CanonicalColumn(index=0, name="class_title", is_required=True),
        CanonicalColumn(
            index=1,
            name="acquired_date",
            is_required=True,
            is_anchor=True,
            anchor_validator=lambda s: bool(NUMERIC_DATE_RE.search(s)),
            data_extractor=lambda s: (
                m.group(0) if (m := NUMERIC_DATE_RE.search(s)) else None
            ),
        ),
        CanonicalColumn(index=2, name="nature_of_acquisition", is_required=True),
        CanonicalColumn(index=3, name="donor_or_seller_name", is_required=False),
        CanonicalColumn(
            index=4,
            name="amount_acquired",
            is_required=True,
            data_extractor=_integer_or_token,
        ),
        CanonicalColumn(
            index=5,
            name="payment_date",
            is_required=False,
            is_anchor=True,
            anchor_validator=lambda s: bool(NUMERIC_DATE_RE.search(s)),
            data_extractor=lambda s: (
                m.group(0) if (m := NUMERIC_DATE_RE.search(s)) else None
            ),
        ),
        CanonicalColumn(index=6, name="nature_of_payment", is_required=False),
    ),
)

_TABLE_II_SCHEMA = TableSchema(
    name="form144_table_ii",
    columns=(
        CanonicalColumn(index=0, name="seller_name", is_required=True),
        CanonicalColumn(index=1, name="class_title", is_required=True),
        CanonicalColumn(
            index=2,
            name="sale_date",
            is_required=True,
            is_anchor=True,
            anchor_validator=lambda s: bool(NUMERIC_DATE_RE.search(s)),
            data_extractor=lambda s: (
                m.group(0) if (m := NUMERIC_DATE_RE.search(s)) else None
            ),
        ),
        CanonicalColumn(
            index=3,
            name="amount_sold",
            is_required=True,
            data_extractor=_integer_or_token,
        ),
        CanonicalColumn(
            index=4,
            name="gross_proceeds",
            is_required=False,
            is_anchor=True,
            anchor_validator=lambda s: (
                normalize_decimal_stripping_currency(s) is not None
            ),
            data_extractor=normalize_decimal_stripping_currency,
        ),
    ),
)


def parse_table_i_rows(
    section: ClassifiedSection | None,
    reference_year: int | None = None,
) -> list[TableISecurityItem]:
    """Map acquisition history rows from Table I."""
    if section is None or len(section.resolved_grid.rows) <= 1:
        return []

    items: list[TableISecurityItem] = []
    for row in section.resolved_grid.rows:
        raw_cells = [c.strip() for c in row if c.strip()]
        if not raw_cells:
            continue

        row_str = " ".join(raw_cells)
        row_lower = row_str.lower()

        if any(term in row_lower for term in _TABLE_TERMINATORS):
            break

        if _is_form144_instruction(row_str) or _is_table_i_header(row):
            continue

        aligned = align_row_to_schema(tuple(raw_cells), _TABLE_I_SCHEMA)
        if aligned is not None:
            acq_d = aligned.get("acquired_date")
            pay_d = aligned.get("payment_date") or acq_d
            items.append(
                TableISecurityItem(
                    class_title=aligned.get("class_title"),
                    acquired_date=acq_d,
                    nature_of_acquisition=aligned.get("nature_of_acquisition"),
                    donor_or_seller_name=aligned.get("donor_or_seller_name"),
                    is_gift=bool(
                        (nat := aligned.get("nature_of_acquisition"))
                        and "gift" in str(nat).lower()
                    ),
                    amount_acquired=aligned.get("amount_acquired"),
                    payment_date=pay_d,
                    nature_of_payment=aligned.get("nature_of_payment"),
                )
            )
            continue

        dates = list(scan_date_cells(raw_cells))

        acquired_date = dates[0][1] if dates else None
        payment_date = dates[1][1] if len(dates) > 1 else acquired_date
        date_indices = {d[0] for d in dates}

        amount_val: int | None = None
        amount_idx = -1
        for idx, cell in enumerate(raw_cells):
            if idx in date_indices:
                continue
            if is_numeric_cell(cell):
                amount_val = normalize_integer_stripping_units(cell)
                if amount_val is not None:
                    amount_idx = idx
                    break

        text_cells = [
            cell
            for idx, cell in enumerate(raw_cells)
            if idx not in date_indices and idx != amount_idx
        ]

        class_title = text_cells[0] if len(text_cells) > 0 else None
        nature = text_cells[1] if len(text_cells) > 1 else None
        donor_seller = text_cells[2] if len(text_cells) > 2 else None
        pay_nature = text_cells[3] if len(text_cells) > 3 else None

        if not any((class_title, acquired_date, nature, donor_seller, amount_val)):
            continue

        items.append(
            TableISecurityItem(
                class_title=class_title,
                acquired_date=acquired_date,
                nature_of_acquisition=nature,
                donor_or_seller_name=donor_seller,
                is_gift=bool(nature and "gift" in nature.lower()),
                amount_acquired=amount_val,
                payment_date=payment_date,
                nature_of_payment=pay_nature,
            )
        )
    normalized_items = [
        normalize_row_record(
            item,
            FORM144_TABLE_I_ROW_SPEC,
            reference_year=reference_year,
        )[0]
        for item in items
    ]
    return [
        replace(item, amount_acquired=as_integer(item.amount_acquired))
        for item in normalized_items
    ]


def _split_seller_name_address(
    item: TableIISecuritySoldItem,
) -> TableIISecuritySoldItem:
    name = item.seller_name
    if not name or "\n" not in name:
        return item
    lines = [line.strip() for line in name.splitlines() if line.strip()]
    if len(lines) < 2 or NUMERIC_TOKEN_RE.match(lines[0]):
        return item
    return replace(item, seller_name=lines[0], seller_address=", ".join(lines[1:]))


def parse_table_ii_rows(
    section: ClassifiedSection | None,
    reference_year: int | None = None,
) -> tuple[bool, list[TableIISecuritySoldItem]]:
    """Map securities sold past 3 months from Table II."""
    if section is None or len(section.resolved_grid.rows) <= 1:
        return True, []

    items: list[TableIISecuritySoldItem] = []
    for row in section.resolved_grid.rows:
        raw_cells = [c.strip() for c in row if c.strip()]
        if not raw_cells:
            continue

        row_str = " ".join(raw_cells)
        row_lower = row_str.lower()

        if any(
            term in row_lower
            for term in ("none", "n/a", "no reported", "nothing to report")
        ):
            return True, []

        if any(term in row_lower for term in _TABLE_TERMINATORS):
            break

        if _is_form144_instruction(row_str) or _is_table_ii_header(row):
            continue

        aligned = align_row_to_schema(tuple(raw_cells), _TABLE_II_SCHEMA)
        if aligned is not None:
            items.append(
                TableIISecuritySoldItem(
                    seller_name=aligned.get("seller_name"),
                    class_title=aligned.get("class_title"),
                    sale_date=aligned.get("sale_date"),
                    amount_sold=aligned.get("amount_sold"),
                    gross_proceeds=aligned.get("gross_proceeds"),
                )
            )
            continue

        scanned_dates = scan_date_cells(raw_cells)
        sale_date = scanned_dates[0][1] if scanned_dates else None
        date_idx = scanned_dates[0][0] if scanned_dates else -1

        numeric_items: list[tuple[int, int | str, str, bool]] = []
        for idx, cell in enumerate(raw_cells):
            if idx == date_idx:
                continue
            has_currency = any(symbol in cell for symbol in ALL_CURRENCY_SYMBOLS)
            if has_currency:
                number = normalize_decimal_stripping_currency(cell)
                if number is not None:
                    numeric_items.append((idx, number, cell, True))
                continue
            integer = normalize_integer_stripping_units(cell)
            if integer is not None:
                numeric_items.append((idx, integer, cell, False))
            elif is_numeric_cell(cell) and (
                decimal := normalize_decimal_stripping_currency(cell)
            ):
                numeric_items.append((idx, decimal, cell, True))

        num_indices = {n[0] for n in numeric_items}
        amount_sold: int | None = None
        gross_proceeds: str | None = None

        amount_item = next((item for item in numeric_items if not item[3]), None)
        proceeds_item = next((item for item in numeric_items if item[3]), None)
        if amount_item is not None:
            amount_sold = int(amount_item[1])
        if proceeds_item is not None:
            gross_proceeds = str(proceeds_item[1])
        if proceeds_item is None and amount_item is not None and len(numeric_items) > 1:
            next_item = next(
                (item for item in numeric_items if item is not amount_item), None
            )
            if next_item is not None:
                gross_proceeds = normalize_decimal_stripping_currency(next_item[2])

        text_cells = [
            cell
            for idx, cell in enumerate(raw_cells)
            if idx != date_idx and idx not in num_indices
        ]

        seller = text_cells[0] if len(text_cells) > 0 else None
        sec_title = text_cells[1] if len(text_cells) > 1 else None

        if not any((seller, sec_title, sale_date, amount_sold, gross_proceeds)):
            continue

        items.append(
            TableIISecuritySoldItem(
                seller_name=seller,
                class_title=sec_title,
                sale_date=sale_date,
                amount_sold=amount_sold,
                gross_proceeds=gross_proceeds,
            )
        )

    nothing_to_report = len(items) == 0
    normalized_items = [
        normalize_row_record(
            _split_seller_name_address(item),
            FORM144_TABLE_II_ROW_SPEC,
            reference_year=reference_year,
        )[0]
        for item in items
    ]
    return nothing_to_report, [
        replace(item, amount_sold=as_integer(item.amount_sold))
        for item in normalized_items
    ]


__all__ = [
    "TableISecurityItem",
    "TableIISecuritySoldItem",
    "parse_table_i_rows",
    "parse_table_ii_rows",
]
