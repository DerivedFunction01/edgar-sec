"""Stock comp separator evidence (TEST_STOCK_COMP_SEPARATOR).
Evaluates the priced span_ge_5 leg over one table's grid: a
stock_comp claim is refused when the grid spans five or more
distinct years. The set-level assign_other leg runs at filing
level, anchored on the input-class seat's determined claim.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core_form_evidence import (
    failing_core_form_outcome as fired_separator_outcome,
)
from edgar_sec.engine.tables.extraction.input_class_evidence import (
    input_class_evidence_for_geometry,
)
from edgar_sec.engine.tables.extraction.stock_comp_separator_specs import (
    STOCK_COMP_SEPARATOR_SPECS,
    StockCompSeparatorSpec,
)
from edgar_sec.foundation.text.dates import YEAR_TOKEN_SEARCH_RE

__all__ = [
    "StockCompSeparatorText",
    "StockCompSeparatorVerdict",
    "apply_stock_comp_assignment",
    "evaluate_form_test_stock_comp_separator",
    "evaluate_stock_comp_separator",
    "fired_separator_outcome",
    "year_span",
]


class StockCompSeparatorText:
    """One table's grid as the separator reads it: rows of cells."""

    def __init__(self, table_text: str = ""):
        self.table_text = table_text or ""
        lines = [ln for ln in self.table_text.split("\n") if ln.strip()]
        self.rows = [[c.strip() for c in ln.split("|")] for ln in lines]

    @classmethod
    def from_rows(cls, rows) -> "StockCompSeparatorText":
        """Grid text from raw context rows (production surface)."""
        table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
        return cls(table_text)

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
    if fired:
        detail = "separator fired: " + ", ".join(fired)
        return StockCompSeparatorVerdict(True, True, tuple(fired), detail)
    return StockCompSeparatorVerdict(False, True, (), "separator clear")


def apply_stock_comp_assignment(geometries, results):
    """Filing-level pass: a stock_comp claim is refused when a
    determined other-family seat has seated the same geometry
    (assign_other; the input-class seat for the anchor family).
    """
    from edgar_sec.engine.tables.extraction.competition import (
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
    text = StockCompSeparatorText.from_rows(table.context.rows)
    return evaluate_stock_comp_separator(text, gate_spec)
