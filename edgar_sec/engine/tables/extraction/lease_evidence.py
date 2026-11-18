"""Lease evidence seat: the depth-4 attribution cell.
A claim seats on the priced winner form or on the named
ladder form under the prose-class guard.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_test_specs import FormTestSpec
from edgar_sec.engine.tables.extraction.lease_specs import (
    LEASE_EVIDENCE_SPECS_BY_TEST_ID,
    LeaseEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable
from edgar_sec.foundation.text.dates import YEAR_TOKEN_SEARCH_RE


def _year_labels(text: str) -> int:
    """Distinct 19xx/20xx year tokens: the priced label count."""
    return len(
        {
            year
            for year in YEAR_TOKEN_SEARCH_RE.findall(text)
            if year[:2] in ("19", "20")
        }
    )


@dataclass(frozen=True, slots=True)
class LeaseText:
    """One geometry's seat text: rows, caption, lead prose.
    Rows are normalized as the priced parse normalizes:
    cells stripped, trailing empties dropped, empty rows out."""

    rows: tuple[tuple[str, ...], ...] = ()
    caption: str = ""
    lead: str = ""

    @property
    def stub_low(self) -> tuple[str, ...]:
        """Every row's first cell, lowercased."""
        return tuple((row[0] if row else "").lower() for row in self.rows)

    @property
    def stub_text(self) -> str:
        """Every stub label as one text: the priced surface."""
        return " ".join(self.stub_low)

    @property
    def header_text(self) -> str:
        """The first row joined, lowercased."""
        return " ".join(self.rows[0]).lower() if self.rows else ""

    @property
    def year_labels(self) -> int:
        """Distinct year tokens over stub and header text."""
        return _year_labels(" ".join(self.stub_low) + " " + self.header_text)

    @classmethod
    def from_table(cls, table: TypedTable) -> LeaseText:
        """Seat text from a typed table's context."""
        rows = []
        for row in table.context.rows:
            cells = [str(cell).strip() for cell in row]
            while cells and cells[-1] == "":
                cells.pop()
            if any(cells):
                rows.append(tuple(cells))
        context = table.context
        return cls(
            rows=tuple(rows),
            caption=" ".join(context.caption_stack).lower(),
            lead=(context.prose_before or "").lower(),
        )


@dataclass(frozen=True, slots=True)
class LeaseLegs:
    """The priced rule's leg readings over one geometry."""

    year_labels: int
    ladder2: bool
    ladder3: bool
    ta_row: bool
    total_pay: bool
    pv_leg: bool
    core: bool
    winner: bool
    prose_class_cap: bool
    prose_class_lead: bool
    prose_class: bool
    named: bool
    named_class: bool

    @property
    def claim(self) -> bool:
        """The seat claim: the winner, or the guarded named form."""
        return self.winner or self.named_class


def legs_for(text: LeaseText, spec: LeaseEvidenceSpec) -> LeaseLegs:
    """Every leg of the priced rule over one geometry's text."""
    years = text.year_labels
    ladder2 = years >= spec.named_min_year_labels
    ladder3 = years >= spec.core_min_year_labels
    ta_row = any(s.startswith(spec.thereafter_prefix) for s in text.stub_low)
    total_pay = any(term in text.stub_text for term in spec.total_terms)
    pv_leg = any(term in text.stub_text for term in spec.pv_terms)
    core = ladder3 and total_pay
    cap_n = text.caption.replace("-", " ")
    lead_n = text.lead.replace("-", " ")
    prose_class_cap = any(term in cap_n for term in spec.class_terms)
    prose_class_lead = any(term in lead_n for term in spec.class_terms)
    prose_class = prose_class_cap or prose_class_lead
    named = ladder2 and ta_row
    return LeaseLegs(
        year_labels=years,
        ladder2=ladder2,
        ladder3=ladder3,
        ta_row=ta_row,
        total_pay=total_pay,
        pv_leg=pv_leg,
        core=core,
        winner=core or pv_leg,
        prose_class_cap=prose_class_cap,
        prose_class_lead=prose_class_lead,
        prose_class=prose_class,
        named=named,
        named_class=named and prose_class,
    )


@dataclass(frozen=True, slots=True)
class LeaseEvidence:
    """The seat verdict for one geometry under the seat's spec."""

    admitted: bool
    evaluable: bool
    legs: LeaseLegs | None
    detail: str


def evaluate_lease(text: LeaseText, spec: LeaseEvidenceSpec) -> LeaseEvidence:
    """The seat verdict over one geometry's seat text."""
    legs = legs_for(text, spec)
    if legs.winner:
        return LeaseEvidence(True, True, legs, "winner: core or present-value form")
    if legs.named_class:
        return LeaseEvidence(True, True, legs, "named ladder under the class guard")
    return LeaseEvidence(
        False, True, legs, f"no seat leg (year labels {legs.year_labels})"
    )


def evaluate_form_test_lease(table: TypedTable, spec: FormTestSpec) -> LeaseEvidence:
    """Stage adapter: evaluate the declared seat spec over a table."""
    gate_spec = LEASE_EVIDENCE_SPECS_BY_TEST_ID.get(spec.test_id)
    if gate_spec is None:
        return LeaseEvidence(False, False, None, "no seat spec for test")
    if not table.context.rows:
        return LeaseEvidence(False, False, None, "no grid rows")
    return evaluate_lease(LeaseText.from_table(table), gate_spec)
