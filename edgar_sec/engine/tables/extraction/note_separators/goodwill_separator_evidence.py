"""Goodwill separator evidence (TEST_GOODWILL_SEPARATOR).
Evaluates the priced allocation-form conjunction over one table's
grid: a goodwill_rollforward claim is refused when the geometry
carries the allocation anatomy and no goodwill bookend walk."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_GOODWILL_SEPARATOR,
)
from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    failing_core_form_outcome as fired_separator_outcome,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_separator_specs import (
    GOODWILL_SEPARATOR_SPECS,
    GoodwillSeparatorSpec,
)
from edgar_sec.engine.tables.extraction.evidence.rollforward_grid_evidence import (
    RollforwardGridText,
    grid_features,
)

__all__ = [
    "GoodwillSeparatorVerdict",
    "RollforwardGridText",
    "evaluate_form_test_goodwill_separator",
    "evaluate_goodwill_separator",
    "failing_goodwill_separator_outcome",
    "fired_separator_outcome",
]

_HEADER_WINDOW = 2000


@dataclass(frozen=True)
class GoodwillSeparatorVerdict:
    """The separator verdict for one table: fired legs, if any."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def _grid_rows(text: RollforwardGridText) -> list[list[str]]:
    """The grid as rows of cells, from the grid text surface."""
    rows = []
    for line in text.table_text.split("\n"):
        cells = [cell.strip() for cell in line.split("|")]
        if any(cells):
            rows.append(cells)
    return rows


def evaluate_goodwill_separator(
    text: RollforwardGridText, spec: GoodwillSeparatorSpec
) -> GoodwillSeparatorVerdict:
    """Evaluate one grid against the family's priced conjunction."""
    rows = _grid_rows(text)
    if not rows:
        return GoodwillSeparatorVerdict(
            False, False, (), "separator unevaluable: no grid rows"
        )
    full_text = " ".join(" ".join(cells) for cells in rows).lower()
    header_zone = " ".join(text.table_text.lower().split())[:_HEADER_WINDOW]
    stubs = [next((cell for cell in cells if cell), "").lower() for cells in rows]
    allocation_context = "allocation" in full_text or "acquired" in full_text
    legs: list[str] = []
    for leg in spec.legs:
        if leg.scope != "claim-local":
            continue
        if leg.kind == "allocation_columns":
            preliminary_side = "preliminary" in header_zone or (
                "before adjustment" in header_zone
            )
            if preliminary_side and "final" in header_zone and allocation_context:
                legs.append(leg.leg_id)
        elif leg.kind == "goodwill_acquired_line":
            if allocation_context and any(
                stub.startswith("goodwill") for stub in stubs
            ):
                legs.append(leg.leg_id)
        elif leg.kind == "no_bookend_walk":
            if not grid_features(text).bookend_f2:
                legs.append(leg.leg_id)
    priced = tuple(leg.leg_id for leg in spec.legs if leg.scope == "claim-local")
    if tuple(legs) == priced:
        detail = "separator fired: " + ", ".join(legs)
        return GoodwillSeparatorVerdict(True, True, tuple(legs), detail)
    return GoodwillSeparatorVerdict(False, True, (), "separator clear")


def failing_goodwill_separator_outcome(form_tests):
    """The stamped separator outcome failing this family's gate.

    Delegates to the homed outcome reader in core_form_evidence."""
    return fired_separator_outcome(
        form_tests, "goodwill_rollforward", TEST_GOODWILL_SEPARATOR
    )


# ---------------- production wiring (stage adapter + gate) ----------------


def evaluate_form_test_goodwill_separator(table, spec):
    """Stage adapter: evaluate the declared separator over a table."""
    gate_spec = GOODWILL_SEPARATOR_SPECS.get(spec.family)
    if gate_spec is None:
        return GoodwillSeparatorVerdict(
            False, False, (), "no separator spec for family"
        )
    text = RollforwardGridText.from_rows(table.context.rows)
    return evaluate_goodwill_separator(text, gate_spec)
