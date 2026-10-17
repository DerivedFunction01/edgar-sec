"""Form 144 Table I (Securities to Be Sold) and Table II (Securities Sold) row extraction."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.families.form144.models import (
    TableISecurityItem,
    TableIISecuritySoldItem,
)
from edgar_sec.engine.forms.common.alignment import (
    CanonicalColumn,
    TableSchema,
    align_row_to_schema,
)
from edgar_sec.engine.forms.common.numbers import clean_numeric
from edgar_sec.engine.forms.common.statutory import STATUTORY_PAGE_ARTIFACT_RE
from edgar_sec.engine.forms.common.tables import is_instruction_row
from edgar_sec.engine.forms.form144.sections import ClassifiedSection
from edgar_sec.engine.tables.numeric_cells import is_numeric_cell
from edgar_sec.foundation.text.dates import NUMERIC_DATE_RE

_TABLE_TERMINATORS = (
    "/s/",
    "** signature",
    "signature of person",
    "date of notice",
    "remarks:",
)

_FORM144_INSTRUCTION_TOKEN_SETS = (
    frozenset({"notice", "proposed", "sale", "securities"}),
    frozenset({"pursuant", "rule", "144"}),
    frozenset({"electronic", "format", "edgar"}),
    frozenset({"regulation", "s-t", "hardship"}),
    frozenset({"filer", "contact", "issuer", "obtain", "file", "number"}),
    frozenset({"purchased", "full", "payment", "cash", "consideration"}),
    frozenset({"material", "adverse", "information", "prospective"}),
    frozenset({"intentional", "misstatements", "criminal"}),
    frozenset({"18", "u.s.c", "1001"}),
    frozenset({"omb", "approval"}),
    frozenset({"3235-0101"}),
    frozenset({"burden", "hours"}),
    frozenset({"please", "type", "print"}),
)


def _is_form144_instruction(row_str: str) -> bool:
    low = row_str.lower().strip()
    if not low or low == "*":
        return True
    if is_instruction_row(low) or STATUTORY_PAGE_ARTIFACT_RE.search(low) is not None:
        return True
    tokens = frozenset(re.findall(r"[a-z0-9\(\)]+", low))
    return any(sig.issubset(tokens) for sig in _FORM144_INSTRUCTION_TOKEN_SETS)


def _is_table_i_header(row: tuple[str, ...]) -> bool:
    lower_cells = [c.lower().strip() for c in row if c.strip()]
    if not lower_cells:
        return True
    if any(NUMERIC_DATE_RE.search(c) for c in lower_cells):
        return False
    row_str = " ".join(lower_cells)
    if "table i" in row_str or "securities to be sold" in row_str:
        return True
    header_hits = sum(
        1
        for c in lower_cells
        if any(
            k in c
            for k in (
                "title",
                "class",
                "acquired",
                "nature of acquisition",
                "whom acquired",
                "amount acquired",
                "date of payment",
                "nature of payment",
            )
        )
    )
    return header_hits >= 2


def _is_table_ii_header(row: tuple[str, ...]) -> bool:
    lower_cells = [c.lower().strip() for c in row if c.strip()]
    if not lower_cells:
        return True
    if any(NUMERIC_DATE_RE.search(c) for c in lower_cells):
        return False
    row_str = " ".join(lower_cells)
    if "table ii" in row_str or "sold during the past" in row_str:
        return True
    header_hits = sum(
        1
        for c in lower_cells
        if any(
            k in c
            for k in (
                "name and address",
                "seller",
                "title of securities",
                "date of sale",
                "amount of securities",
                "gross proceeds",
            )
        )
    )
    return header_hits >= 2


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
            data_extractor=clean_numeric,
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
            data_extractor=clean_numeric,
        ),
        CanonicalColumn(
            index=4,
            name="gross_proceeds",
            is_required=False,
            is_anchor=True,
            anchor_validator=lambda s: (
                "$" in s or (is_numeric_cell(s) and clean_numeric(s) is not None)
            ),
            data_extractor=lambda s: (
                float(n) if (n := clean_numeric(s)) is not None else None
            ),
        ),
    ),
)


def parse_table_i_rows(section: ClassifiedSection | None) -> list[TableISecurityItem]:
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

        dates: list[tuple[int, str]] = []
        for idx, cell in enumerate(raw_cells):
            m = NUMERIC_DATE_RE.search(cell)
            if m:
                dates.append((idx, m.group(0)))

        acquired_date = dates[0][1] if dates else None
        payment_date = dates[1][1] if len(dates) > 1 else acquired_date
        date_indices = {d[0] for d in dates}

        amount_val: float | int | None = None
        amount_idx = -1
        for idx, cell in enumerate(raw_cells):
            if idx in date_indices:
                continue
            if is_numeric_cell(cell):
                amount_val = clean_numeric(cell)
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
    return items


def parse_table_ii_rows(
    section: ClassifiedSection | None,
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

        sale_date: str | None = None
        date_idx = -1
        for idx, cell in enumerate(raw_cells):
            m = NUMERIC_DATE_RE.search(cell)
            if m:
                sale_date = m.group(0)
                date_idx = idx
                break

        numeric_items: list[tuple[int, float | int]] = []
        for idx, cell in enumerate(raw_cells):
            if idx == date_idx:
                continue
            if "$" in cell or is_numeric_cell(cell):
                n = clean_numeric(cell)
                if n is not None:
                    numeric_items.append((idx, n))

        num_indices = {n[0] for n in numeric_items}
        amount_sold: float | int | None = None
        gross_proceeds: float | None = None

        if len(numeric_items) >= 2:
            amount_sold = numeric_items[0][1]
            gross_proceeds = float(numeric_items[1][1])
        elif len(numeric_items) == 1:
            amount_sold = numeric_items[0][1]

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
    return nothing_to_report, items


__all__ = [
    "TableISecurityItem",
    "TableIISecuritySoldItem",
    "parse_table_i_rows",
    "parse_table_ii_rows",
]
