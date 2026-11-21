"""Labor-form evidence: the S6-B bargaining-unit signature seat.

Evaluates the priced signature over one table's grid, under the
fragment guard carried in the signature.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.specs.labor_specs import (
    COUNT_HDR,
    DATE_HDR,
    LABOR_EVIDENCE_SPECS,
    LABOR_EVIDENCE_SPECS_BY_TEST_ID,
    REP_HDR,
    UNION_NAMES,
    WORKFORCE_HDR,
    LaborEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.core.normalize import collapse_text
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable
from edgar_sec.foundation.text.normalize import NORMALIZE_TO_SPACE
from edgar_sec.foundation.text.patterns import RE_NAMED_ENTITY, RE_NUMERIC_ENTITY

_FRAGMENT_LEAD = re.compile(r"^\(\d+\)")
FRAGMENT_MAX_CELLS = 3
_TO_SPACE = str.maketrans({**{ch: " " for ch in NORMALIZE_TO_SPACE}, "\u200b": " "})


def _clean(cell: str) -> str:
    """The pricing instrument's cell cleaning, ported exactly."""
    text = cell.translate(_TO_SPACE)
    text = RE_NUMERIC_ENTITY.sub(" ", text)
    text = RE_NAMED_ENTITY.sub(" ", text)
    return collapse_text(text).lower()


@dataclass(frozen=True, slots=True)
class LaborText:
    """One table projected onto the priced signature's surfaces."""

    header_text: str
    stub_text: str
    cell_count: int
    lead_text: str

    @classmethod
    def from_table(cls, table: TypedTable) -> LaborText:
        """Project from the table's grid rows (context.rows)."""
        rows = []
        for row in table.context.rows:
            cells = tuple(_clean(cell) for cell in row)
            if any(cells):
                rows.append(cells)
        header = " | ".join(cell for row in rows[:2] for cell in row)
        stub = " | ".join(row[0] for row in rows if row)
        lead = ""
        for row in table.context.rows:
            for cell in row:
                if cell.strip():
                    lead = cell.strip()
                    break
            if lead:
                break
        return cls(header, stub, sum(len(row) for row in rows), lead)

    @property
    def is_fragment(self) -> bool:
        """The signature's guard: <=3 cells, or a "(n)" text lead."""
        return self.cell_count <= FRAGMENT_MAX_CELLS or bool(
            _FRAGMENT_LEAD.match(self.lead_text)
        )


@dataclass(frozen=True, slots=True)
class LaborEvidence:
    """The labor-form verdict over one table."""

    admitted: bool
    arm: str
    detail: str


_REFUSED = LaborEvidence(False, "", "labor signature absent")


def evaluate_labor_evidence(text: LaborText, spec: LaborEvidenceSpec) -> LaborEvidence:
    """Seat iff the priced signature fires outside the guard.
    Core legs only: representative identity or temporal terms in
    the header grammar; supporting features never seat alone."""
    hdr_rep = any(term in text.header_text for term in REP_HDR)
    count = any(term in text.header_text for term in COUNT_HDR) or (
        "employees" in text.header_text and "number" in text.header_text
    )
    count3 = count or any(term in text.header_text for term in WORKFORCE_HDR)
    hdr_date = any(term in text.header_text for term in DATE_HDR)
    stub_name = any(term in text.stub_text for term in UNION_NAMES)
    arm = ""
    legs = ""
    if hdr_rep and count3:
        arm, legs = "A3", "representative header + coverage header"
    elif hdr_date and stub_name and not hdr_rep:
        arm, legs = "ARM3", "date header + union name in stub"
    if not arm:
        return _REFUSED
    if text.is_fragment:
        return LaborEvidence(False, arm, f"labor signature {arm}: fragment")
    return LaborEvidence(True, arm, f"labor signature {arm}: {legs}")


def evaluate_form_test_labor(table: TypedTable, spec: FormTestSpec) -> LaborEvidence:
    """Stage adapter: evaluate a declared labor spec over a table."""
    gate_spec = LABOR_EVIDENCE_SPECS_BY_TEST_ID.get(spec.test_id)
    if gate_spec is None:
        return _REFUSED
    return evaluate_labor_evidence(LaborText.from_table(table), gate_spec)


def apply_labor_seat(geometry, scores, claims, reach, hard_vetoed, claim_floor):
    """Seat labor_contracts on one geometry, if its form passed.
    Reads the stamped labor_form outcome; unstamped or unpassed
    never acts. Score handling mirrors the derivatives reach."""
    from edgar_sec.engine.tables.extraction.cascade.geometry_scoring import (
        ClaimEvidence,
        FamilyScore,
    )

    spec = next(iter(LABOR_EVIDENCE_SPECS.values()), None)
    if spec is None or spec.family in hard_vetoed or spec.family in claims:
        return scores
    outcome = {o.test_id: o for o in geometry.form_tests}.get(spec.test_id)
    if outcome is None or not outcome.passed:
        return scores
    existing = scores.get(spec.family)
    if existing is None:
        scores = dict(scores)
        scores[spec.family] = FamilyScore(
            spec.family,
            claim_floor,
            {"gate": claim_floor},
            (ClaimEvidence("gate", outcome.detail, claim_floor),),
        )
    elif existing.total < claim_floor:
        lift = claim_floor - existing.total
        channels = dict(existing.by_channel)
        channels["gate"] = channels.get("gate", 0.0) + lift
        scores = dict(scores)
        scores[spec.family] = FamilyScore(
            existing.family,
            claim_floor,
            channels,
            existing.evidence + (ClaimEvidence("gate", outcome.detail, lift),),
        )
    claims.append(spec.family)
    reach.append(spec.family)
    return scores
