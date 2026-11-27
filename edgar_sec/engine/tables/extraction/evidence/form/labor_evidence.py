"""Labor-form evidence: the S6-B bargaining-unit signature seat.

Evaluates the priced signature over one table's grid, under the
fragment guard carried in the signature.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.specs.families.labor_specs import (
    COUNT_HDR,
    DATE_HDR,
    LABOR_EVIDENCE_SPECS,
    LABOR_EVIDENCE_SPECS_BY_TEST_ID,
    REP_HDR,
    UNION_NAMES,
    WORKFORCE_HDR,
    LaborEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import collapse_text
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

_REP = "rep"
_COUNT = "count"
_COUNT_NUMBER = "count_number"
_WORKFORCE = "workforce"
_DATE = "date"
_UNION_NAME = "union_name"


@lru_cache(maxsize=None)
def _header_index() -> TermIndex:
    """The header tuples as one index, substring mode (the
    lists' own semantics), plus the compound count check's
    bare "number" as its own kind."""
    entries = [TermEntry(term, _REP) for term in REP_HDR]
    entries += [TermEntry(term, _COUNT) for term in COUNT_HDR]
    entries.append(TermEntry("number", _COUNT_NUMBER))
    entries += [TermEntry(term, _WORKFORCE) for term in WORKFORCE_HDR]
    entries += [TermEntry(term, _DATE) for term in DATE_HDR]
    return TermIndex(entries)


@lru_cache(maxsize=None)
def _stub_index() -> TermIndex:
    """The stub tuple as one index, substring mode."""
    return TermIndex(TermEntry(term, _UNION_NAME) for term in UNION_NAMES)


def evaluate_labor_evidence(text: LaborText, spec: LaborEvidenceSpec) -> LaborEvidence:
    """Seat iff the priced signature fires outside the guard.
    Core legs only: representative identity or temporal terms in
    the header grammar; supporting features never seat alone."""
    header_hits = _header_index().scan(text.header_text)
    stub_hits = _stub_index().scan(text.stub_text)
    hdr_rep = bool(header_hits.get(_REP))
    count = bool(header_hits.get(_COUNT)) or (
        "employees" in header_hits.get(_WORKFORCE, frozenset())
        and bool(header_hits.get(_COUNT_NUMBER))
    )
    count3 = count or bool(header_hits.get(_WORKFORCE))
    hdr_date = bool(header_hits.get(_DATE))
    stub_name = bool(stub_hits.get(_UNION_NAME))
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
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
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
