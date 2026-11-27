"""Restructuring-evidence gate: the ASC 420 walk over one geometry.

Evaluates the gate parameters declared as registry data in
restructuring_evidence_specs.RESTRUCTURING_EVIDENCE_SPECS; a claim
requires the subject, the bookend pair, a movement, no loan context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.core.text.period_keys import (
    numeric_dates as _numeric_dates,
    period_keys as _period_keys,
    priced_years as _priced_years,
    starts_with_numeric_date as _starts_with_numeric_date,
    starts_with_period as _starts_with_period,
)
from edgar_sec.engine.tables.extraction.specs.families.restructuring_evidence_specs import (
    RESTRUCTURING_EVIDENCE_SPECS_BY_TEST_ID,
    RestructuringEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.date_patterns import (
    MONTH_NAMES,
    PERIOD_ENDED_PAT,
    YEAR_TOKEN_PATTERN,
)

# The priced surface is the measurement packet's: prose and grid
# text each capped at 6000 chars, as the collect's packet() caps.
_TEXT_CAP = 6000

_MONTH_ALT = build_alternation(MONTH_NAMES, auto_escape=True)
_MONTH_WORD_RE = re.compile(rf"\b(?:{_MONTH_ALT})\b", re.IGNORECASE)

# Heading boundaries in the prose surface: a numbered note
# heading or an all-caps statement title line.
_HEADING_NUMBERED_RE = re.compile(r"\n\s*\d{1,2}\.\s+[A-Z]")
_HEADING_CAPS_RE = re.compile(r"\n[ A-Z][A-Z0-9 ,&()'’\-]{7,}(?=\n|$)")


@dataclass(frozen=True, slots=True)
class RestructuringText:
    """One geometry's gate text: caption, prose, grid lines."""

    caption: str = ""
    prose: str = ""
    lines: tuple[str, ...] = ()
    note_title: str = ""

    @classmethod
    def from_table(cls, table: TypedTable) -> RestructuringText:
        """Gate text from a typed table, on the priced surface."""
        context = table.context
        table_text = "\n".join(
            " | ".join(str(cell) for cell in row) for row in context.rows
        )
        return cls(
            caption=" ".join(context.caption_stack),
            note_title=(getattr(context.note, "title", "") or ""),
            prose=(context.prose_before or "")[-_TEXT_CAP:],
            lines=tuple(table_text[:_TEXT_CAP].split("\n")),
        )


@dataclass(frozen=True, slots=True)
class RestructuringEvidence:
    """The gate verdict for one geometry under the family's spec."""

    admitted: bool
    detail: str


_REFUSED_NO_SPEC = RestructuringEvidence(False, "no gate spec for test id")


def _last_match_start(pattern: re.Pattern[str], text: str) -> int:
    """Start index of the pattern's last match, or -1 when none."""
    start = -1
    for match in pattern.finditer(text):
        start = match.start()
    return start


def _prose_anchor(prose: str, prose_l: str, terms: tuple[str, ...]) -> bool:
    """The prose arm's boundary discipline: the last subject
    mention must follow the last heading boundary in the prose."""
    subject_pos = max((prose_l.rfind(term) for term in terms), default=-1)
    if subject_pos < 0:
        return False
    heading_pos = max(
        _last_match_start(_HEADING_NUMBERED_RE, prose),
        _last_match_start(_HEADING_CAPS_RE, prose),
    )
    return subject_pos > heading_pos


def _tail_anchor(
    prose: str, prose_l: str, terms: tuple[str, ...], tail_chars: int
) -> bool:
    """The tail lead's boundary discipline: the last subject
    mention inside the tail window must follow the last heading
    boundary inside the tail window."""
    tail_l = prose_l[-tail_chars:]
    subject_pos = max((tail_l.rfind(term) for term in terms), default=-1)
    if subject_pos < 0:
        return False
    heading_pos = max(
        _last_match_start(_HEADING_NUMBERED_RE, prose[-tail_chars:]),
        _last_match_start(_HEADING_CAPS_RE, prose[-tail_chars:]),
    )
    return subject_pos > heading_pos


# Charges-incidence signature: the anatomy discipline that
# separated charges tables at adjudication scale — statement
# anatomy vetoes plus the three form-specific vocabulary measures.
_IS_MARKER_RE = re.compile(
    build_alternation(
        [
            "net revenues",
            r"^revenues\b",
            "gross margin",
            "gross profit",
            r"income \(loss\) from operations",
            "loss from operations",
            "income from operations",
            "cost of revenues",
            "cost of sales",
        ]
    )
)
_CF_MARKER_RE = re.compile(
    build_alternation(
        [
            "cash flows from operating",
            "adjustments to reconcile",
            "cash flows from operations",
            r"net cash (provided|used)",
        ]
    )
)
_COST_STUB_RE = re.compile(
    build_alternation(
        [
            "severance",
            "termination benefit",
            "facility",
            "lease termination",
            "lease exit",
            "contract termination",
            "write-down",
            "writedown",
            "other associated",
            "employee",
            "retention",
            "relocation",
            "exit cost",
            "one-time termination",
        ]
    )
)
_PERIOD_ROW_RE = re.compile(
    build_alternation(
        [
            "fiscal",
            "cumulative",
            "year ended",
            "years ended",
            PERIOD_ENDED_PAT,
            r"^q[1-4]\b",
            rf"(?:{YEAR_TOKEN_PATTERN})\s*$",
        ]
    )
)


def _charges_signature(lines_l: list[str], table_l: str) -> str:
    """The charges-incidence signature over one geometry's lines,
    or an empty string when the anatomy does not carry it."""
    if "charges" not in table_l and "costs" not in table_l:
        return ""
    if any(_CF_MARKER_RE.search(ln) for ln in lines_l):
        return ""
    is_markers = sum(1 for ln in lines_l if _IS_MARKER_RE.search(ln))
    if is_markers >= 2:
        return ""
    numeric_rows = 0
    cost_stubs = 0
    for ln in lines_l:
        cells = ln.split("|")
        if sum(1 for cell in cells if any(ch.isdigit() for ch in cell)) >= 2:
            numeric_rows += 1
        if cells and _COST_STUB_RE.search(cells[0]):
            cost_stubs += 1
    if numeric_rows >= 3 and cost_stubs >= 2:
        return (
            f"charges signature: cost stubs {cost_stubs}, numeric rows {numeric_rows}"
        )
    # Period form (feature contrast): the charges-by-
    # period matrix — cost vocabulary in the column headers, row
    # labels are periods; no cost-type row stubs exist to count.
    header = " ".join(lines_l[:2])
    if "restructuring charges" in header or _COST_STUB_RE.search(header):
        period_rows = sum(1 for ln in lines_l if _PERIOD_ROW_RE.search(ln))
        if period_rows >= 3 and numeric_rows >= 3:
            return (
                f"charges signature: period form, period rows {period_rows}, "
                f"numeric rows {numeric_rows}"
            )
    # Segment form (feature contrast): the charges-by-
    # segment table — charges vocabulary in a total row, row labels
    # are business lines; digit-bearing lines are the row measure.
    total_rows = sum(1 for ln in lines_l if "total" in ln and "restructuring" in ln)
    digit_lines = sum(1 for ln in lines_l if any(ch.isdigit() for ch in ln))
    if total_rows >= 1 and digit_lines >= 3:
        return (
            f"charges signature: segment form, total rows {total_rows}, "
            f"numeric lines {digit_lines}"
        )
    return ""


# Header form: the charge-type vocabulary carried in a walk
# table's column headers, over a balance-at closing row.
_CHARGE_TYPE_TERMS = (
    "severance",
    "facility closure",
    "facility exit",
    "lease termination",
    "contract termination",
    "termination benefit",
    "workforce reduction",
    "exit cost",
    "impairment",
    "relocation",
)


def _charge_type_count(text_l: str) -> int:
    collapsed = " ".join(text_l.split())
    return sum(1 for term in _CHARGE_TYPE_TERMS if term in collapsed)


def _summary_form(lines_l: list[str]) -> str:
    """The summary form (Form B, programme-adopted): an anchored,
    bookendless fragment carrying a Total row, no balance line
    anywhere, and at least 3 data rows — the census's B3 shape."""
    if any("balance" in ln for ln in lines_l):
        return ""
    if not any(ln.strip().startswith("total") or " | total" in ln for ln in lines_l):
        return ""
    data_rows = sum(1 for ln in lines_l if any(ch.isdigit() for ch in ln))
    if data_rows < 3:
        return ""
    return f"summary form, data rows {data_rows}"


_SUMMARY_ANATOMY_MARKERS = (
    "total revenue",
    "net sales",
    "total net sales",
    "total operating expenses",
    "total operating income",
    "net pension",
    "postretirement benefit cost",
    "total contractual",
    "total assets",
    "comprehensive income",
    "per share",
    "total lease cost",
    "deferred tax",
    "property, plant and equipment",
    "shipment volume",
    "total liabilities",
    "earnings per share",
    "quarterly financial",
    "purchase price",
    "total commitments",
    "total other long-term",
    "total obligations",
    "contractual obligations",
    "total stockholders",
    "liabilities assumed",
    "operating lease obligations",
    "total current",
)

_PAREN_SPAN_RE = re.compile(r"\([^)]*\)")


_SUMMARY_CHARGE_VOCAB = (
    "restructur",
    "severance",
    "exit",
    "impairment",
    "termination",
    "charges",
)


def _summary_guard(arm: str, lines_l: list[str], caption_l: str, note_l: str) -> str:
    """The summary form's precision guard: V3 plus the priced
    R-A/R-B recoveries and the C3 extended veto — lead anchor or
    two-charge-type prose, anatomy veto, charge vocabulary."""
    rows_l = "\n".join(lines_l)
    veto_l = _PAREN_SPAN_RE.sub(" ", rows_l)
    if any(marker in veto_l for marker in _SUMMARY_ANATOMY_MARKERS):
        return "competing anatomy"
    head_l = note_l + " " + caption_l
    if not any(word in rows_l for word in _SUMMARY_CHARGE_VOCAB) and not (
        "restructur" in head_l or "exit" in head_l
    ):
        return "no charge vocabulary"
    if arm != "lead" and _charge_type_count(rows_l) < 2:
        return "prose anchor"
    return ""


def _bookends(spec: RestructuringEvidenceSpec, lines_l: list[str], first_line: str):
    """The bookend pair in any filed form, with the forms named."""
    begin_row = any("balance" in ln and "beginning" in ln for ln in lines_l)
    end_row = any(
        "balance" in ln and ("ending" in ln or "end of" in ln) for ln in lines_l
    )
    dated = [ln for ln in lines_l if "balance" in ln and _priced_years(ln)]
    years: set[str] = set()
    months: set[str] = set()
    for ln in dated:
        years.update(_priced_years(ln))
        months.update(name for name in MONTH_NAMES if name in ln)
    anchor_lines = [ln for ln in lines_l if any(a in ln for a in spec.anchors)]
    akeys: set = set()
    for ln in anchor_lines:
        akeys |= _period_keys(ln)
    bare = [ln for ln in lines_l if _starts_with_period(ln)]
    bkeys: set = set()
    for ln in bare:
        bkeys |= _period_keys(ln)
    horiz_keys = _period_keys(first_line)
    if "beginning" in first_line:
        horiz_keys.add("beginning")
    if " end" in first_line:
        horiz_keys.add("end")
    forms = []
    if begin_row and end_row:
        forms.append("word pair")
    if len(dated) >= 2 and (len(years) >= 2 or len(months) >= 2):
        forms.append("dated pair")
    if len(anchor_lines) >= 2 and len(akeys) >= 2:
        forms.append("anchor pair")
    if any("beginning" in ln for ln in anchor_lines) and any(
        "end of" in ln or "ending" in ln for ln in anchor_lines
    ):
        forms.append("anchor word")
    if len(bare) >= 2 and len(bkeys) >= 2:
        forms.append("bare pair")
    if any(a in first_line for a in spec.anchors) and len(horiz_keys) >= 2:
        forms.append("horizontal header")
    forms.extend(_header_forms(spec, lines_l, anchor_lines))
    if any("balance at" in ln for ln in lines_l) and any(
        "charge" in ln for ln in lines_l
    ):
        forms.append("closing balance")
    return forms


def _header_forms(
    spec: RestructuringEvidenceSpec, lines_l: list[str], anchor_lines: list[str]
) -> list[str]:
    """The header-carried bookend forms priced by the depth-2 pass."""
    nonempty = [ln for ln in lines_l if ln.strip()]
    header = nonempty[: spec.header_zone_lines]
    move_terms = [term for _name, terms in spec.move_types for term in terms]
    forms = []
    if any(
        len(_period_keys(ln)) >= 2 and any(term in ln for term in move_terms)
        for ln in header
    ):
        forms.append("dated header")
    if any("beginning" in ln for ln in anchor_lines) and any(
        "remaining" in ln for ln in anchor_lines
    ):
        forms.append("remaining closing")
    if nonempty:
        last = nonempty[-1]
        stripped = last.strip(" |")
        starts = _MONTH_WORD_RE.match(stripped) or _starts_with_numeric_date(stripped)
        if (
            starts
            and any(ch.isdigit() for ch in last)
            and not any("beginning" in ln for ln in lines_l)
        ):
            forms.append("bare closing")
    return forms


def _movement_types(
    spec: RestructuringEvidenceSpec, lines_l: list[str], first_idx: int
) -> set[str]:
    """Distinct movement types over the lines, widened vocabulary."""
    types = set()
    for name, terms in spec.move_types:
        if any(any(term in ln for term in terms) for ln in lines_l):
            types.add(name)
    for term, name in spec.extra_move_terms:
        if any(term in ln for ln in lines_l):
            types.add(name)
    costs_row = any(
        spec.costs_row_term in ln and spec.costs_row_excluded_term not in ln
        for index, ln in enumerate(lines_l)
        if index != first_idx
    )
    if costs_row:
        types.add(spec.costs_row_type)
    return types


def evaluate_restructuring_evidence(
    text: RestructuringText,
    spec: RestructuringEvidenceSpec,
) -> RestructuringEvidence:
    """Evaluate one geometry's text against the family's gate spec."""
    cap_l = text.caption.lower()
    prose_l = text.prose.lower()
    table_text = "\n".join(text.lines)
    lines_l = [ln.lower() for ln in text.lines]
    full_l = (text.caption + " \n " + table_text).lower()
    head_l = (
        text.caption
        + " "
        + text.prose[: spec.head_prose_chars]
        + " "
        + table_text[: spec.head_text_chars]
    ).lower()
    first_line = ""
    first_idx = -1
    for index, ln in enumerate(lines_l):
        if ln.strip():
            first_line = ln
            first_idx = index
            break
    loan = any(
        term in head_l or term in full_l[: spec.loan_full_chars]
        for term in spec.loan_terms
    )
    if loan:
        return RestructuringEvidence(False, "loan context: scope condition")
    terms = spec.subject_terms
    lead = (
        any(term in cap_l for term in terms)
        or _tail_anchor(text.prose, prose_l, terms, spec.prose_tail_chars)
        or any(term in first_line for term in terms)
    )
    prose = _prose_anchor(text.prose, prose_l, terms)
    note_form = any(term in (text.note_title or "").lower() for term in terms)
    if note_form:
        lead = True
    header_form = _charge_type_count(first_line) >= 2 and any(
        "balance at" in ln for ln in lines_l
    )
    if header_form:
        lead = True
    sched_form = any(
        "balance at beginning" in ln and "balance at end" in ln for ln in lines_l
    ) and any(term in ln for term in terms for ln in lines_l)
    if sched_form:
        lead = True
    if not (lead or prose):
        return RestructuringEvidence(False, "subject not anchored")
    forms = _bookends(spec, lines_l, first_line)
    if not forms:
        charges = _charges_signature(lines_l, table_text.lower())
        if charges:
            arm = "prose" if prose and not lead else "lead"
            return RestructuringEvidence(
                True, f"restructuring charges: subject {arm}, {charges}"
            )
        summary = _summary_form(lines_l)
        if summary:
            arm = "prose" if prose and not lead else "lead"
            refusal = _summary_guard(
                arm, lines_l, cap_l, (text.note_title or "").lower()
            )
            if refusal:
                return RestructuringEvidence(False, f"summary form refused: {refusal}")
            return RestructuringEvidence(
                True, f"restructuring summary: subject {arm}, {summary}"
            )
        return RestructuringEvidence(False, "no bookend pair in any filed form")
    types = _movement_types(spec, lines_l, first_idx)
    if not types:
        return RestructuringEvidence(False, "no movement type")
    arm = "prose" if prose and not lead else "lead"
    if header_form and not prose:
        arm = "header"
    detail = (
        f"restructuring walk: subject {arm}, bookends {', '.join(forms)}, "
        f"movements {', '.join(sorted(types))}"
    )
    return RestructuringEvidence(True, detail)


def evaluate_form_test_restructuring(
    table: TypedTable, spec: FormTestSpec
) -> RestructuringEvidence:
    """Stage adapter: evaluate a declared gate spec over a table."""
    gate_spec = RESTRUCTURING_EVIDENCE_SPECS_BY_TEST_ID.get(spec.test_id)
    if gate_spec is None:
        return _REFUSED_NO_SPEC
    return evaluate_restructuring_evidence(
        RestructuringText.from_table(table), gate_spec
    )
