"""Lease separator evidence (TEST_LEASE_SEPARATOR): spanprod_le_2
refuses a lease claim whose stub+header span two or fewer distinct
years; subj_before400 one whose subject lead names a financing
liability; assign_sibling_seat runs at filing level, debt-anchored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    failing_core_form_outcome as fired_separator_outcome,
    norml,
)
from edgar_sec.engine.tables.extraction.note_separators.lease_separator_specs import (
    LEASE_SEPARATOR_SPECS,
    LeaseSeparatorSpec,
)
from edgar_sec.foundation.text.date_patterns import YEAR_TOKEN_SEARCH_RE

__all__ = [
    "LeaseSeparatorText",
    "LeaseSeparatorVerdict",
    "apply_lease_assignment",
    "debt_seat_claimed",
    "evaluate_form_test_lease_separator",
    "evaluate_lease_separator",
    "fired_separator_outcome",
    "subject_fires",
    "subject_surface",
    "year_span_prod",
]

DEBT_LADDER_TEST_ID = "debt_maturity_year_ladder"
DEBT_ADMISSION_TEST_ID = "debt_maturity_j1_admission"
_SUBJECT_RES = {
    leg.leg_id: re.compile(leg.pattern)
    for spec in LEASE_SEPARATOR_SPECS.values()
    for leg in spec.legs
    if leg.kind == "subject"
}


class LeaseSeparatorText:
    """One table's surfaces as the separator reads them: grid rows
    (the pricing instrument's row hygiene), caption stack, and
    prose_before for the subject leg."""

    def __init__(self, table_text: str = "", caption_stack=(), prose_before=""):
        self.table_text = table_text or ""
        self.caption_stack = tuple(caption_stack or ())
        self.prose_before = prose_before or ""
        rows = []
        for ln in self.table_text.split("\n"):
            if not ln.strip():
                continue
            cells = [c.strip() for c in ln.split("|")]
            while cells and cells[-1] == "":
                cells.pop()
            if any(cells):
                rows.append(cells)
        self.rows = rows

    @classmethod
    def from_rows(cls, rows, caption_stack=(), prose_before="") -> "LeaseSeparatorText":
        """Surfaces from raw context rows (production surface)."""
        table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
        return cls(table_text, caption_stack, prose_before)

    @classmethod
    def from_packet(cls, packet) -> "LeaseSeparatorText":
        """Surfaces from a census packet (priced population)."""
        return cls(
            packet.get("table_text") or "",
            packet.get("caption_stack") or (),
            packet.get("prose_before") or "",
        )


@dataclass(frozen=True)
class LeaseSeparatorVerdict:
    """The separator verdict for one table: fired legs, if any."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def year_span_prod(text: LeaseSeparatorText) -> int:
    """Distinct year tokens over stub + header (the priced surface)."""
    stubs = " ".join(r[0] for r in text.rows if r and r[0])
    header = " ".join(text.rows[0]) if text.rows else ""
    years = set(YEAR_TOKEN_SEARCH_RE.findall(stubs + " " + header))
    return len(years)


def subject_surface(text: LeaseSeparatorText, tail: int) -> str:
    """The subject surface: caption stack + the prose_before tail,
    read through the frozen NORM (the priced subj_before form)."""
    prose = text.prose_before or ""
    if tail:
        prose = prose[-tail:]
    return norml(" ".join(text.caption_stack) + " " + prose)


def subject_fires(text: LeaseSeparatorText, leg) -> bool:
    """True when the leg's regex matches the subject surface."""
    return _SUBJECT_RES[leg.leg_id].search(subject_surface(text, leg.tail)) is not None


def evaluate_lease_separator(
    text: LeaseSeparatorText, spec: LeaseSeparatorSpec
) -> LeaseSeparatorVerdict:
    """Evaluate one grid against the family's priced legs."""
    if not text.rows:
        return LeaseSeparatorVerdict(
            False, False, (), "separator unevaluable: no grid rows"
        )
    fired: list[str] = []
    for leg in spec.legs:
        if leg.scope != "claim-local":
            continue
        if leg.kind == "span" and year_span_prod(text) <= leg.limit:
            fired.append(leg.leg_id)
        if leg.kind == "subject" and subject_fires(text, leg):
            fired.append(leg.leg_id)
    if fired:
        detail = "separator fired: " + ", ".join(fired)
        return LeaseSeparatorVerdict(True, True, tuple(fired), detail)
    return LeaseSeparatorVerdict(False, True, (), "separator clear")


def debt_seat_claimed(form_tests) -> bool:
    """The debt seat's claim on one geometry, from its stamped
    outcomes: the year ladder and the J1 admission both passed."""
    outcomes = {o.test_id: o.passed for o in form_tests}
    return (
        outcomes.get(DEBT_LADDER_TEST_ID) is True
        and outcomes.get(DEBT_ADMISSION_TEST_ID) is True
    )


def apply_lease_assignment(geometries, results):
    """Filing-level pass: a lease claim is refused when another
    family claims the same geometry, or when the debt seat has
    seated it (assign_sibling_seat); it only removes claims.
    """
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
        ClaimEvidence,
        CompetitionResult,
        FamilyScore,
    )

    family = "lease_maturity"
    refused: dict[int, str] = {}
    for i, result in enumerate(results):
        if family not in result.claims:
            continue
        others = [name for name in result.claims if name != family]
        if others:
            refused[i] = "lease assignment: geometry co-claimed"
        elif debt_seat_claimed(geometries[i].form_tests):
            refused[i] = "lease assignment: geometry seated to debt_maturity"
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


def evaluate_form_test_lease_separator(table, spec):
    """Stage adapter: evaluate the declared separator over a table."""
    gate_spec = LEASE_SEPARATOR_SPECS.get(spec.family)
    if gate_spec is None:
        return LeaseSeparatorVerdict(False, False, (), "no separator spec for family")
    text = LeaseSeparatorText.from_rows(
        table.context.rows, table.context.caption_stack, table.context.prose_before
    )
    return evaluate_lease_separator(text, gate_spec)
