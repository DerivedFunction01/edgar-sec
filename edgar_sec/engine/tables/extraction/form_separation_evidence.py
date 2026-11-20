"""Form-separation evidence (TEST_FORM_SEPARATION).

The claim-level form determination over one candidate:
the geometry's determined form read against the family's
foreign classes and gold-routing families.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import YEAR_TOKEN_RE
from edgar_sec.engine.tables.extraction.form_separation_specs import (
    FORM_SEPARATION_SPECS,
    FormSeparationSpec,
)
from edgar_sec.engine.tables.extraction.pension_routed_evidence import (
    header_keys,
    stub_key,
)
from edgar_sec.engine.tables.numeric_cells import STRICT_NUMERIC_CELL_RE

_HEADER_LINES = 3

_PAREN_RE = re.compile(r"\([^)]*\)")
_FIRM_RE = re.compile(build_alternation(["CPA", "PLLC", "LLP", r"P\.A\."]))
_STATEMENT_LINE_PATTERNS = (
    "total revenues",
    "operating expenses",
    "operating income",
    "operating loss",
    "interest income",
    "interest expense",
    "income tax",
    "net income",
    "net loss",
    "gross profit",
    "cost of revenues",
)
_STOCK_STATUS_TERMS = (
    "nonaccrual",
    "past due",
    "nonperforming",
    "delinquent",
    "impaired loans",
    "troubled debt",
)
_INVENTORY_COMPONENT_TERMS = (
    "raw materials",
    "work in process",
    "finished goods",
    "merchandise",
)
_QUARTER_ORDINALS = ("1st", "2nd", "3rd", "4th")
_LEVEL_RE = re.compile(r"^level (i|ii|iii)\b")


class FormSeparationText:
    """The packet text surface the determiner reads."""

    def __init__(self, table_text, caption_stack=()):
        lines = [ln for ln in (table_text or "").split("\n") if ln.strip()]
        self.rows = [tuple(c.strip() for c in ln.split("|")) for ln in lines]
        self.raw_stubs = tuple(row[0] for row in self.rows)
        self.stubs = tuple(stub for stub in self.raw_stubs if stub)
        self.headers = tuple(cell for row in self.rows[:_HEADER_LINES] for cell in row)
        self.caption_stack = list(caption_stack or [])
        self.stub_keys = frozenset(
            key for key in (stub_key(stub) for stub in self.stubs) if key
        )
        self.header_keys = header_keys(self.headers)

    @classmethod
    def from_packet(cls, packet):
        return cls(packet.get("table_text") or "", packet.get("caption_stack") or [])

    @classmethod
    def from_rows(cls, rows, caption_stack=()):
        table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
        return cls(table_text, caption_stack)


@dataclass(frozen=True, slots=True)
class FormSeparationVerdict:
    """The determination's read: refused on a foreign form."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def _stub_subjects(text: FormSeparationText) -> tuple[str, ...]:
    """Per-row stub keys, parenthetical tails stripped."""
    return tuple(stub_key(_PAREN_RE.sub(" ", stub)) for stub in text.raw_stubs)


def _numeric_cells(text: FormSeparationText) -> list[str]:
    """The grid's strict-numeric data cells."""
    return [
        cell for row in text.rows for cell in row if STRICT_NUMERIC_CELL_RE.match(cell)
    ]


def _is_furniture(text: FormSeparationText) -> bool:
    """A non-grid text block: no numerics, single-cell rows."""
    if _numeric_cells(text):
        return False
    return all(sum(1 for cell in row if cell) <= 1 for row in text.rows)


def _is_eps_reconciliation(subjects: tuple[str, ...]) -> bool:
    """The EPS computation form: per-share lines over a share base."""
    if not any("per share" in subject for subject in subjects):
        return False
    return any(
        "weighted average shares" in subject or subject in ("numerator", "denominator")
        for subject in subjects
    )


def _is_warrant_activity(text: FormSeparationText, subjects: tuple[str, ...]) -> bool:
    """A warrant schedule: warrant terms over an exercise price."""
    joined = (" ".join(text.headers) + " " + " ".join(subjects)).lower()
    return "warrant" in joined and "exercise price" in joined


def _is_inventory(subjects: tuple[str, ...]) -> bool:
    """An inventory schedule: at least two component stubs."""
    matched = {
        term
        for subject in subjects
        for term in _INVENTORY_COMPONENT_TERMS
        if term in subject
    }
    return len(matched) >= 2


def _is_supplemental_schedule(
    text: FormSeparationText, subjects: tuple[str, ...]
) -> bool:
    """The accountant-fees schedule: audit-fee stubs or the firm."""
    if any("audit" in subject for subject in subjects):
        return True
    if len(text.rows) > 6:
        return False
    return any(_FIRM_RE.search(cell) for row in text.rows for cell in row if cell)


def _is_lease_maturity(text: FormSeparationText, subjects: tuple[str, ...]) -> bool:
    """The maturity ladder: bare-year stubs ending in Thereafter."""
    years = sum(1 for stub in text.raw_stubs if YEAR_TOKEN_RE.match(stub.strip()))
    return years >= 3 and "thereafter" in subjects


def _is_debt_maturity(text: FormSeparationText, subjects: tuple[str, ...]) -> bool:
    """A debt maturity ladder: Thereafter over debt stubs."""
    header_text = " ".join(text.headers).lower()
    return "thereafter" in header_text and any(
        "debt" in subject for subject in subjects
    )


def _is_movement_detail(subjects: tuple[str, ...]) -> bool:
    """A movement bridge: direction stubs or a pre/post-tax bridge."""
    direction = sum(
        1
        for subject in subjects
        if subject.startswith("higher ") or subject.startswith("lower ")
    )
    if direction >= 2:
        return True
    return "total before tax" in subjects and "net of tax" in subjects


def _is_restatement_recast(subjects: tuple[str, ...]) -> bool:
    """A restatement recast: an as-adjusted stub."""
    return any("as adjusted" in subject for subject in subjects)


def _is_statement_summary(subjects: tuple[str, ...]) -> bool:
    """A condensed statement: at least three core statement lines."""
    matched = {
        pattern
        for subject in subjects
        for pattern in _STATEMENT_LINE_PATTERNS
        if pattern in subject
    }
    return len(matched) >= 3


def _is_percentage_rows(text: FormSeparationText) -> bool:
    """A mix table in percents: a total row summing to 100."""
    percent_cells = sum(
        1 for row in text.rows for cell in row if cell == "%" or cell.endswith("%")
    )
    if percent_cells < 2:
        return False
    subjects = _stub_subjects(text)
    for row, subject in zip(text.rows, subjects):
        if not subject.startswith("total"):
            continue
        for cell in row:
            if not STRICT_NUMERIC_CELL_RE.match(cell):
                continue
            try:
                value = float(cell.strip("()$").replace(",", ""))
            except ValueError:
                continue
            if value == 100:
                return True
    return False


def _is_segment_detail(text: FormSeparationText, subjects: tuple[str, ...]) -> bool:
    """Segment results with variance columns over a revenue total."""
    if not any(subject.startswith("total revenue") for subject in subjects):
        return False
    if sum(1 for subject in subjects if subject) < 3:
        return False
    header_text = " ".join(text.headers).lower()
    return "change" in header_text


def _is_composition(subjects: tuple[str, ...]) -> bool:
    """A credit-stock composition: status components over a stock total."""
    status = {
        subject
        for subject in subjects
        if any(term in subject for term in _STOCK_STATUS_TERMS)
    }
    if len(status) < 2:
        return False
    return any(
        subject.startswith("total") and ("loans" in subject or "receivables" in subject)
        for subject in subjects
    )


def _is_summary_columns(text: FormSeparationText) -> bool:
    """Quarterly columns: a quarters caption over ordinal headers."""
    caption_text = " ".join(text.caption_stack).lower()
    header_text = " ".join(text.headers).lower()
    if "quarters" not in caption_text and "quarters" not in header_text:
        return False
    ordinals = sum(1 for ordinal in _QUARTER_ORDINALS if ordinal in header_text)
    return ordinals >= 3


def _is_ladder_detail(subjects: tuple[str, ...]) -> bool:
    """A due-in ladder: at least two due-in stubs."""
    return sum(1 for subject in subjects if subject.startswith("due in")) >= 2


def _is_fair_value(text: FormSeparationText, subjects: tuple[str, ...]) -> bool:
    """A fair-value shape: level stubs or carrying/fair headers."""
    levels = {subject for subject in subjects if _LEVEL_RE.match(subject)}
    if len(levels) >= 2:
        return True
    header_text = " ".join(text.headers).lower()
    return "carrying value" in header_text and "fair value" in header_text


def _is_fragment(text: FormSeparationText) -> bool:
    """A fragment: one row, or two rows of long prose stubs."""
    if len(text.rows) == 1:
        return True
    if len(text.rows) != 2:
        return False
    stubs = [stub for stub in text.stubs if stub.strip()]
    return bool(stubs) and all(len(stub) >= 80 for stub in stubs)


def _determine_form(text: FormSeparationText, spec: FormSeparationSpec) -> str | None:
    """The determined form token for one candidate, or None.

    Recognizers key on the form's own subject signals, in
    most-specific-first order; an unrecognized form abstains.
    """
    subjects = _stub_subjects(text)
    if _is_furniture(text):
        return "furniture"
    if _is_eps_reconciliation(subjects):
        return "gold:eps_reconciliation"
    if _is_warrant_activity(text, subjects):
        return "gold:warrant_activity"
    if _is_inventory(subjects):
        return "gold:inventory"
    if _is_supplemental_schedule(text, subjects):
        return "supplemental-schedule"
    if _is_lease_maturity(text, subjects):
        return "gold:lease_maturity"
    if _is_debt_maturity(text, subjects):
        return "gold:debt_maturity"
    if _is_movement_detail(subjects):
        return "movement-detail"
    if _is_restatement_recast(subjects):
        return "restatement-recast"
    if _is_statement_summary(subjects):
        return "statement-summary"
    if _is_percentage_rows(text):
        return "percentage-rows"
    if _is_segment_detail(text, subjects):
        return "segment-detail"
    if _is_composition(subjects):
        return "composition"
    if _is_summary_columns(text):
        return "summary-columns"
    if _is_ladder_detail(subjects):
        return "ladder-detail"
    if _is_fair_value(text, subjects):
        return "shape:fair_value"
    if _is_fragment(text):
        return "fragment"
    return None


def _is_foreign(token: str, spec: FormSeparationSpec) -> bool:
    """Whether a determined form token refuses this family."""
    if token in spec.foreign_classes:
        return True
    if token == "restatement-recast":
        return spec.recast_cell
    if token == "segment-detail":
        return spec.segment_detail_cell
    if token.startswith("gold:"):
        return token[len("gold:") :] in spec.gold_families
    if token.startswith("shape:"):
        return spec.foreign_shapes and token[len("shape:") :] != spec.family
    return False


def evaluate_form_separation(
    text: FormSeparationText, spec: FormSeparationSpec
) -> FormSeparationVerdict:
    """Refuse when the determined form is foreign here."""
    if not text.rows:
        return FormSeparationVerdict(False, False, (), "no grid rows")
    token = _determine_form(text, spec)
    if token is None or not _is_foreign(token, spec):
        return FormSeparationVerdict(False, True, (), "form separation clear")
    legs = (f"form:{token}",)
    return FormSeparationVerdict(
        True, True, legs, "form separation fired: " + ", ".join(legs)
    )


# ---------------------------------------------------------------
# Production wiring: the stage adapter reads the assembled
# table's full grid (context rows) through the same derivation.


def evaluate_form_test_form_separation(table, spec) -> FormSeparationVerdict:
    """Stage entry: evaluate the determination over a table."""
    context = table.context
    text = FormSeparationText.from_rows(
        context.rows, list(context.caption_stack) + list(table.caption.titles)
    )
    return evaluate_form_separation(text, FORM_SEPARATION_SPECS[spec.family])
