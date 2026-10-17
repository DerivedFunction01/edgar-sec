"""Extraction of proposed sale details from Form 144 Box 3."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.families.form144.models import (
    BrokerDetails,
    ProposedSaleItem,
)
from edgar_sec.engine.forms.common.entities import (
    STATE_ZIP_RE,
    STREET_SUFFIX_RE,
    normalize_exchange_name,
)
from edgar_sec.engine.forms.common.numbers import clean_numeric
from edgar_sec.engine.forms.form144.patterns import NUMERIC_TOKEN_RE
from edgar_sec.engine.forms.form144.sections import ClassifiedSection
from edgar_sec.foundation.text.dates import parse_date


def _field_header(cell: str, marker: str) -> bool:
    lower = cell.lower().replace(" ", "")
    return {
        "a": "title of the class" in cell.lower() or "3(a)" in lower,
        "b": (
            "broker" in cell.lower() and "broker-dealer file number" not in cell.lower()
        )
        or "3(b)" in lower,
        "c": ("to be sold" in cell.lower() or "number of shares" in cell.lower())
        and "outstanding" not in cell.lower()
        or "3(c)" in lower,
        "d": "market value" in cell.lower() or "3(d)" in lower,
        "e": "outstanding" in cell.lower() or "3(e)" in lower,
        "f": "approx" in cell.lower() or "3(f)" in lower,
        "g": "securities exchange" in cell.lower() or "3(g)" in lower,
    }[marker]


def _value_column(
    row: tuple[str, ...],
    row_index: int,
    label_index: int,
    marker: str,
    marker_columns: dict[str, int],
    rows: tuple[tuple[str, ...], ...],
    data_start: int | None = None,
    data_end: int | None = None,
) -> int:
    if label_index > 0:
        previous = row[label_index - 1].strip().replace(" ", "").lower()
        if previous in {f"({marker})", f"3({marker})"}:
            return label_index - 1
    if any(
        label_index < len(marker_row)
        and marker_row[label_index].strip().replace(" ", "").lower()
        in {f"({marker})", f"3({marker})"}
        for marker_row in rows[max(0, row_index - 3) : row_index]
    ):
        return label_index
    marker_index = marker_columns.get(marker)
    if row_index > 0 and marker_index == label_index:
        return marker_index
    if row_index > 0 and marker_index is not None and marker_index + 1 == label_index:
        return marker_index

    next_marker = chr(ord(marker) + 1) if marker < "g" else None
    boundary = next(
        (
            col_idx
            for col_idx in range(label_index + 1, len(row))
            if next_marker and _field_header(row[col_idx], next_marker)
        ),
        len(row),
    )
    start = data_start if data_start is not None else row_index + 1
    end = data_end + 1 if data_end is not None else len(rows)
    scores: dict[int, int] = {}
    for col_idx in range(label_index, max(label_index + 1, boundary)):
        score = 0
        for data_row in rows[start:end]:
            if col_idx >= len(data_row):
                continue
            value = data_row[col_idx].strip()
            if marker in {"c", "d", "e"}:
                score += clean_numeric(value) is not None
            elif marker == "f":
                score += parse_date(value) is not None
            elif marker == "g":
                score += normalize_exchange_name(value) is not None
            elif value and not _field_header(value, marker):
                score += 1
        scores[col_idx] = score
    best_score = max(scores.values(), default=0)
    if best_score:
        if scores.get(label_index) == best_score:
            return label_index
        return next(index for index, score in scores.items() if score == best_score)

    if (
        label_index + 1 < len(row)
        and (
            marker_index == label_index
            or f"({marker})" in row[label_index].lower().replace(" ", "")
            or f"3({marker})" in row[label_index].lower().replace(" ", "")
        )
        and not row[label_index + 1].strip()
    ):
        return label_index + 1
    return label_index


def _box3_marker_columns(rows: tuple[tuple[str, ...], ...]) -> dict[str, int]:
    markers: dict[str, int] = {}
    for row in rows[:2]:
        for col_idx, cell in enumerate(row):
            marker = cell.strip().replace(" ", "").lower()
            for letter in "abcdefg":
                if marker in {f"({letter})", f"3({letter})"}:
                    markers[letter] = col_idx
    return markers


def _has_sale_data_shape(row: tuple[str, ...]) -> bool:
    numeric_count = sum(clean_numeric(cell) is not None for cell in row)
    has_date = any(parse_date(cell) for cell in row)
    has_exchange = any(normalize_exchange_name(cell) for cell in row)
    return numeric_count >= 2 or (numeric_count >= 1 and has_date and has_exchange)


def _has_box3_header(row: tuple[str, ...]) -> bool:
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
    return (
        "3(a)" in text
        or "3 (a)" in text
        or "title of the class" in text
        or ("number of shares" in text and "to be sold" in text)
        or "aggregate market value" in text
        or ("approximate date" in text and "securities exchange" in text)
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


def parse_proposed_sale_box_3(section: ClassifiedSection | None) -> ProposedSaleItem:
    if section is None:
        return ProposedSaleItem()

    grid = section.resolved_grid
    class_title: str | None = None
    broker_name: str | None = None
    broker_street: str | None = None
    broker_city: str | None = None
    broker_state: str | None = None
    broker_zip: str | None = None
    units_to_sell: float | int | None = None
    market_value: float | None = None
    outstanding: float | int | None = None
    approx_date: str | None = None
    exchange: str | None = None

    header_indices: dict[str, int] = {}
    data_rows: list[list[str]] = []
    rows = grid.rows
    data_width = max((len(row) for row in rows), default=0)
    sec_use_column = next(
        (
            col_idx
            for row in rows
            for col_idx, cell in enumerate(row)
            if "sec use only" in cell.lower()
        ),
        None,
    )
    if sec_use_column is not None:
        rows = tuple(
            row[:sec_use_column] + ("",) + row[sec_use_column:]
            if len(row) == data_width - 1
            and (
                any(parse_date(cell) for cell in row)
                or sum(clean_numeric(cell) is not None for cell in row) >= 2
            )
            else row
            for row in rows
        )
    marker_columns = _box3_marker_columns(rows)
    first_box3_header = next(
        (row_idx for row_idx, row in enumerate(rows) if _has_box3_header(row)),
        None,
    )
    data_search_start = first_box3_header + 1 if first_box3_header is not None else 0
    first_data_row = next(
        (
            row_idx
            for row_idx in range(data_search_start, len(rows))
            if _has_sale_data_shape(rows[row_idx])
        ),
        None,
    )
    last_sale_row = next(
        (
            row_idx
            for row_idx in range(len(rows) - 1, data_search_start - 1, -1)
            if _has_sale_data_shape(rows[row_idx])
        ),
        None,
    )
    broker_column = None
    header_start = max(0, first_data_row - 8) if first_data_row is not None else 0
    header_end = first_data_row if first_data_row is not None else len(rows)
    for row_idx in range(header_start, header_end):
        row = rows[row_idx]
        for col_idx, cell in enumerate(row):
            lower = cell.lower()
            if "broker" in lower and "broker-dealer file number" not in lower:
                broker_column = _value_column(
                    row,
                    row_idx,
                    col_idx,
                    "b",
                    marker_columns,
                    rows,
                    first_data_row,
                    last_sale_row,
                )
                break
        if broker_column is not None:
            break
    last_data_row = last_sale_row
    if last_sale_row is not None and broker_column is not None:
        for row_idx in range(last_sale_row + 1, len(rows)):
            row = rows[row_idx]
            if broker_column >= len(row):
                continue
            value = row[broker_column].strip()
            if not value or not all(
                not cell.strip()
                for col_idx, cell in enumerate(row)
                if col_idx != broker_column
            ):
                continue
            address_fragment = STATE_ZIP_RE.search(value) or (
                NUMERIC_TOKEN_RE.match(value)
                and any(character.isalpha() for character in value)
            )
            if address_fragment:
                last_data_row = row_idx

    for row_idx, row in enumerate(rows):
        if row_idx < header_start:
            continue
        if last_data_row is not None and row_idx > last_data_row:
            break
        row_text = " ".join(" ".join(c.split()) for c in row if c.strip())
        lower_row = row_text.lower()
        if not row_text:
            continue
        if lower_row.startswith("instructions:"):
            break

        has_title_hdr = (
            "title of the class" in lower_row
            or "3 (a)" in lower_row
            or "3(a)" in lower_row
        )
        has_broker_hdr = (
            "broker" in lower_row or "3 (b)" in lower_row or "3(b)" in lower_row
        )
        has_units_hdr = (
            "to be sold" in lower_row
            or ("number of shares" in lower_row and "outstanding" not in lower_row)
            or "3 (c)" in lower_row
        )
        has_val_hdr = (
            "market value" in lower_row
            or "aggregate" in lower_row
            or "3 (d)" in lower_row
        )
        has_out_hdr = "outstanding" in lower_row or "3 (e)" in lower_row
        has_date_hdr = "approx" in lower_row or "3 (f)" in lower_row
        has_exch_hdr = "securities exchange" in lower_row or "3 (g)" in lower_row

        has_data_values = (
            any(parse_date(cell) for cell in row)
            or sum(clean_numeric(cell) is not None for cell in row) >= 2
        )
        is_header_row = (
            any(
                (
                    has_title_hdr,
                    has_broker_hdr,
                    has_units_hdr,
                    has_val_hdr,
                    has_out_hdr,
                    has_date_hdr,
                    has_exch_hdr,
                )
            )
            and not has_data_values
        )
        if first_data_row is not None and row_idx < first_data_row:
            is_header_row = True

        for c_idx, cell in enumerate(row):
            c_clean = " ".join(cell.split())
            c_lower = c_clean.lower()
            if not c_clean:
                continue

            if (
                "title of the class" in c_lower or "3 (a)" in c_lower
            ) and class_title is None:
                header_indices.setdefault(
                    "class",
                    _value_column(
                        row,
                        row_idx,
                        c_idx,
                        "a",
                        marker_columns,
                        rows,
                        first_data_row,
                        last_data_row,
                    ),
                )
                if (
                    "title of the class" in c_lower
                    and not is_header_row
                    and c_idx + 1 < len(row)
                    and row[c_idx + 1].strip()
                    and row[c_idx + 1].strip().lower()
                    not in {"(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)"}
                ):
                    val = row[c_idx + 1].strip()
                    if "broker" not in val.lower() and "shares" not in val.lower():
                        class_title = val
            elif (
                (
                    ("broker" in c_lower and "broker-dealer" not in c_lower)
                    or "3 (b)" in c_lower
                )
                and broker_name is None
                and "broker" not in header_indices
            ):
                header_indices.setdefault(
                    "broker",
                    _value_column(
                        row,
                        row_idx,
                        c_idx,
                        "b",
                        marker_columns,
                        rows,
                        first_data_row,
                        last_data_row,
                    ),
                )
                if (
                    not is_header_row
                    and c_idx + 1 < len(row)
                    and row[c_idx + 1].strip()
                ):
                    val = row[c_idx + 1].strip()
                    if not any(
                        term in val.lower()
                        for term in (
                            "shares",
                            "value",
                            "file number",
                            "name and address",
                            "sec use only",
                        )
                    ):
                        broker_name = val
            elif (
                "to be sold" in c_lower
                or ("number of shares" in c_lower and "outstanding" not in c_lower)
                or "3 (c)" in c_lower
            ) and units_to_sell is None:
                header_indices.setdefault(
                    "units",
                    _value_column(
                        row,
                        row_idx,
                        c_idx,
                        "c",
                        marker_columns,
                        rows,
                        first_data_row,
                        last_data_row,
                    ),
                )
                if (
                    not is_header_row
                    and c_idx + 1 < len(row)
                    and row[c_idx + 1].strip()
                ):
                    num = clean_numeric(row[c_idx + 1].strip())
                    if num is not None:
                        units_to_sell = num
            elif (
                "market value" in c_lower
                or "aggregate" in c_lower
                or "3 (d)" in c_lower
            ) and market_value is None:
                header_indices.setdefault(
                    "val",
                    _value_column(
                        row,
                        row_idx,
                        c_idx,
                        "d",
                        marker_columns,
                        rows,
                        first_data_row,
                        last_data_row,
                    ),
                )
                if (
                    not is_header_row
                    and c_idx + 1 < len(row)
                    and row[c_idx + 1].strip()
                ):
                    num = clean_numeric(row[c_idx + 1].strip())
                    if num is not None:
                        market_value = float(num)
            elif (
                "outstanding" in c_lower or "3 (e)" in c_lower
            ) and outstanding is None:
                header_indices.setdefault(
                    "out",
                    _value_column(
                        row,
                        row_idx,
                        c_idx,
                        "e",
                        marker_columns,
                        rows,
                        first_data_row,
                        last_data_row,
                    ),
                )
                if (
                    not is_header_row
                    and c_idx + 1 < len(row)
                    and row[c_idx + 1].strip()
                ):
                    num = clean_numeric(row[c_idx + 1].strip())
                    if num is not None:
                        outstanding = num
            elif ("approx" in c_lower or "3 (f)" in c_lower) and approx_date is None:
                header_indices.setdefault(
                    "date",
                    _value_column(
                        row,
                        row_idx,
                        c_idx,
                        "f",
                        marker_columns,
                        rows,
                        first_data_row,
                        last_data_row,
                    ),
                )
                if (
                    not is_header_row
                    and c_idx + 1 < len(row)
                    and row[c_idx + 1].strip()
                ):
                    parsed = parse_date(row[c_idx + 1].strip())
                    if parsed:
                        approx_date = parsed.display
            elif ("exchange" in c_lower or "3 (g)" in c_lower) and exchange is None:
                header_indices.setdefault(
                    "exch",
                    _value_column(
                        row,
                        row_idx,
                        c_idx,
                        "g",
                        marker_columns,
                        rows,
                        first_data_row,
                        last_data_row,
                    ),
                )
                if (
                    not is_header_row
                    and c_idx + 1 < len(row)
                    and row[c_idx + 1].strip()
                ):
                    exchange = normalize_exchange_name(row[c_idx + 1].strip())

        if not is_header_row:
            data_rows.append([c.strip() for c in row])

    for d_row in data_rows:
        if (
            class_title is None
            and "class" in header_indices
            and header_indices["class"] < len(d_row)
        ):
            val = d_row[header_indices["class"]]
            if val and "title" not in val.lower():
                class_title = " ".join(val.split())

        if (
            broker_name is None
            and "broker" in header_indices
            and header_indices["broker"] < len(d_row)
        ):
            val = d_row[header_indices["broker"]]
            if val and "name" not in val.lower():
                broker_name = val

        if (
            units_to_sell is None
            and "units" in header_indices
            and header_indices["units"] < len(d_row)
        ):
            units_to_sell = clean_numeric(d_row[header_indices["units"]])

        if (
            market_value is None
            and "val" in header_indices
            and header_indices["val"] < len(d_row)
        ):
            num = clean_numeric(d_row[header_indices["val"]])
            if num is not None:
                market_value = float(num)

        if (
            outstanding is None
            and "out" in header_indices
            and header_indices["out"] < len(d_row)
        ):
            outstanding = clean_numeric(d_row[header_indices["out"]])

        if (
            approx_date is None
            and "date" in header_indices
            and header_indices["date"] < len(d_row)
        ):
            parsed = parse_date(d_row[header_indices["date"]])
            if parsed:
                approx_date = parsed.display

        if (
            exchange is None
            and "exch" in header_indices
            and header_indices["exch"] < len(d_row)
        ):
            exchange = normalize_exchange_name(d_row[header_indices["exch"]])

        if exchange is None:
            exchange = normalize_exchange_name(" ".join(d_row))

    broker_column = header_indices.get("broker")
    if broker_column is not None:
        broker_cells: list[str] = []
        for row in data_rows:
            if broker_column >= len(row):
                continue
            value = row[broker_column].strip()
            if not value or "name and address" in value.lower():
                continue
            if broker_cells and not (
                STATE_ZIP_RE.search(value)
                or (
                    NUMERIC_TOKEN_RE.match(value)
                    and any(character.isalpha() for character in value)
                )
            ):
                continue
            broker_cells.append(value)
        if broker_cells:
            broker_name = "\n".join(broker_cells)

    broker = None
    if broker_name:
        broker_lines = [" ".join(line.split()) for line in broker_name.splitlines()]
        broker_lines = [line for line in broker_lines if line]
        broker_name_value = broker_lines[0] if broker_lines else broker_name.strip()
        if len(broker_lines) > 1:
            address_lines = broker_lines[1:]
            state_zip = STATE_ZIP_RE.search(address_lines[-1])
            if state_zip:
                city_text = address_lines[-1][: state_zip.start()].strip(" ,")
                broker_street, broker_city = _split_broker_street_city(city_text)
                broker_city = broker_city or city_text
                broker_state = state_zip.group(1)
                broker_zip = state_zip.group(2)
                broker_street = broker_street or " ".join(address_lines[:-1]) or None
            else:
                broker_street = " ".join(address_lines)
        else:
            state_zip = STATE_ZIP_RE.search(broker_name)
            if state_zip:
                broker_state = state_zip.group(1)
                broker_zip = state_zip.group(2)
                broker_street = broker_name[: state_zip.start()].strip()
        broker = BrokerDetails(
            name=broker_name_value,
            street1=broker_street,
            city=broker_city,
            state_or_country=broker_state,
            zip_code=broker_zip,
        )

    return ProposedSaleItem(
        class_title=class_title,
        broker=broker,
        units_to_be_sold=units_to_sell,
        aggregate_market_value=market_value,
        units_outstanding=outstanding,
        approx_sale_date=approx_date,
        exchange_name=exchange,
    )


__all__ = ["clean_numeric", "parse_proposed_sale_box_3"]
