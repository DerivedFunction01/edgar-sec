"""Grid table parsing for Form 144 Table I and Table II."""

from __future__ import annotations

from edgar_sec.domain.forms.families.form144.models import (
    TableISecurityItem,
    TableIISecuritySoldItem,
)
from edgar_sec.engine.forms.common.numbers import clean_numeric
from edgar_sec.engine.forms.common.tables import partition_grid_rows
from edgar_sec.engine.forms.form144.sections import ClassifiedSection

_TABLE_I_HEADER_KEYWORDS = frozenset(
    {
        "title",
        "class",
        "date",
        "acquired",
        "nature",
        "acquisition",
        "amount",
        "payment",
        "securities",
    }
)
_TABLE_II_HEADER_KEYWORDS = frozenset(
    {
        "name",
        "address",
        "seller",
        "title",
        "securities",
        "sold",
        "date",
        "sale",
        "amount",
        "gross",
        "proceeds",
    }
)


def _build_table_i_col_map(header_row: tuple[str, ...]) -> dict[str, int]:
    col_map: dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        lower = cell.lower()
        if "title" in lower or "class" in lower:
            col_map.setdefault("class_title", idx)
        elif "date" in lower and "acquired" in lower:
            col_map.setdefault("acquired_date", idx)
        elif "nature" in lower and "acquisition" in lower:
            col_map.setdefault("nature", idx)
        elif "whom" in lower or "donor" in lower or "person" in lower:
            col_map.setdefault("donor_seller", idx)
        elif "amount" in lower:
            col_map.setdefault("amount", idx)
        elif "payment" in lower and "date" in lower:
            col_map.setdefault("payment_date", idx)
        elif "payment" in lower or "consideration" in lower:
            col_map.setdefault("payment_nature", idx)
    return col_map


def _build_table_ii_col_map(header_row: tuple[str, ...]) -> dict[str, int]:
    col_map: dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        lower = cell.lower()
        if "name" in lower and ("seller" in lower or "address" in lower):
            col_map.setdefault("seller", idx)
        elif "title" in lower or "class" in lower:
            col_map.setdefault("class_title", idx)
        elif "date" in lower and "sale" in lower:
            col_map.setdefault("sale_date", idx)
        elif "amount" in lower:
            col_map.setdefault("amount", idx)
        elif "proceeds" in lower or "gross" in lower:
            col_map.setdefault("gross_proceeds", idx)
    return col_map


def parse_table_i_rows(section: ClassifiedSection | None) -> list[TableISecurityItem]:
    """Map acquisition history rows from Table I."""
    if section is None:
        return []

    partition = partition_grid_rows(
        section.resolved_grid, _TABLE_I_HEADER_KEYWORDS, min_header_score=6
    )
    col_map = (
        _build_table_i_col_map(section.resolved_grid.rows[partition.header_index])
        if partition.header_index is not None
        else {}
    )

    items: list[TableISecurityItem] = []
    for row in partition.data_rows:
        if col_map:

            def _get(key: str) -> str | None:
                idx = col_map.get(key)
                if idx is not None and idx < len(row):
                    val = row[idx].strip()
                    return val if val else None
                return None

            class_title = _get("class_title")
            acquired_date = _get("acquired_date")
            nature = _get("nature")
            donor_seller = _get("donor_seller")
            amount = clean_numeric(_get("amount"))
            pay_date = _get("payment_date")
            pay_nature = _get("payment_nature")
        else:
            non_empty = [c.strip() for c in row if c.strip()]
            if len(non_empty) < 2:
                continue
            class_title = non_empty[0] if len(non_empty) > 0 else None
            acquired_date = non_empty[1] if len(non_empty) > 1 else None
            nature = non_empty[2] if len(non_empty) > 2 else None
            donor_seller = non_empty[3] if len(non_empty) > 3 else None
            amount = clean_numeric(non_empty[4]) if len(non_empty) > 4 else None
            pay_date = non_empty[5] if len(non_empty) > 5 else None
            pay_nature = non_empty[6] if len(non_empty) > 6 else None

        if not any((class_title, acquired_date, nature, donor_seller, amount)):
            continue

        items.append(
            TableISecurityItem(
                class_title=class_title,
                acquired_date=acquired_date,
                nature_of_acquisition=nature,
                donor_or_seller_name=donor_seller,
                is_gift=bool(nature and "gift" in nature.lower()),
                amount_acquired=amount,
                payment_date=pay_date,
                nature_of_payment=pay_nature,
            )
        )

    return items


def parse_table_ii_rows(
    section: ClassifiedSection | None,
) -> tuple[bool, list[TableIISecuritySoldItem]]:
    """Map securities sold past 3 months from Table II."""
    if section is None:
        return True, []

    partition = partition_grid_rows(
        section.resolved_grid, _TABLE_II_HEADER_KEYWORDS, min_header_score=5
    )
    col_map = (
        _build_table_ii_col_map(section.resolved_grid.rows[partition.header_index])
        if partition.header_index is not None
        else {}
    )

    items: list[TableIISecuritySoldItem] = []
    for row in partition.data_rows:
        row_str = " ".join(c.strip() for c in row if c.strip())
        lower_row = row_str.lower()
        if "none" in lower_row or "n/a" in lower_row or "no reported" in lower_row:
            return True, []

        if col_map:

            def _get2(key: str) -> str | None:
                idx = col_map.get(key)
                if idx is not None and idx < len(row):
                    val = row[idx].strip()
                    return val if val else None
                return None

            seller = _get2("seller")
            sec_title = _get2("class_title")
            sale_date = _get2("sale_date")
            amount = clean_numeric(_get2("amount"))
            proceeds = (
                float(p)
                if (p := clean_numeric(_get2("gross_proceeds"))) is not None
                else None
            )
        else:
            non_empty = [c.strip() for c in row if c.strip()]
            if len(non_empty) < 2:
                continue
            seller = non_empty[0] if len(non_empty) > 0 else None
            sec_title = non_empty[1] if len(non_empty) > 1 else None
            sale_date = non_empty[2] if len(non_empty) > 2 else None
            amount = clean_numeric(non_empty[3]) if len(non_empty) > 3 else None
            proceeds = (
                float(p)
                if (p := clean_numeric(non_empty[4] if len(non_empty) > 4 else None))
                is not None
                else None
            )

        if not any((seller, sec_title, sale_date, amount, proceeds)):
            continue

        items.append(
            TableIISecuritySoldItem(
                seller_name=seller,
                class_title=sec_title,
                sale_date=sale_date,
                amount_sold=amount,
                gross_proceeds=proceeds,
            )
        )

    nothing_to_report = len(items) == 0
    return nothing_to_report, items


__all__ = [
    "parse_table_i_rows",
    "parse_table_ii_rows",
]
