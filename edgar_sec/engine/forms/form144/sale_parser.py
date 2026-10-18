"""Extraction of proposed sale details from Form 144 Box 3."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.families.form144.models import (
    BrokerDetails,
    ProposedSaleItem,
)
from edgar_sec.engine.forms.common.alignment import (
    CanonicalColumn,
    TableSchema,
    align_row_to_schema,
)
from edgar_sec.engine.forms.common.entities import (
    STATE_ZIP_RE,
    STREET_SUFFIX_RE,
    normalize_exchange_name,
)
from edgar_sec.engine.forms.common.numbers import clean_numeric
from edgar_sec.engine.forms.common.tables import is_instruction_row
from edgar_sec.engine.forms.form144.patterns import NUMERIC_TOKEN_RE
from edgar_sec.engine.forms.form144.sections import ClassifiedSection
from edgar_sec.engine.tables.currencies import ALL_CURRENCY_SYMBOLS
from edgar_sec.foundation.text.dates import parse_date

_SEC_FILE_RE = re.compile(r"^\d{1,3}-\d{4,7}$")
_SPLIT_EXPLANATION_RE = re.compile(
    r"\s+(?:as of|based on|\(based|\(as of)\b", flags=re.IGNORECASE
)


def _is_box3_header(row: tuple[str, ...]) -> bool:
    text = " ".join(" ".join(cell.split()) for cell in row if cell.strip()).lower()
    if any(
        marker in text
        for marker in (
            "name of issuer",
            "person for whose account",
            "table i",
            "table ii",
            "date of notice",
            "(signature)",
        )
    ):
        return False
    if any(m in text for m in ("(e)", "(f)", "(g)")) and not any(
        c.isdigit() for c in text
    ):
        return True
    return any(
        k in text
        for k in (
            "3(a)",
            "3 (a)",
            "title of the class",
            "to be sold",
            "aggregate market value",
            "approximate",
            "securities exchange",
            "number of shares",
        )
    )


def _split_broker_street_city(address: str) -> tuple[str | None, str | None]:
    if not NUMERIC_TOKEN_RE.match(address):
        return None, None
    suffixes = list(STREET_SUFFIX_RE.finditer(address))
    if not suffixes:
        return None, None
    suffix = suffixes[-1]
    street = address[: suffix.end()].strip(" ,")
    city = address[suffix.end() :].strip(" ,")
    return (street, city) if city else (None, None)


def _parse_broker(lines: list[str]) -> BrokerDetails | None:
    flattened = [l.strip() for part in lines for l in part.splitlines() if l.strip()]
    if not flattened:
        return None
    name = flattened[0]
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None

    if len(flattened) > 1:
        address_lines = flattened[1:]
        state_zip = STATE_ZIP_RE.search(address_lines[-1])
        if state_zip:
            city_text = address_lines[-1][: state_zip.start()].strip(" ,")
            street, city = _split_broker_street_city(city_text)
            city = city or city_text
            state = state_zip.group(1)
            zip_code = state_zip.group(2)
            street = street or (
                " ".join(address_lines[:-1]) if len(address_lines) > 1 else None
            )
        else:
            street = " ".join(address_lines)
    else:
        state_zip = STATE_ZIP_RE.search(name)
        if state_zip:
            state = state_zip.group(1)
            zip_code = state_zip.group(2)
            street = name[: state_zip.start()].strip()

    return BrokerDetails(
        name=name,
        street1=street,
        city=city,
        state_or_country=state,
        zip_code=zip_code,
    )


def _extract_leading_number(text: str) -> tuple[float | int | None, bool]:
    cleaned = text.strip()
    if not cleaned:
        return None, False
    if STREET_SUFFIX_RE.search(cleaned) or STATE_ZIP_RE.search(cleaned):
        return None, False
    has_curr = any(s in cleaned for s in ALL_CURRENCY_SYMBOLS)
    primary = _SPLIT_EXPLANATION_RE.split(cleaned)[0].strip()
    num = clean_numeric(primary)
    return (num, has_curr) if num is not None else (None, False)


def _is_currency_cell(s: str) -> bool:
    num, is_curr = _extract_leading_number(s)
    return is_curr and num is not None


def _is_date_cell(s: str) -> bool:
    return parse_date(s) is not None if "as of" not in s.lower() else False


def _is_exchange_cell(s: str) -> bool:
    return normalize_exchange_name(s) is not None


_BOX_3_SCHEMA = TableSchema(
    name="form144_box3",
    columns=(
        CanonicalColumn(index=0, name="class_title", is_required=False),
        CanonicalColumn(index=1, name="broker", is_required=False),
        CanonicalColumn(
            index=2,
            name="units_to_be_sold",
            is_required=False,
            data_extractor=lambda s: _extract_leading_number(s)[0],
        ),
        CanonicalColumn(
            index=3,
            name="aggregate_market_value",
            is_required=False,
            is_anchor=True,
            anchor_validator=_is_currency_cell,
            data_extractor=lambda s: (
                float(n) if (n := _extract_leading_number(s)[0]) is not None else None
            ),
        ),
        CanonicalColumn(
            index=4,
            name="units_outstanding",
            is_required=False,
            data_extractor=lambda s: _extract_leading_number(s)[0],
        ),
        CanonicalColumn(
            index=5,
            name="approx_sale_date",
            is_required=False,
            is_anchor=True,
            anchor_validator=_is_date_cell,
            data_extractor=lambda s: d.display if (d := parse_date(s)) else None,
        ),
        CanonicalColumn(
            index=6,
            name="exchange_name",
            is_required=False,
            is_anchor=True,
            anchor_validator=_is_exchange_cell,
            data_extractor=normalize_exchange_name,
        ),
    ),
)


_BOX_3_PART2_SCHEMA = TableSchema(
    name="form144_box3_part2",
    columns=(
        CanonicalColumn(
            index=0,
            name="units_outstanding",
            is_required=False,
            data_extractor=lambda s: _extract_leading_number(s)[0],
        ),
        CanonicalColumn(
            index=1,
            name="approx_sale_date",
            is_required=False,
            is_anchor=True,
            anchor_validator=_is_date_cell,
            data_extractor=lambda s: d.display if (d := parse_date(s)) else None,
        ),
        CanonicalColumn(
            index=2,
            name="exchange_name",
            is_required=False,
            is_anchor=True,
            anchor_validator=_is_exchange_cell,
            data_extractor=normalize_exchange_name,
        ),
    ),
)


def parse_proposed_sale_box_3(section: ClassifiedSection | None) -> ProposedSaleItem:
    """Extract proposed sale fields from Box 3 section grid using a state machine."""
    if section is None:
        return ProposedSaleItem()

    rows = section.resolved_grid.rows
    if not rows:
        return ProposedSaleItem()

    first_hdr = next((idx for idx, r in enumerate(rows) if _is_box3_header(r)), 0)

    class_title: str | None = None
    units: float | int | None = None
    val: float | None = None
    out: float | int | None = None
    dt: str | None = None
    exch: str | None = None
    broker_parts: list[str] = []

    for row in rows[first_hdr + 1 :]:
        raw_cells = [c.strip() for c in row if c.strip()]
        if not raw_cells:
            continue
        row_str = " ".join(raw_cells)
        if _is_box3_header(row) or is_instruction_row(row_str):
            continue

        cells: list[str] = []
        skip_next = False
        for i, c in enumerate(raw_cells):
            if skip_next:
                skip_next = False
                continue
            if c in ALL_CURRENCY_SYMBOLS and i + 1 < len(raw_cells):
                cells.append(c + raw_cells[i + 1])
                skip_next = True
            else:
                cells.append(c)

        rem_cells = [c for c in cells if not _SEC_FILE_RE.match(c)]

        has_curr = any(_is_currency_cell(c) for c in rem_cells)
        has_dt_or_exch = any(
            _is_date_cell(c) or _is_exchange_cell(c) for c in rem_cells
        )
        schema = (
            _BOX_3_PART2_SCHEMA
            if has_dt_or_exch and not has_curr and len(rem_cells) <= 4
            else _BOX_3_SCHEMA
        )
        aligned = align_row_to_schema(tuple(rem_cells), schema)
        if aligned is not None and (
            aligned.get("aggregate_market_value") is not None
            or aligned.get("approx_sale_date") is not None
            or aligned.get("exchange_name") is not None
        ):
            if class_title is None and aligned.get("class_title"):
                class_title = " ".join(aligned["class_title"].split())
            if not broker_parts and aligned.get("broker"):
                broker_parts.append(aligned["broker"])
            if units is None and aligned.get("units_to_be_sold") is not None:
                units = aligned["units_to_be_sold"]
            if val is None and aligned.get("aggregate_market_value") is not None:
                val = aligned["aggregate_market_value"]
            if out is None and aligned.get("units_outstanding") is not None:
                out = aligned["units_outstanding"]
            if dt is None and aligned.get("approx_sale_date") is not None:
                dt = aligned["approx_sale_date"]
            if exch is None and aligned.get("exchange_name") is not None:
                exch = aligned["exchange_name"]
            continue

        if exch is None:
            for idx in range(len(rem_cells) - 1, -1, -1):
                match_exch = normalize_exchange_name(rem_cells[idx])
                if match_exch:
                    exch = match_exch
                    rem_cells.pop(idx)
                    break

        if dt is None:
            for idx in range(len(rem_cells) - 1, -1, -1):
                cell_val = rem_cells[idx]
                if "as of" in cell_val.lower():
                    continue
                match_dt = parse_date(cell_val)
                if match_dt:
                    dt = match_dt.display
                    rem_cells.pop(idx)
                    break

        numeric_items: list[tuple[float | int, bool, str]] = []
        text_items: list[str] = []
        for c in rem_cells:
            num, is_curr = _extract_leading_number(c)
            if num is not None:
                numeric_items.append((num, is_curr, c))
            else:
                text_items.append(c)

        if len(numeric_items) >= 3:
            units = units if units is not None else numeric_items[0][0]
            val = val if val is not None else float(numeric_items[1][0])
            out = out if out is not None else numeric_items[2][0]
        elif len(numeric_items) == 2:
            n1, _, _ = numeric_items[0]
            n2, is_curr2, _ = numeric_items[1]
            units = units if units is not None else n1
            if is_curr2:
                val = val if val is not None else float(n2)
            elif n2 > n1 * 5:
                out = out if out is not None else n2
            else:
                val = val if val is not None else float(n2)
        elif len(numeric_items) == 1:
            if units is None:
                units = numeric_items[0][0]
            elif val is None and numeric_items[0][1]:
                val = float(numeric_items[0][0])
            elif out is None:
                out = numeric_items[0][0]

        for t in text_items:
            lower = t.lower()
            if any(
                phrase in lower
                for phrase in (
                    "market value",
                    "date of sale",
                    "closing price",
                    "to be determined",
                )
            ):
                continue
            if class_title is None and (
                any(
                    w in lower
                    for w in (
                        "common",
                        "class",
                        "preferred",
                        "stock",
                        "ordinary",
                        "share",
                        "par",
                    )
                )
                or (len(text_items) >= 2 and t == text_items[0])
            ):
                class_title = " ".join(t.split())
            elif "name and address" not in lower:
                broker_parts.append(t)

        if exch is None:
            exch = normalize_exchange_name(" ".join(row))

    broker = _parse_broker(broker_parts) if broker_parts else None

    return ProposedSaleItem(
        class_title=class_title,
        broker=broker,
        units_to_be_sold=units,
        aggregate_market_value=val,
        units_outstanding=out,
        approx_sale_date=dt,
        exchange_name=exch,
    )


__all__ = ["clean_numeric", "parse_proposed_sale_box_3"]
