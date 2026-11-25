"""Stock comp separator evidence (TEST_STOCK_COMP_SEPARATOR).
Evaluates the priced claim-local legs over one table — span_ge_5
and the C2 composition over the seat verdict and geometry
surfaces — plus the set-level assign_other leg at filing level.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    failing_core_form_outcome as fired_separator_outcome,
)
from edgar_sec.engine.tables.extraction.evidence.form.input_class_evidence import (
    input_class_evidence_for_geometry,
)
from edgar_sec.engine.tables.extraction.evidence.equity.stock_comp_evidence import (
    StockCompText,
    evaluate_stock_comp,
    legs_for,
)
from edgar_sec.engine.tables.extraction.note_separators.stock_comp_separator_specs import (
    STOCK_COMP_SEPARATOR_SPECS,
    StockCompSeparatorSpec,
)
from edgar_sec.engine.tables.extraction.specs.families.stock_comp_specs import (
    STOCK_COMP_EVIDENCE_SPECS,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.date_patterns import YEAR_TOKEN_SEARCH_RE

__all__ = [
    "StockCompSeparatorSurfaces",
    "StockCompSeparatorText",
    "StockCompSeparatorVerdict",
    "apply_stock_comp_assignment",
    "evaluate_form_test_stock_comp_separator",
    "evaluate_stock_comp_separator",
    "fired_separator_outcome",
    "separator_surfaces_for",
    "year_span",
]

_SEAT_SPEC = STOCK_COMP_EVIDENCE_SPECS["stock_comp_rollforward"]
_BOOKEND_RE = re.compile(
    build_alternation(
        (
            "outstanding at",
            "outstanding as of",
            "vested at",
            "balance as of",
            "balance at",
        )
    )
)
_AVAILABLE_RE = re.compile(r"\s*available\b")


@dataclass(frozen=True)
class StockCompSeparatorSurfaces:
    """The C2 composition's readings over one table: the seat
    verdict and legs, and the geometry channel reads."""

    seat_admitted: bool
    activity_rows: int
    units_lead: bool
    col_waep: bool
    bookend: bool
    warrant: bool
    available: bool


def separator_surfaces_for(table) -> StockCompSeparatorSurfaces:
    """The priced surface readings over one typed table: the seat
    verdict from the family's own evaluator, and the bookend /
    warrant / available reads over the geometry channels."""
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
        geometry_text_from_table,
    )

    seat_text = StockCompText.from_table(table)
    seat_legs = legs_for(seat_text, _SEAT_SPEC)
    seat = evaluate_stock_comp(seat_text, _SEAT_SPEC)
    text = geometry_text_from_table(table, evaluate_stage=False)
    zone = " ".join(list(text.headers) + list(text.stubs)).lower()
    surfaces = " ".join(
        list(text.stubs) + list(text.headers) + [text.lead or "", text.caption or ""]
    ).lower()
    return StockCompSeparatorSurfaces(
        seat_admitted=seat.admitted,
        activity_rows=seat_legs.activity_rows,
        units_lead=seat_legs.units_lead,
        col_waep=seat_legs.col_waep,
        bookend=bool(_BOOKEND_RE.search(zone)),
        warrant="warrant" in surfaces,
        available=any(_AVAILABLE_RE.match(s.lower()) for s in text.stubs),
    )


class StockCompSeparatorText:
    """One table's grid as the separator reads it: rows of
    cells, plus the C2 surface readings when built from a
    typed table (grid-only texts carry none)."""

    def __init__(self, table_text: str = "", surfaces=None):
        self.table_text = table_text or ""
        lines = [ln for ln in self.table_text.split("\n") if ln.strip()]
        self.rows = [[c.strip() for c in ln.split("|")] for ln in lines]
        self.surfaces = surfaces

    @classmethod
    def from_rows(cls, rows) -> "StockCompSeparatorText":
        """Grid text from raw context rows (production surface)."""
        table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
        return cls(table_text)

    @classmethod
    def from_table(cls, table) -> "StockCompSeparatorText":
        """Grid + surfaces from a typed table (stage surface)."""
        text = cls.from_rows(table.context.rows)
        text.surfaces = separator_surfaces_for(table)
        return text

    @classmethod
    def from_packet(cls, packet) -> "StockCompSeparatorText":
        """Grid text from a census packet (priced population)."""
        return cls(packet.get("table_text") or "")


@dataclass(frozen=True)
class StockCompSeparatorVerdict:
    """The separator verdict for one table: fired legs, if any."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def year_span(text: StockCompSeparatorText) -> int:
    """Distinct year tokens over the grid (foundation home)."""
    return len(set(YEAR_TOKEN_SEARCH_RE.findall(text.table_text)))


def _seat_bound_fires(text: StockCompSeparatorText, leg) -> bool:
    """The seat-bound leg: the seat reader does not admit the geometry
    and no exception holds (the Xb bookend form, or a WAEP column —
    the price-form variant carries no bookends). Silent with no surfaces."""
    surfaces = text.surfaces
    if surfaces is None or surfaces.seat_admitted:
        return False
    excepted = surfaces.col_waep or (
        surfaces.bookend
        and (surfaces.activity_rows >= leg.limit or surfaces.units_lead)
    )
    return not excepted


def evaluate_stock_comp_separator(
    text: StockCompSeparatorText, spec: StockCompSeparatorSpec
) -> StockCompSeparatorVerdict:
    """Evaluate one grid against the family's priced legs."""
    if not text.rows:
        return StockCompSeparatorVerdict(
            False, False, (), "separator unevaluable: no grid rows"
        )
    fired: list[str] = []
    for leg in spec.legs:
        if leg.scope != "claim-local":
            continue
        if leg.kind == "span" and year_span(text) >= leg.limit:
            fired.append(leg.leg_id)
        elif leg.kind == "seat_bound" and _seat_bound_fires(text, leg):
            fired.append(leg.leg_id)
        elif (
            leg.kind == "warrant"
            and text.surfaces is not None
            and text.surfaces.warrant
        ):
            fired.append(leg.leg_id)
        elif (
            leg.kind == "available"
            and text.surfaces is not None
            and text.surfaces.available
        ):
            fired.append(leg.leg_id)
    if fired:
        detail = "separator fired: " + ", ".join(fired)
        return StockCompSeparatorVerdict(True, True, tuple(fired), detail)
    return StockCompSeparatorVerdict(False, True, (), "separator clear")


def apply_stock_comp_assignment(geometries, results):
    """Filing-level pass: a stock_comp claim is refused when a
    determined other-family seat has seated the same geometry
    (assign_other; the input-class seat for the anchor family).
    """
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
        ClaimEvidence,
        CompetitionResult,
        FamilyScore,
    )

    family = "stock_comp_rollforward"
    spec = STOCK_COMP_SEPARATOR_SPECS[family]
    anchor = next(leg.anchor_family for leg in spec.legs if leg.kind == "assign_other")
    refused: dict[int, str] = {}
    for i, result in enumerate(results):
        if family not in result.claims or anchor not in result.claims:
            continue
        verdict = input_class_evidence_for_geometry(geometries[i], anchor)
        if verdict.admitted:
            refused[i] = f"stock comp assignment: geometry seated to {anchor}"
    if not refused:
        return list(results)
    out = []
    for i, result in enumerate(results):
        if i not in refused:
            out.append(result)
            continue
        scores = dict(result.scores)
        score = scores.get(family)
        if score is not None:
            scores[family] = FamilyScore(
                score.family,
                score.total,
                score.by_channel,
                score.evidence + (ClaimEvidence("gate", refused[i], 0.0),),
            )
        out.append(
            CompetitionResult(
                claims=tuple(name for name in result.claims if name != family),
                contested=tuple(name for name in result.contested if name != family),
                scores=scores,
                foreign_explained=result.foreign_explained,
                groups=result.groups,
            )
        )
    return out


# ---------------- production wiring (stage adapter + gate) ----------------


def evaluate_form_test_stock_comp_separator(table, spec):
    """Stage adapter: evaluate the declared separator over a table."""
    gate_spec = STOCK_COMP_SEPARATOR_SPECS.get(spec.family)
    if gate_spec is None:
        return StockCompSeparatorVerdict(
            False, False, (), "no separator spec for family"
        )
    text = StockCompSeparatorText.from_table(table)
    return evaluate_stock_comp_separator(text, gate_spec)
