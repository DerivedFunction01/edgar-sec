"""PPE evidence seat: the re-derived vocabulary form.
A claim seats on the guarded re-derived core or on any of
the six priced geometry forms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_test_specs import FormTestSpec
from edgar_sec.engine.tables.extraction.ppe_specs import (
    PPE_EVIDENCE_SPECS_BY_TEST_ID,
    PpeEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable
from edgar_sec.foundation.text.dates import (
    YEAR_TOKEN_PATTERN,
    YEAR_TOKEN_SEARCH_RE,
)

NET_CLOSE_RE = re.compile(r"(property|equipment)[^.]{0,40}net|net of accumulated")
NET_LABEL_COMMA_RE = re.compile(r",\s*net\b")
NET_LABEL_END_RE = re.compile(r"\bnet$")
BOOKEND_DATED_RE = re.compile(rf"(balance|as of).{{0,40}}(?:{YEAR_TOKEN_PATTERN})")
BOOKEND_YEAR_ROW_RE = re.compile(rf".*(?:{YEAR_TOKEN_PATTERN}).*")


@dataclass(frozen=True, slots=True)
class PpeText:
    """One geometry's seat text: rows and lead prose.
    Rows are normalized as the priced parse normalizes:
    cells stripped, trailing empties dropped, empty rows out."""

    rows: tuple[tuple[str, ...], ...] = ()
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
    def all_text(self) -> str:
        """Every cell of every row as one lowercased text."""
        return " ".join(" ".join(row) for row in self.rows).lower()

    @property
    def header_text(self) -> str:
        """The first row joined, lowercased."""
        return " ".join(self.rows[0]).lower() if self.rows else ""

    @classmethod
    def from_table(cls, table: TypedTable) -> PpeText:
        """Seat text from a typed table's context."""
        rows = []
        for row in table.context.rows:
            cells = [str(cell).strip() for cell in row]
            while cells and cells[-1] == "":
                cells.pop()
            if any(cells):
                rows.append(tuple(cells))
        return cls(
            rows=tuple(rows),
            lead=(table.context.prose_before or "").lower(),
        )


def _bookend_r2(text: PpeText, spec: PpeEvidenceSpec) -> bool:
    """The dated-bookend grammar, ported from the priced
    instrument: a beginning-side and an ending-side marker,
    by word, by dated balance row, or by forward term."""
    stub = text.stub_low
    half = max(len(stub) // 2, 1)
    begin_word = any(term in s for term in spec.bookend_begin_terms for s in stub)
    end_word = any(term in s for term in spec.bookend_end_terms for s in stub)
    dated = [
        bool(BOOKEND_DATED_RE.search(s))
        or (bool(BOOKEND_YEAR_ROW_RE.fullmatch(s)) and "balance" in s)
        for s in stub
    ]
    begin_dated = any(dated[:half]) or (
        bool(stub) and "as of" in stub[0] and bool(YEAR_TOKEN_SEARCH_RE.search(stub[0]))
    )
    end_dated = any(dated[half:]) or (
        bool(stub)
        and "as of" in stub[-1]
        and bool(YEAR_TOKEN_SEARCH_RE.search(stub[-1]))
    )
    bf = any(term in s for term in spec.bookend_forward_begin_terms for s in stub)
    cf = any(term in s for term in spec.bookend_forward_end_terms for s in stub)
    return (begin_word or begin_dated or bf) and (end_word or end_dated or cf)


@dataclass(frozen=True, slots=True)
class PpeLegs:
    """The priced rule's leg readings over one geometry."""

    class_rows: int
    classes2: bool
    classes3: bool
    contra: bool
    contra_all: bool
    net_close: bool
    net_label: bool
    net_bare: bool
    net2: bool
    bs_guard: bool
    lease_guard: bool
    net_col: bool
    bookend_r2: bool
    newcore: bool
    newcore_lg: bool
    col_form: bool
    col1_form: bool
    s3_form: bool
    roll_form: bool
    rights_form: bool
    comp_form: bool

    @property
    def claim(self) -> bool:
        """The seat claim: the guarded core or a geometry form."""
        return (
            self.newcore_lg
            or self.col_form
            or self.col1_form
            or self.s3_form
            or self.roll_form
            or self.rights_form
            or self.comp_form
        )

    @property
    def seat_leg(self) -> str:
        """The first firing seat leg, in priced form order."""
        for name in (
            "newcore_lg",
            "col_form",
            "col1_form",
            "s3_form",
            "roll_form",
            "rights_form",
            "comp_form",
        ):
            if getattr(self, name):
                return name
        return ""


def legs_for(text: PpeText, spec: PpeEvidenceSpec) -> PpeLegs:
    """Every leg of the priced rule over one geometry's text."""
    stub = text.stub_low
    stub_text = text.stub_text
    all_text = text.all_text

    def count_stub(*terms: str) -> int:
        return sum(1 for s in stub if any(t in s for t in terms))

    class_rows = count_stub(*spec.class_terms)
    classes2 = class_rows >= 2
    contra = spec.contra_term in stub_text
    net_close = bool(NET_CLOSE_RE.search(stub_text)) or any(
        lit in stub_text for lit in spec.net_close_literals
    )
    net_label = any(
        NET_LABEL_COMMA_RE.search(s)
        or NET_LABEL_END_RE.search(s)
        or s.startswith("net ")
        for s in stub
    )
    net_bare = False
    for i, s in enumerate(stub):
        if spec.contra_term in s:
            after = stub[i + 1 :]
            if 1 <= len(after) <= 2 and all(
                a == "" or a.startswith("total") for a in after
            ):
                net_bare = True
    net2 = net_close or net_label or net_bare
    bs_guard = spec.bs_guard_term not in stub_text
    lease_guard = all(term not in stub_text for term in spec.lease_guard_terms)
    contra_all = spec.contra_term in all_text
    second_row = text.rows[1] if len(text.rows) > 1 else ()
    net_col = any(term in all_text for term in spec.net_col_terms) or any(
        cell.strip().lower() == "net" for cell in second_row
    )
    bookend_r2 = _bookend_r2(text, spec)
    newcore = classes2 and contra and net2 and bs_guard
    header = text.header_text
    return PpeLegs(
        class_rows=class_rows,
        classes2=classes2,
        classes3=class_rows >= 3,
        contra=contra,
        contra_all=contra_all,
        net_close=net_close,
        net_label=net_label,
        net_bare=net_bare,
        net2=net2,
        bs_guard=bs_guard,
        lease_guard=lease_guard,
        net_col=net_col,
        bookend_r2=bookend_r2,
        newcore=newcore,
        newcore_lg=newcore and lease_guard,
        col_form=classes2 and contra_all and net_col and not contra,
        col1_form=class_rows == 1
        and all(term in header for term in spec.col1_header_terms),
        s3_form=spec.s3_marker_term in all_text
        and contra_all
        and any(term in all_text for term in spec.s3_cost_terms),
        roll_form=bookend_r2
        and all(term in stub_text for term in spec.roll_stub_terms),
        rights_form=count_stub(spec.rights_term) >= 2
        and spec.depletion_term in stub_text
        and net_label,
        comp_form=class_rows == 1 and contra and spec.comp_lead_term in text.lead,
    )


@dataclass(frozen=True, slots=True)
class PpeEvidence:
    """The seat verdict for one geometry under the seat's spec."""

    admitted: bool
    evaluable: bool
    legs: PpeLegs | None
    detail: str


def evaluate_ppe(text: PpeText, spec: PpeEvidenceSpec) -> PpeEvidence:
    """The seat verdict over one geometry's seat text."""
    legs = legs_for(text, spec)
    if legs.claim:
        return PpeEvidence(True, True, legs, f"seat leg: {legs.seat_leg}")
    return PpeEvidence(False, True, legs, f"no seat leg (class rows {legs.class_rows})")


def evaluate_form_test_ppe(table: TypedTable, spec: FormTestSpec) -> PpeEvidence:
    """Stage adapter: evaluate the declared seat spec over a table."""
    gate_spec = PPE_EVIDENCE_SPECS_BY_TEST_ID.get(spec.test_id)
    if gate_spec is None:
        return PpeEvidence(False, False, None, "no seat spec for test")
    if not table.context.rows:
        return PpeEvidence(False, False, None, "no grid rows")
    return evaluate_ppe(PpeText.from_table(table), gate_spec)
