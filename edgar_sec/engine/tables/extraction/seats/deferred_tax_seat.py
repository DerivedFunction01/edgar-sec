"""Deferred tax seat: the R18 maximal-join claim act.

Claims a filing's deferred-tax composition tables from
their own grids, as classify_filing's last pass.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from edgar_sec.engine.tables.extraction.specs.families.deferred_tax_specs import (
    A4_STUB_TERMS,
    A5_STUB_TERM,
    DTA_TERMS,
    DTL_TERMS,
    HEADER_TERMS,
    MARKERS,
    NET_TERMS,
    PERIOD_TERMS,
    TEMP_DIFF_TERMS,
    TOTAL_TERMS,
    VAL_ALLOW_TERMS,
    WALK_ROW_TERMS,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.core.registry import PRIMARY_STATEMENT_FAMILIES
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable
from edgar_sec.engine.tables.numeric_cells import is_strict_numeric_cell

if TYPE_CHECKING:
    from edgar_sec.engine.tables.extraction.cascade.scoring.classify import (
        Classification,
    )

FAMILY = "deferred_tax"
SEAT_DETAIL_PREFIX = "deferred_tax seat:"


@dataclass(frozen=True, slots=True)
class DeferredTaxText:
    """One table's grid surfaces for the deferred-tax legs."""

    rows: tuple[tuple[str, ...], ...]
    stub_low: tuple[str, ...]
    stub_text: str
    header_text: str


def text_from_table(table: TypedTable) -> DeferredTaxText:
    """Project a table's resolved grid to the leg surfaces."""
    rows: list[tuple[str, ...]] = []
    for row in table.context.rows:
        cells = [cell.strip() for cell in row]
        while cells and cells[-1] == "":
            cells.pop()
        if any(cells):
            rows.append(tuple(cells))
    stub_low = tuple((row[0] if row else "").lower() for row in rows)
    return DeferredTaxText(
        rows=tuple(rows),
        stub_low=stub_low,
        stub_text=" ".join(stub_low),
        header_text=" ".join(rows[0]).lower() if rows else "",
    )


def _has(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def legs_for(text: DeferredTaxText) -> dict[str, bool]:
    """Evaluate the deferred-tax legs over one table's text."""
    stub = text.stub_low
    st = text.stub_text
    legs: dict[str, bool] = {}
    legs["dta"] = _has(st, DTA_TERMS)
    legs["dtl"] = _has(st, DTL_TERMS)
    legs["val_allow"] = _has(st, VAL_ALLOW_TERMS)
    legs["net_line"] = _has(st, NET_TERMS)
    legs["two_sided"] = legs["dta"] and legs["dtl"]
    legs["A0_core"] = legs["two_sided"] and (legs["val_allow"] or legs["net_line"])
    legs["total_either"] = _has(st, TOTAL_TERMS)
    legs["closing"] = legs["val_allow"] or legs["net_line"] or legs["total_either"]
    components = sum(1 for s in stub if s and not any(m in s for m in MARKERS))
    legs["components2"] = components >= 2
    legs["temp_diff"] = _has(st, TEMP_DIFF_TERMS)
    legs["hdr_dt"] = _has(text.header_text, HEADER_TERMS)
    legs["subject"] = legs["dta"] or legs["dtl"] or legs["temp_diff"] or legs["hdr_dt"]
    legs["CORE"] = legs["subject"] and legs["components2"] and legs["closing"]
    legs["A1"] = (
        (legs["dta"] or legs["dtl"]) and legs["components2"] and legs["closing"]
    )
    legs["A3"] = legs["temp_diff"] and legs["net_line"]
    walk = sum(1 for s in stub if any(term in s for term in WALK_ROW_TERMS))
    legs["A4"] = walk >= 2 and all(term in st for term in A4_STUB_TERMS)
    legs["A5"] = legs["val_allow"] and _has(st, PERIOD_TERMS) and A5_STUB_TERM in st
    legs["unstubbed_total"] = any(
        (not (row[0] if row else ""))
        and any(is_strict_numeric_cell(cell.replace(" ", "")) for cell in row[1:])
        for row in text.rows
    )
    legs["A6b"] = (
        legs["hdr_dt"]
        and legs["components2"]
        and (legs["closing"] or legs["unstubbed_total"])
    )
    legs["D2COMP"] = legs["CORE"] or legs["A3"] or legs["A5"] or legs["A6b"]
    legs["A4VA"] = legs["A4"] and legs["val_allow"]
    return legs


def seat_claims(
    tables: list[TypedTable] | tuple[TypedTable, ...],
    families: list[str] | tuple[str, ...],
) -> dict[int, str]:
    """The seat's claims over one filing: position -> claim detail."""
    legs = [legs_for(text_from_table(table)) for table in tables]
    base = {
        position
        for position, leg in enumerate(legs)
        if leg["D2COMP"] and families[position] not in PRIMARY_STATEMENT_FAMILIES
    }
    claims: dict[int, str] = {}
    for position, leg in enumerate(legs):
        if position in base:
            arms = "+".join(name for name in ("CORE", "A3", "A5", "A6b") if leg[name])
            claims[position] = f"{SEAT_DETAIL_PREFIX} base ({arms})"
        elif base and leg["subject"] and leg["closing"]:
            claims[position] = f"{SEAT_DETAIL_PREFIX} companion"
        elif leg["A4VA"]:
            claims[position] = f"{SEAT_DETAIL_PREFIX} a4va"
    return claims


def apply_deferred_tax_seat(
    tables: list[TypedTable] | tuple[TypedTable, ...],
    results: list[Classification],
    scores: list[dict[str, float]],
    finish: Callable[..., Classification],
) -> None:
    """Seat the claims in a filing's classification results."""
    from edgar_sec.engine.tables.extraction.cascade.scoring.classify import Evidence

    claims = seat_claims(tables, [result.family for result in results])
    for position, detail in claims.items():
        table = tables[position]
        labels = [normalize_text(row.label) for row in table.rows]
        evidence = list(results[position].evidence) + [Evidence("seat", detail, 0.0)]
        results[position] = finish(
            FAMILY,
            "seat",
            scores[position].get(FAMILY, 0.0),
            evidence,
            labels,
            table,
        )
