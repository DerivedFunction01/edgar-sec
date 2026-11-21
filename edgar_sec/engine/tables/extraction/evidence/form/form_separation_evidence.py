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
from edgar_sec.engine.tables.extraction.specs.form_separation_specs import (
    FORM_SEPARATION_SPECS,
    FormSeparationSpec,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_evidence import (
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
_EPS_OWN_FRAME_TERMS = (
    "numerator",
    "denominator",
    "weighted average",
    "weighted-average",
    "average shares",
    "average common shares",
    "equivalent shares",
)
_EPS_FRAME_HEADER_LABELS = (
    "numerator",
    "denominator",
    "weighted average",
    "weighted-average",
    "weighted average shares",
    "weighted-average shares",
    "average shares",
    "average common shares",
    "per share",
    "per-share",
    "per share amount",
    "per-share amount",
)
_INTANGIBLE_CLASS_NAMES = (
    "goodwill",
    "patents",
    "trademarks",
    "trade names",
    "customer relationships",
    "developed technology",
    "licenses",
    "copyrights",
    "intangible assets",
    "other intangible assets",
)
_COMPOSITION_TERMS = (
    "warrant",
    "stock option",
    "options",
    "rsa",
    "rsu",
    "conversion of",
    "convertible",
    "anti-dilutive",
    "share award",
    "unit option",
    "restricted stock",
    "accrued",
    "accounts receivable",
    "allowance for doubtful",
    "principal",
    "unamortized",
    "debt discount",
    "debt issuance",
    "net carrying",
    "united states",
    "international",
    "cost of sales",
    "operating expenses",
    "restructuring",
)
_GOODWILL_MOVEMENT_WORDS = (
    "acquired",
    "disposed",
    "adjustment",
    "measurement",
    "translation",
    "reclassified",
    "related",
    "sale",
    "impairment",
)
_PAYMENT_SCHEDULE_TERMS = (
    "payment date",
    "record date",
    "distribution amount",
    "dividend payments",
)


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


def _is_eps_own_frame(subjects: tuple[str, ...]) -> bool:
    """An EPS computation's own frame: numerator/denominator or share base."""
    return any(term in subject for subject in subjects for term in _EPS_OWN_FRAME_TERMS)


def _eps_own_frame_in_headers(text: FormSeparationText) -> bool:
    """The EPS own frame in the header band: a label cell or fragments.

    The band is the leading rows before the first stubbed data row;
    a descriptive header merely containing the words does not match.
    """
    units: list[str] = []
    for row in text.rows:
        if row[0].strip() and any(STRICT_NUMERIC_CELL_RE.match(cell) for cell in row):
            break
        for cell in row:
            for line in cell.split("\n"):
                unit = " ".join(line.lower().split()).strip("():")
                if unit:
                    units.append(unit)
    if any(unit in _EPS_FRAME_HEADER_LABELS for unit in units):
        return True
    for label in _EPS_FRAME_HEADER_LABELS:
        parts = label.split(" ")
        if len(parts) < 2:
            continue
        for i in range(len(units) - len(parts) + 1):
            if units[i : i + len(parts)] == parts:
                return True
    return False


def _is_intangibles_own_frame(subjects: tuple[str, ...]) -> bool:
    """An intangibles table's own frame: a bare class stub."""
    return any(subject in _INTANGIBLE_CLASS_NAMES for subject in subjects)


def _is_own_frame(subjects: tuple[str, ...], family: str) -> bool:
    """The family's own-frame signal, guarding the broad branches."""
    if family == "eps_reconciliation":
        return _is_eps_own_frame(subjects)
    if family == "intangibles":
        return _is_intangibles_own_frame(subjects)
    return False


def _has_add_deduct_walk(subjects: tuple[str, ...]) -> bool:
    """An Add:/Deduct: walk: a stub whose first token is add or deduct."""
    return any(
        subject.split(" ", 1)[0] in ("add", "deduct") for subject in subjects if subject
    )


def _data_subjects(text: FormSeparationText, subjects: tuple[str, ...]) -> list[str]:
    """The subjects of rows with a non-empty subject and a numeric cell."""
    return [
        subject
        for row, subject in zip(text.rows, subjects)
        if subject and any(STRICT_NUMERIC_CELL_RE.match(cell) for cell in row)
    ]


def _is_payment_schedule(text: FormSeparationText) -> bool:
    """A dividend/distribution payment schedule: date headers."""
    header_text = " ".join(text.headers).lower()
    return any(term in header_text for term in _PAYMENT_SCHEDULE_TERMS)


def _is_option_schedule(subjects: tuple[str, ...]) -> bool:
    """An option schedule: an option-count or purchase-price stub."""
    return any(
        "number of options" in subject or "option purchase price" in subject
        for subject in subjects
    )


def _is_condensed_summary(
    text: FormSeparationText, subjects: tuple[str, ...], family: str
) -> bool:
    """A condensed note-level summary: short, own-frame absent."""
    if _is_own_frame(subjects, family):
        return False
    if len(_data_subjects(text, subjects)) > 6:
        return False
    return any(
        "income from continuing operations" in subject or "statutory capital" in subject
        for subject in subjects
    )


def _is_percentage_schedule(text: FormSeparationText) -> bool:
    """A percentage schedule: a Percentage header over numeric rows."""
    header_text = " ".join(text.headers).lower()
    if "percentage" not in header_text:
        return False
    numeric_rows = sum(
        1
        for row in text.rows
        if any(STRICT_NUMERIC_CELL_RE.match(cell) for cell in row)
    )
    return numeric_rows >= 2


def _is_goodwill_segment(subject: str) -> bool:
    """A goodwill-by-segment stub: qualified, no movement word."""
    if not subject.startswith("goodwill") or len(subject.split()) < 2:
        return False
    return not any(word in subject for word in _GOODWILL_MOVEMENT_WORDS)


def _is_generalized_composition(
    text: FormSeparationText, subjects: tuple[str, ...], family: str
) -> bool:
    """A component composition: >=2 component stubs, own-frame absent."""
    if _is_own_frame(subjects, family):
        return False
    if family == "eps_reconciliation" and _eps_own_frame_in_headers(text):
        return False
    if _has_add_deduct_walk(subjects):
        return False
    matched = {
        subject
        for subject in subjects
        if any(term in subject for term in _COMPOSITION_TERMS)
        or _is_goodwill_segment(subject)
    }
    return len(matched) >= 2


def _is_goodwill_walk_narrow(subjects: tuple[str, ...]) -> bool:
    """A separable goodwill walk: named acquisition/disposal or held-for-sale."""
    if any(
        "goodwill acquired through the acquisition of" in subject
        or "goodwill disposed through the sale of" in subject
        for subject in subjects
    ):
        return True
    if any("reclassified to assets held for sale" in subject for subject in subjects):
        return True
    return any(
        subject.startswith("sale of") and "to franchisees" in subject
        for subject in subjects
    )


def _is_nongaap_bridge(subjects: tuple[str, ...]) -> bool:
    """A non-GAAP core bridge: a core EPS stub."""
    return any("core eps" in subject for subject in subjects)


def _is_fair_value_wrapped(text: FormSeparationText) -> bool:
    """A wrapped fair-value header: carrying/fair/value tokens."""
    tokens = set(" ".join(text.headers).lower().split())
    return {"carrying", "fair", "value"} <= tokens


def _is_single_data_row_fragment(
    text: FormSeparationText, subjects: tuple[str, ...]
) -> bool:
    """A single-data-row fragment: one data row, no own-frame stub."""
    data = _data_subjects(text, subjects)
    if len(data) != 1:
        return False
    subject = data[0]
    if "amortization" in subject:
        return False
    return not any(term in subject for term in _EPS_OWN_FRAME_TERMS)


def _determine_form(text: FormSeparationText, spec: FormSeparationSpec) -> str | None:
    """The determined form token for one candidate, or None.

    Recognizers key on the form's own subject signals, in
    most-specific-first order; an unrecognized form abstains.
    """
    subjects = _stub_subjects(text)
    family = spec.family
    is_eps = family == "eps_reconciliation"
    is_int = family == "intangibles"
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
    if is_eps and _is_payment_schedule(text):
        return "supplemental-schedule"
    if is_eps and _is_option_schedule(subjects):
        return "supplemental-schedule"
    if _is_lease_maturity(text, subjects):
        return "gold:lease_maturity"
    if _is_debt_maturity(text, subjects):
        return "gold:debt_maturity"
    if _is_movement_detail(subjects):
        return "movement-detail"
    if is_int and _is_goodwill_walk_narrow(subjects):
        return "movement-detail"
    if is_eps and _is_nongaap_bridge(subjects):
        return "movement-detail"
    if _is_restatement_recast(subjects):
        return "restatement-recast"
    if _is_statement_summary(subjects):
        return "statement-summary"
    if is_eps and _is_condensed_summary(text, subjects, family):
        return "statement-summary"
    if _is_percentage_rows(text):
        return "percentage-rows"
    if is_eps and _is_percentage_schedule(text):
        return "percentage-rows"
    if _is_segment_detail(text, subjects):
        return "segment-detail"
    if _is_composition(subjects):
        return "composition"
    if (is_eps or is_int) and _is_generalized_composition(text, subjects, family):
        return "composition"
    if _is_summary_columns(text):
        return "summary-columns"
    if _is_ladder_detail(subjects):
        return "ladder-detail"
    if _is_fair_value(text, subjects):
        return "shape:fair_value"
    if is_eps and _is_fair_value_wrapped(text):
        return "shape:fair_value"
    if (is_eps or is_int) and _is_single_data_row_fragment(text, subjects):
        return "fragment"
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
