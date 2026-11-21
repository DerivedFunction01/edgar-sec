"""Stock comp evidence seat: the activity pair and the
price-form structure reader (depth-2's priced form).
A claim seats on a rank-1 leg; the spec's claim form
selects the seat form or the derived form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.specs.families.stock_comp_specs import (
    STOCK_COMP_EVIDENCE_SPECS_BY_TEST_ID,
    StockCompEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable
from edgar_sec.engine.tables.numeric_cells import is_strict_numeric_cell
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import MONTH_WORD_RE, YEAR_TOKEN_SEARCH_RE

_RANGE2 = re.compile(r"\$?\s*[\d,]+(\.\d+)?\s*(?:[-–—]|\bto\b)\s*\$?\s*[\d,]+(\.\d+)?")
_OPEN_PREFIX = build_alternation(("less than", "under", "below"))
_OPEN_SUFFIX = build_alternation(("and above", "and over", "or more"))
_OPEN_RANGE = re.compile(
    rf"(?:{_OPEN_PREFIX})\s*\$?\s*[\d,]+(\.\d+)?"
    rf"|\$?\s*[\d,]+(\.\d+)?\s*(?:{_OPEN_SUFFIX})"
)
_BOOKEND_LEAD = build_alternation(("outstanding", "nonvested", "unvested"))
_BEGIN = re.compile(
    rf"{_BOOKEND_LEAD}.{{0,30}}{build_alternation(('beginning', 'start'))}"
)
_END = re.compile(rf"{_BOOKEND_LEAD}.{{0,30}}{build_alternation(('end', 'ending'))}")


def _cell_kind(cell: str) -> str:
    """The pricing kind of one grid cell."""
    if not cell:
        return "empty"
    if "%" in cell:
        return "percent"
    if is_strict_numeric_cell(cell.replace(" ", "")):
        return "numeric"
    if YEAR_TOKEN_SEARCH_RE.search(cell) or MONTH_WORD_RE.search(cell):
        return "date"
    return "text"


def _is_range(cell: str) -> bool:
    """Whether one stub cell reads as an exercise-price range."""
    c = cell.strip().lower()
    if not c or len(c) > 48:
        return False
    return bool(_RANGE2.search(c) or _OPEN_RANGE.search(c))


def _normalize_rows(rows) -> tuple[tuple[str, ...], ...]:
    """The pricing grid shape: stripped cells, trailing
    empties popped, all-empty rows dropped."""
    out = []
    for row in rows:
        cells = [c.strip() for c in row]
        while cells and cells[-1] == "":
            cells.pop()
        if any(cells):
            out.append(tuple(cells))
    return tuple(out)


@dataclass(frozen=True, slots=True)
class StockCompText:
    """One geometry's seat text: normalized grid rows and
    the lead prose. Rows arrive normalized (from_table or
    the packet parse); the legs read them as priced."""

    rows: tuple[tuple[str, ...], ...] = ()
    lead: str = ""

    @classmethod
    def from_table(cls, table: TypedTable) -> StockCompText:
        """Seat text from a typed table: normalized grid + lead."""
        return cls(
            rows=_normalize_rows(table.context.rows),
            lead=table.context.prose_before,
        )


@dataclass(frozen=True, slots=True)
class StockCompLegs:
    """The priced rule's leg readings over one geometry."""

    activity_rows: int
    act1: bool
    act2: bool
    granted: bool
    pair: bool
    lead_options: bool
    winner: bool
    range_rows: int
    col_waep: bool
    col_out: bool
    col_exerc: bool
    gx2: bool
    bookend_begin: bool
    bookend_end: bool
    core: bool
    units_lead: bool

    @property
    def seat_claim(self) -> bool:
        """The seat form: the pair, or the structure reader."""
        return self.pair or self.gx2

    @property
    def derived_claim(self) -> bool:
        """The derived form: the fenced winner, or units ∧ core."""
        return (self.winner and not self.col_exerc) or (self.units_lead and self.core)

    def claim(self, form: str) -> bool:
        """The claim under one named form."""
        return self.derived_claim if form == "derived" else self.seat_claim


def legs_for(text: StockCompText, spec: StockCompEvidenceSpec) -> StockCompLegs:
    """Every leg of the priced rule over one geometry."""
    rows = text.rows
    stub_low = [(row[0] if row else "").lower() for row in rows]
    stub_text = " ".join(stub_low)
    lead = text.lead.lower()
    activity_rows = sum(1 for s in stub_low if any(t in s for t in spec.activity_terms))
    act1 = activity_rows >= 1
    act2 = activity_rows >= spec.min_activity_rows
    granted = spec.granted_term in stub_text
    pair = granted and act2
    lead_options = spec.lead_options_term in lead
    winner = pair or (lead_options and act2)
    hdr_end = len(rows)
    for i, row in enumerate(rows):
        stub_cell = row[0] if row else ""
        n_num = sum(1 for c in row[1:] if _cell_kind(c) == "numeric")
        if (
            _is_range(stub_cell)
            or is_strict_numeric_cell(stub_cell.replace(" ", ""))
            or n_num >= 2
        ):
            hdr_end = i
            break
    hdr_block = rows[:hdr_end] if hdr_end else rows[:1]
    data_stub = [(row[0] if row else "") for row in rows[hdr_end:]]
    n_cols = max((len(r) for r in rows), default=0)
    col_hdrs = [
        " ".join(r[j] for r in hdr_block if j < len(r)).lower() for j in range(n_cols)
    ]
    range_rows = sum(1 for s in data_stub if _is_range(s))
    col_waep = any(spec.waep_term in h for h in col_hdrs[1:])
    col_out = any(spec.outstanding_term in h for h in col_hdrs[1:])
    col_exerc = any(spec.exercisable_term in h for h in col_hdrs[1:])
    gx2 = range_rows >= spec.min_range_rows and col_waep and (col_out or col_exerc)
    bookend_begin = bool(_BEGIN.search(stub_text)) or (
        "beginning of year" in stub_text or "beginning of period" in stub_text
    )
    bookend_end = bool(_END.search(stub_text)) or (
        "end of year" in stub_text or "end of period" in stub_text
    )
    return StockCompLegs(
        activity_rows=activity_rows,
        act1=act1,
        act2=act2,
        granted=granted,
        pair=pair,
        lead_options=lead_options,
        winner=winner,
        range_rows=range_rows,
        col_waep=col_waep,
        col_out=col_out,
        col_exerc=col_exerc,
        gx2=gx2,
        bookend_begin=bookend_begin,
        bookend_end=bookend_end,
        core=bookend_begin and bookend_end and act1,
        units_lead=spec.units_term in lead,
    )


@dataclass(frozen=True, slots=True)
class StockCompEvidence:
    """The seat verdict for one geometry under the seat's spec."""

    admitted: bool
    evaluable: bool
    legs: StockCompLegs | None
    detail: str


def _seat_detail(legs: StockCompLegs) -> str:
    """The firing legs of the seat form, named."""
    fired = []
    if legs.pair:
        fired.append("pair: granted stub with activity")
    if legs.gx2:
        fired.append("gx2: range-bucket structure under a waep column")
    return "; ".join(fired)


def _derived_detail(legs: StockCompLegs) -> str:
    """The firing legs of the derived form, named."""
    fired = []
    if legs.winner and not legs.col_exerc:
        fired.append("winner fenced: no exercisable column")
    if legs.units_lead and legs.core:
        fired.append("units lead with typed core")
    return "; ".join(fired)


def evaluate_stock_comp(
    text: StockCompText, spec: StockCompEvidenceSpec
) -> StockCompEvidence:
    """The seat verdict over one geometry's seat text."""
    legs = legs_for(text, spec)
    if legs.claim(spec.claim_form):
        detail = (
            _derived_detail(legs)
            if spec.claim_form == "derived"
            else _seat_detail(legs)
        )
        return StockCompEvidence(True, True, legs, detail)
    return StockCompEvidence(
        False,
        True,
        legs,
        f"no seat leg ({spec.claim_form} form; activity rows "
        f"{legs.activity_rows}, range rows {legs.range_rows})",
    )


def evaluate_form_test_stock_comp(
    table: TypedTable, spec: FormTestSpec
) -> StockCompEvidence:
    """Stage adapter: evaluate the declared seat spec over a table."""
    seat_spec = STOCK_COMP_EVIDENCE_SPECS_BY_TEST_ID.get(spec.test_id)
    if seat_spec is None:
        return StockCompEvidence(False, False, None, "no seat spec for test")
    if not table.context.rows:
        return StockCompEvidence(False, False, None, "no grid rows")
    return evaluate_stock_comp(StockCompText.from_table(table), seat_spec)
