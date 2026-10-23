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
from edgar_sec.engine.forms.common.dates import normalize_iso_date
from edgar_sec.engine.forms.common.entities import (
    STATE_ZIP_RE,
    STREET_SUFFIX_RE,
    normalize_exchange_name,
)
from edgar_sec.engine.forms.common.tables import is_instruction_row, split_street_city
from edgar_sec.engine.forms.common.numbers import (
    format_scaled_number_string,
    normalize_decimal_stripping_currency,
    normalize_integer_stripping_units,
)
from edgar_sec.engine.forms.form144.patterns import SEC_FILE_BARE_RE
from edgar_sec.engine.forms.form144.sections import ClassifiedSection
from edgar_sec.engine.tables.currencies import ALL_CURRENCY_SYMBOLS
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import parse_date

_SPLIT_EXPLANATION_RE = re.compile(
    r"(?:\s+(?:as of|based on)\b|(?:\s+|(?<=\d))\((?:based on|as of)\b)",
    flags=re.IGNORECASE,
)
_CURRENCY_CODE_ALT = build_alternation(
    tuple(re.escape(code) for code in ("U.S.$", "US $", "US$", "USD"))
)
_CURRENCY_CODE_PREFIX_RE = re.compile(rf"^(?:{_CURRENCY_CODE_ALT})\s*", re.I)
_APPROX_TILDE_RE = re.compile(r"^~+\s*")
_TRAILING_COMMA_RE = re.compile(r",\s*$")
_CURRENCY_AMOUNT_RE = re.compile(r"\$\s*\d[\d,]*(?:\.\d+)?")


def _preclean_money(primary: str) -> str:
    """Strip approximation tildes and currency-code prefixes."""
    text = _APPROX_TILDE_RE.sub("", primary.strip())
    text = _CURRENCY_CODE_PREFIX_RE.sub("", text)
    return _APPROX_TILDE_RE.sub("", text).strip()


_FOOTNOTE_SUFFIX_RE = re.compile(r"\s*\(\d{1,2}\)\s*$")
_QUANTITY_PREFIX_ALT = build_alternation(
    ("up to", "approximately", "approximate", "approx", "about")
)
_QUANTITY_PREFIX_RE = re.compile(rf"^(?:{_QUANTITY_PREFIX_ALT})\.?\s+", re.I)
_MAGNITUDE_ALT = build_alternation(
    (
        "mm",
        "million",
        "millions",
        "billion",
        "billions",
        "thousand",
        "thousands",
        "m",
        "k",
        "b",
    )
)
_MAGNITUDE_TOKEN_RE = re.compile(rf"(?:{_MAGNITUDE_ALT})\b", re.IGNORECASE)


def _normalize_number(primary: str, *, currency: bool) -> int | str | None:
    """Strict schema normalization, falling back to magnitude scaling."""
    strict = (
        normalize_decimal_stripping_currency(primary)
        if currency
        else normalize_integer_stripping_units(primary)
    )
    if strict is not None:
        return strict
    if _MAGNITUDE_TOKEN_RE.search(primary):
        scaled = format_scaled_number_string(primary)
        if scaled is not None and not currency:
            return int(scaled) if "." not in scaled else None
        return scaled
    return None


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
    return split_street_city(address)


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


def _extract_leading_number(text: str) -> tuple[int | str | None, bool]:
    cleaned = text.strip()
    if not cleaned:
        return None, False
    if STREET_SUFFIX_RE.search(cleaned) or STATE_ZIP_RE.search(cleaned):
        return None, False
    has_curr = any(s in cleaned for s in ALL_CURRENCY_SYMBOLS)
    primary = _SPLIT_EXPLANATION_RE.split(cleaned)[0].strip()
    primary = _QUANTITY_PREFIX_RE.sub("", _preclean_money(primary))
    primary = _TRAILING_COMMA_RE.sub("", _FOOTNOTE_SUFFIX_RE.sub("", primary))
    num = _normalize_number(primary, currency=has_curr)
    if num is None and "\n" in primary:
        first_line = _QUANTITY_PREFIX_RE.sub("", primary.splitlines()[0].strip())
        num = _normalize_number(first_line, currency=has_curr)
    return (num, has_curr) if num is not None else (None, False)


def _extract_units(text: str) -> int | None:
    value, is_currency = _extract_leading_number(text)
    return value if isinstance(value, int) and not is_currency else None


def _extract_market_value(text: str) -> str | None:
    cleaned = text.strip().lstrip("*").strip()
    if not cleaned:
        return None
    if STREET_SUFFIX_RE.search(cleaned) or STATE_ZIP_RE.search(cleaned):
        return None
    primary = _SPLIT_EXPLANATION_RE.split(cleaned)[0].strip()
    primary = _QUANTITY_PREFIX_RE.sub("", _FOOTNOTE_SUFFIX_RE.sub("", primary))
    primary = _TRAILING_COMMA_RE.sub("", _preclean_money(primary))
    value = _normalize_number(primary.strip(), currency=True)
    if value is None and "\n" in primary:
        first_line = _FOOTNOTE_SUFFIX_RE.sub("", primary.splitlines()[0].strip())
        value = _normalize_number(first_line.strip(), currency=True)
    if value is None and " " in primary and not _MAGNITUDE_TOKEN_RE.search(primary):
        value = _normalize_number(primary.split()[0], currency=True)
    if value is None and not cleaned[0].isdigit() and cleaned[0] != "$":
        amounts = _CURRENCY_AMOUNT_RE.findall(cleaned)
        if len(amounts) == 1:
            value = _normalize_number(amounts[0], currency=True)
    return value if isinstance(value, str) else None


def _value_without_trailing_date(cell: str) -> str:
    text = cell.strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 2 and parse_date(lines[-1]) is not None:
        head = "\n".join(lines[:-1])
        num, _is_curr = _extract_leading_number(head)
        if num is not None:
            return head
    head, sep, tail = text.rpartition(" ")
    if sep and parse_date(tail) is not None:
        num, _is_curr = _extract_leading_number(head)
        if num is not None:
            return head
    return cell


def _is_currency_cell(s: str) -> bool:
    num, is_curr = _extract_leading_number(s)
    return is_curr and num is not None


def _is_date_cell(s: str, reference_year: int | None = None) -> bool:
    if "as of" in s.lower():
        return False
    return parse_date(s, reference_year=reference_year) is not None


def _date_display(s: str, reference_year: int | None = None) -> str | None:
    parsed = parse_date(s, reference_year=reference_year)
    return parsed.display if parsed is not None else None


def _is_exchange_cell(s: str) -> bool:
    return normalize_exchange_name(s) is not None


def _box3_schema(reference_year: int | None) -> TableSchema:
    return TableSchema(
        name="form144_box3",
        columns=(
            CanonicalColumn(index=0, name="class_title", is_required=False),
            CanonicalColumn(index=1, name="broker", is_required=False),
            CanonicalColumn(
                index=2,
                name="units_to_be_sold",
                is_required=False,
                data_extractor=_extract_units,
            ),
            CanonicalColumn(
                index=3,
                name="aggregate_market_value",
                is_required=False,
                is_anchor=True,
                anchor_validator=_is_currency_cell,
                data_extractor=_extract_market_value,
            ),
            CanonicalColumn(
                index=4,
                name="units_outstanding",
                is_required=False,
                data_extractor=_extract_units,
            ),
            CanonicalColumn(
                index=5,
                name="approx_sale_date",
                is_required=False,
                is_anchor=True,
                anchor_validator=lambda s: _is_date_cell(s, reference_year),
                data_extractor=lambda s: _date_display(s, reference_year),
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


def _box3_part2_schema(reference_year: int | None) -> TableSchema:
    return TableSchema(
        name="form144_box3_part2",
        columns=(
            CanonicalColumn(
                index=0,
                name="units_outstanding",
                is_required=False,
                data_extractor=_extract_units,
            ),
            CanonicalColumn(
                index=1,
                name="approx_sale_date",
                is_required=False,
                is_anchor=True,
                anchor_validator=lambda s: _is_date_cell(s, reference_year),
                data_extractor=lambda s: _date_display(s, reference_year),
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


_TAB_GLUE_RE = re.compile(r"&#9;|\t")


def _split_tab_glued(cell: str) -> tuple[str, ...]:
    """Split a cell whose fields are glued together with tab characters."""
    if "&#9;" not in cell and "\t" not in cell:
        return (cell,)
    parts = tuple(_TAB_GLUE_RE.split(cell))
    if sum(1 for part in parts if part.strip()) < 2:
        return (cell,)
    return parts


def parse_proposed_sale_box_3(
    section: ClassifiedSection | None,
    reference_year: int | None = None,
) -> ProposedSaleItem:
    """Extract proposed sale fields from Box 3 section grid using a state machine."""
    if section is None:
        return ProposedSaleItem()

    rows = tuple(
        tuple(part for cell in row for part in _split_tab_glued(cell))
        for row in section.resolved_grid.rows
    )
    if not rows:
        return ProposedSaleItem()

    first_hdr = next((idx for idx, r in enumerate(rows) if _is_box3_header(r)), 0)

    class_title: str | None = None
    units: int | None = None
    val: str | None = None
    out: int | None = None
    dt: str | None = None
    exch: str | None = None
    broker_parts: list[str] = []

    for row in rows[first_hdr + 1 :]:
        if section.raw_node is None and len(row) == 7:
            r_class, r_broker, r_units, r_val, r_out, r_dt, r_exch = row
            if r_class and class_title is None:
                class_title = r_class
            if r_broker and not broker_parts:
                broker_parts.append(r_broker)
            if r_units and units is None:
                units = normalize_integer_stripping_units(r_units)
            if r_val and val is None:
                val = _extract_market_value(r_val)
            if r_out and out is None:
                out = normalize_integer_stripping_units(r_out)
            if r_dt and dt is None:
                parsed_dt = parse_date(r_dt, reference_year=reference_year)
                dt = parsed_dt.display if parsed_dt else None
            if r_exch and exch is None:
                exch = normalize_exchange_name(r_exch)
            continue

        raw_cells = [c.strip() for c in row if c.strip()]
        if not raw_cells:
            continue
        row_str = " ".join(raw_cells)
        if _is_box3_header(row) or is_instruction_row(row_str):
            has_anchor = any(
                (
                    _is_currency_cell(c)
                    or _is_date_cell(c, reference_year)
                    or _is_exchange_cell(c)
                )
                for c in raw_cells
                if "see instr" not in c.lower()
            )
            if not has_anchor:
                continue

        cells: list[str] = []
        skip_next = False
        for i, raw_c in enumerate(raw_cells):
            c = _value_without_trailing_date(raw_c)
            if skip_next:
                skip_next = False
                continue
            if c in ALL_CURRENCY_SYMBOLS and i + 1 < len(raw_cells):
                cells.append(c + raw_cells[i + 1])
                skip_next = True
            else:
                cells.append(c)

        rem_cells = [c for c in cells if not SEC_FILE_BARE_RE.fullmatch(c)]

        has_curr = any(_is_currency_cell(c) for c in rem_cells)
        has_dt_or_exch = any(
            _is_date_cell(c, reference_year) or _is_exchange_cell(c) for c in rem_cells
        )
        schema = (
            _box3_part2_schema(reference_year)
            if has_dt_or_exch and not has_curr and len(rem_cells) <= 4
            else _box3_schema(reference_year)
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
                match_dt = parse_date(cell_val, reference_year=reference_year)
                if match_dt:
                    dt = match_dt.display
                    rem_cells.pop(idx)
                    break

        numeric_items: list[tuple[int | str, bool, str]] = []
        text_items: list[str] = []
        for c in rem_cells:
            num, is_curr = _extract_leading_number(c)
            if num is not None:
                numeric_items.append((num, is_curr, c))
            else:
                text_items.append(c)

        if len(numeric_items) >= 3:
            integer_items = [item for item in numeric_items if not item[1]]
            if integer_items:
                units = units if units is not None else int(integer_items[0][0])
                if len(integer_items) > 1:
                    out = out if out is not None else int(integer_items[-1][0])
            proceeds = next((item for item in numeric_items if item[1]), None)
            if proceeds is None:
                proceeds = numeric_items[1]
            val = val if val is not None else _extract_market_value(proceeds[2])
        elif len(numeric_items) == 2:
            n1, is_curr1, _ = numeric_items[0]
            n2, is_curr2, _ = numeric_items[1]
            units = units if units is not None else (int(n1) if not is_curr1 else None)
            if is_curr2:
                val = (
                    val
                    if val is not None
                    else _extract_market_value(numeric_items[1][2])
                )
            elif is_curr1:
                val = (
                    val
                    if val is not None
                    else _extract_market_value(numeric_items[0][2])
                )
                if units is None:
                    units = int(n2)
            elif not is_curr2 and not is_curr1 and int(n2) > int(n1) * 5:
                out = out if out is not None else int(n2)
            else:
                val = (
                    val
                    if val is not None
                    else _extract_market_value(numeric_items[1][2])
                )
        elif len(numeric_items) == 1:
            if units is None and not numeric_items[0][1]:
                units = int(numeric_items[0][0])
            elif val is None and numeric_items[0][1]:
                val = _extract_market_value(numeric_items[0][2])
            elif out is None and not numeric_items[0][1]:
                out = int(numeric_items[0][0])

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
        approx_sale_date=normalize_iso_date(dt, reference_year) or dt,
        exchange_name=exch,
    )


__all__ = ["parse_proposed_sale_box_3"]
