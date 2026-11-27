"""Goodwill sibling-mass separator evidence
(TEST_GOODWILL_SIBLING_SEPARATOR): the priced conjunction
over one table's grid — refused when the grid's stub rows
carry sibling-class mass and no stub binds goodwill."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_GOODWILL_SIBLING_SEPARATOR,
)
from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    failing_core_form_outcome as fired_separator_outcome,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_separator_evidence import (
    _grid_rows,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_sibling_separator_specs import (
    GOODWILL_SIBLING_SEPARATOR_SPECS,
    SIBLING_CLASS_TERMS,
    GoodwillSiblingSeparatorSpec,
)
from edgar_sec.engine.tables.extraction.evidence.rollforward_grid_evidence import (
    RollforwardGridText,
)

__all__ = [
    "GoodwillSiblingSeparatorVerdict",
    "RollforwardGridText",
    "evaluate_form_test_goodwill_sibling_separator",
    "evaluate_goodwill_sibling_separator",
    "failing_goodwill_sibling_separator_outcome",
    "fired_separator_outcome",
]


@dataclass(frozen=True)
class GoodwillSiblingSeparatorVerdict:
    """The separator verdict for one table: fired legs, if any."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


_SIBLING_INDEX = TermIndex(
    [TermEntry(term, "sibling") for term in SIBLING_CLASS_TERMS]
    + [TermEntry("goodwill", "goodwill")]
)


def _stubs(rows: list[list[str]]) -> list[str]:
    """The grid's stub rows, lowered: first cell of each row."""
    return [next((cell for cell in cells if cell), "").lower() for cells in rows]


def _sibling_mass(stubs: list[str]) -> int:
    """Stub rows carrying a sibling intangibles-class term."""
    return sum(1 for stub in stubs if "sibling" in _SIBLING_INDEX.scan(stub))


def evaluate_goodwill_sibling_separator(
    text: RollforwardGridText, spec: GoodwillSiblingSeparatorSpec
) -> GoodwillSiblingSeparatorVerdict:
    """Evaluate one grid against the family's priced conjunction."""
    rows = _grid_rows(text)
    if not rows:
        return GoodwillSiblingSeparatorVerdict(
            False, False, (), "separator unevaluable: no grid rows"
        )
    stubs = _stubs(rows)
    legs: list[str] = []
    for leg in spec.legs:
        if leg.scope != "claim-local":
            continue
        if leg.kind == "sibling_mass":
            if _sibling_mass(stubs) >= int(leg.limit):
                legs.append(leg.leg_id)
        elif leg.kind == "goodwill_not_stub_subject":
            if not any("goodwill" in _SIBLING_INDEX.scan(stub) for stub in stubs):
                legs.append(leg.leg_id)
    priced = tuple(leg.leg_id for leg in spec.legs if leg.scope == "claim-local")
    if tuple(legs) == priced:
        detail = "sibling separator fired: " + ", ".join(legs)
        return GoodwillSiblingSeparatorVerdict(True, True, tuple(legs), detail)
    return GoodwillSiblingSeparatorVerdict(False, True, (), "separator clear")


def failing_goodwill_sibling_separator_outcome(form_tests):
    """The stamped separator outcome failing this family's gate.

    Delegates to the homed outcome reader in core_form_evidence."""
    return fired_separator_outcome(
        form_tests, "goodwill_rollforward", TEST_GOODWILL_SIBLING_SEPARATOR
    )


# ---------------- production wiring (stage adapter + gate) ----------------


def evaluate_form_test_goodwill_sibling_separator(table, spec):
    """Stage adapter: evaluate the declared separator over a table."""
    gate_spec = GOODWILL_SIBLING_SEPARATOR_SPECS.get(spec.family)
    if gate_spec is None:
        return GoodwillSiblingSeparatorVerdict(
            False, False, (), "no separator spec for family"
        )
    text = RollforwardGridText(
        "\n".join(
            " | ".join(cell.replace("\n", " ").replace("\r", " ") for cell in row)
            for row in table.context.rows
        ),
        " ".join(table.context.caption_stack or ()),
    )
    return evaluate_goodwill_sibling_separator(text, gate_spec)
