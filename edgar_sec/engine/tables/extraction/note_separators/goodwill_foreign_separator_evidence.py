"""Goodwill foreign-subject separator evidence
(TEST_GOODWILL_FOREIGN_SEPARATOR): the priced conjunction over
one table's grid — a claim is refused when its stub/header zone
binds a foreign walked subject and goodwill is not bound there."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_GOODWILL_FOREIGN_SEPARATOR,
)
from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    failing_core_form_outcome as fired_separator_outcome,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_separator_evidence import (
    _grid_rows,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_foreign_separator_specs import (
    FOREIGN_CLASS_TERMS,
    GOODWILL_FOREIGN_SEPARATOR_SPECS,
    STATEMENT_TITLE_TERMS,
    GoodwillForeignSeparatorSpec,
)
from edgar_sec.engine.tables.extraction.evidence.rollforward_grid_evidence import (
    RollforwardGridText,
)

__all__ = [
    "GoodwillForeignSeparatorVerdict",
    "RollforwardGridText",
    "evaluate_form_test_goodwill_foreign_separator",
    "evaluate_goodwill_foreign_separator",
    "failing_goodwill_foreign_separator_outcome",
    "fired_separator_outcome",
]

_ZONE_ROWS = 10
_HEADER_ROWS = 2

# Qualifiers that make a goodwill stub bind goodwill as the
# walked subject; a bare "Goodwill" row does not.
_GOODWILL_SUBJECT_QUALIFIERS = (
    ", gross",
    ", net",
    " as of",
    " - ",
    " associated",
    " at ",
    " balance",
)


@dataclass(frozen=True)
class GoodwillForeignSeparatorVerdict:
    """The separator verdict for one table: fired legs, if any."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def _zone(rows: list[list[str]]) -> tuple[list[str], list[str], list[str]]:
    """The priced zone: stubs and header cells of the first
    rows, as (stubs, header cells, all zone cells), lowered."""
    zone_rows = rows[:_ZONE_ROWS]
    stubs = [next((cell for cell in cells if cell), "").lower() for cells in zone_rows]
    header_cells = [
        cell.lower() for cells in rows[:_HEADER_ROWS] for cell in cells if cell
    ]
    zone_cells = [cell.lower() for cells in zone_rows for cell in cells if cell]
    return stubs, header_cells, zone_cells


_FOREIGN_INDEX = TermIndex(
    [TermEntry(term, "title") for term in STATEMENT_TITLE_TERMS]
    + [TermEntry(term, "class", value=term) for term in FOREIGN_CLASS_TERMS]
    + [
        TermEntry("level 3", "level3"),
        TermEntry("goodwill", "goodwill"),
    ]
    + [TermEntry(q, "qualifier") for q in _GOODWILL_SUBJECT_QUALIFIERS]
)


def _foreign_subject_zone(
    text: RollforwardGridText, stubs: list[str], zone_cells: list[str]
) -> bool:
    """A foreign walked subject is bound in the zone: by title,
    by class enumeration, or as the single walked subject."""
    caption = text.caption.lower()
    caption_hits = _FOREIGN_INDEX.scan(caption)
    if "level3" in caption_hits:
        return True
    zone_hits = [ _FOREIGN_INDEX.scan(cell) for cell in zone_cells ]
    if any("title" in hits for hits in zone_hits):
        return True
    if any(stub.startswith("intangible assets") for stub in stubs):
        return True
    classes = set()
    for hits in zone_hits:
        classes |= set(hits.get("class", frozenset()))
    if len(classes) >= 2:
        return True
    if "class" in caption_hits:
        return True
    return bool(stubs) and any(
        stubs[0] == term or stubs[0].startswith(term + " ")
        for term in FOREIGN_CLASS_TERMS
    )


def _goodwill_bound(
    text: RollforwardGridText, stubs: list[str], header_cells: list[str]
) -> bool:
    """Goodwill is a bound subject of the zone: named in the
    caption, heading a column, or bound by a qualified stub."""
    if "goodwill" in _FOREIGN_INDEX.scan(text.caption.lower()):
        return True
    if any("goodwill" in _FOREIGN_INDEX.scan(cell) for cell in header_cells):
        return True
    return any(
        stub.startswith("goodwill") and "qualifier" in _FOREIGN_INDEX.scan(stub)
        for stub in stubs
    )


def evaluate_goodwill_foreign_separator(
    text: RollforwardGridText, spec: GoodwillForeignSeparatorSpec
) -> GoodwillForeignSeparatorVerdict:
    """Evaluate one grid against the family's priced conjunction."""
    rows = _grid_rows(text)
    if not rows:
        return GoodwillForeignSeparatorVerdict(
            False, False, (), "separator unevaluable: no grid rows"
        )
    stubs, header_cells, zone_cells = _zone(rows)
    legs: list[str] = []
    for leg in spec.legs:
        if leg.scope != "claim-local":
            continue
        if leg.kind == "foreign_subject_zone":
            if _foreign_subject_zone(text, stubs, zone_cells):
                legs.append(leg.leg_id)
        elif leg.kind == "goodwill_not_bound":
            if not _goodwill_bound(text, stubs, header_cells):
                legs.append(leg.leg_id)
    priced = tuple(leg.leg_id for leg in spec.legs if leg.scope == "claim-local")
    if tuple(legs) == priced:
        detail = "foreign separator fired: " + ", ".join(legs)
        return GoodwillForeignSeparatorVerdict(True, True, tuple(legs), detail)
    return GoodwillForeignSeparatorVerdict(False, True, (), "separator clear")


def failing_goodwill_foreign_separator_outcome(form_tests):
    """The stamped separator outcome failing this family's gate.

    Delegates to the homed outcome reader in core_form_evidence."""
    return fired_separator_outcome(
        form_tests, "goodwill_rollforward", TEST_GOODWILL_FOREIGN_SEPARATOR
    )


# ---------------- production wiring (stage adapter + gate) ----------------


def evaluate_form_test_goodwill_foreign_separator(table, spec):
    """Stage adapter: evaluate the declared separator over a table."""
    gate_spec = GOODWILL_FOREIGN_SEPARATOR_SPECS.get(spec.family)
    if gate_spec is None:
        return GoodwillForeignSeparatorVerdict(
            False, False, (), "no separator spec for family"
        )
    text = RollforwardGridText(
        "\n".join(" | ".join(row) for row in table.context.rows),
        " ".join(table.context.caption_stack or ()),
    )
    return evaluate_goodwill_foreign_separator(text, gate_spec)
