"""Credit-losses seat: the priced conjunction over one table's text.

Evaluates the seat parameters declared as registry data in
credit_losses_specs.CREDIT_LOSSES_EVIDENCE_SPECS: a rank-1
subject, arm-3 bookends, a movement element, the DA veto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.credit_losses_specs import (
    CREDIT_LOSSES_EVIDENCE_SPECS_BY_TEST_ID,
    CreditLossesEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.form_test_specs import FormTestSpec
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import (
    ISO_DATE_RE,
    MONTH_NAMES,
    NUMERIC_DATE_RE,
    YEAR_TOKEN_PATTERN,
    month_name_to_index,
)

_MONTH_ALT = build_alternation(MONTH_NAMES, auto_escape=True, compact=True)
_ORDINAL_ALT = build_alternation(["st", "nd", "rd", "th"], auto_escape=True)
_RE_DATE_FULL = re.compile(
    rf"\b({_MONTH_ALT})\s+\d{{1,2}}(?:{_ORDINAL_ALT})?,?\s+"
    rf"({YEAR_TOKEN_PATTERN})\b",
    re.IGNORECASE,
)
_RE_DATE_MY = re.compile(rf"\b({_MONTH_ALT})\s+({YEAR_TOKEN_PATTERN})\b", re.IGNORECASE)
_RE_BARE_END = re.compile(
    rf"allowance[^\n|]*,\s*(?:{_MONTH_ALT})\s+\d{{1,2}}\b", re.IGNORECASE
)
_RE_ASOF_PREP = re.compile(r"(allowance|balance)[^\n|]*\bas of\b", re.IGNORECASE)
_RE_ACLTOK = re.compile(r"(?<![a-z])acl(?![a-z])")
_RE_SEP = re.compile(r"[|\n]+")


@dataclass(frozen=True, slots=True)
class CreditLossesText:
    """One table's seat text: drawn geometry and prose context."""

    drawn: str = ""
    prose: str = ""

    @classmethod
    def from_table(cls, table: TypedTable) -> CreditLossesText:
        """Seat text from a typed table: caption, grid, prose_before."""
        context = table.context
        caption = " ".join(context.caption_stack)
        grid = "\n".join("|".join(row) for row in context.rows)
        return cls(
            drawn=(caption + " \n " + grid).lower(),
            prose=(context.prose_before or "").lower(),
        )


@dataclass(frozen=True, slots=True)
class CreditLossesLegs:
    """The seat's leg verdicts for one table under one spec."""

    r1: bool
    bare: bool
    acltok: bool
    carrier: bool
    subject: bool
    bookends_baseline: bool
    bookends_arm3: bool
    movement: bool
    vetoed: bool
    claim: bool


def _dates_in(segment: str) -> set[tuple[int, int]]:
    """(year, month) keys in one segment, the priced date shapes."""
    out: set[tuple[int, int]] = set()
    for match in _RE_DATE_FULL.finditer(segment):
        index = month_name_to_index(match.group(1))
        if index is not None:
            out.add((int(match.group(2)), index))
    for match in _RE_DATE_MY.finditer(segment):
        index = month_name_to_index(match.group(1))
        if index is not None:
            out.add((int(match.group(2)), index))
    for match in NUMERIC_DATE_RE.finditer(segment):
        parts = match.group(0).split("/")
        if len(parts) == 3 and len(parts[2]) == 4:
            out.add((int(parts[2]), int(parts[0])))
    for match in ISO_DATE_RE.finditer(segment):
        year, month, _day = match.group(0).split("-")
        out.add((int(year), int(month)))
    return out


def _bookends(drawn: str, spec: CreditLossesEvidenceSpec) -> tuple[bool, bool]:
    """(baseline, arm-3) bookend verdicts over the drawn text."""
    beginning = "beginning" in drawn
    ending = "ending" in drawn
    n_asof = sum(1 for line in drawn.split("|") if _RE_ASOF_PREP.search(line))
    baseline = (
        (beginning and ending) or n_asof >= 2 or _RE_BARE_END.search(drawn) is not None
    )
    segments = _RE_SEP.split(drawn)
    arm1 = (
        beginning
        or any(phrase in drawn for phrase in spec.bookend_x_begin)
        or "opening balance" in drawn
        or "opening allowance" in drawn
    ) and (
        ending
        or any(phrase in drawn for phrase in spec.bookend_x_end)
        or "closing balance" in drawn
    )
    asof_dates: set[tuple[int, int]] = set()
    anchored_dates: set[tuple[int, int]] = set()
    for segment in segments:
        keys = _dates_in(segment)
        if not keys:
            continue
        if _RE_ASOF_PREP.search(segment):
            asof_dates |= keys
        if any(word in segment for word in spec.anchor_words):
            anchored_dates |= keys
    arm3 = arm1 or len(asof_dates) >= 2 or len(anchored_dates) >= 2
    return baseline, arm3


def _movement(drawn: str, spec: CreditLossesEvidenceSpec) -> bool:
    """Movement: one element, or a Schedule II valuation marker."""
    elements = {
        key: any(term in drawn for term in terms)
        for key, terms in spec.movement_elements
    }
    n_base = sum(elements[key] for key in spec.movement_base_keys)
    moves_ext = n_base >= 1 or any(elements[key] for key in spec.movement_ext_keys)
    schedule = any(marker in drawn for marker in spec.schedule_markers) or any(
        elements[key] for key in spec.schedule_keys
    )
    return moves_ext or schedule


def legs_for(
    text: CreditLossesText, spec: CreditLossesEvidenceSpec
) -> CreditLossesLegs:
    """Every leg of the priced claim over one table's text."""
    drawn, prose = text.drawn, text.prose
    subjects = {key for key, phrase in spec.subject_phrases if phrase in drawn}
    r1 = bool(subjects & set(spec.r1_keys))
    bare = spec.bare_key in subjects
    acltok = _RE_ACLTOK.search(drawn) is not None
    collapsed = _RE_SEP.sub(" ", drawn)
    carrier = any(phrase in prose for phrase in spec.carrier_phrases) or any(
        phrase in collapsed and phrase not in drawn for phrase in spec.carrier_phrases
    )
    subject = r1 or bare or acltok or carrier
    baseline, arm3 = _bookends(drawn, spec)
    movement = _movement(drawn, spec)
    vetoed = (
        carrier
        and not (r1 or bare or acltok)
        and (spec.da_phrase in drawn or spec.da_phrase in prose)
    )
    claim = subject and arm3 and movement and not vetoed
    return CreditLossesLegs(
        r1=r1,
        bare=bare,
        acltok=acltok,
        carrier=carrier,
        subject=subject,
        bookends_baseline=baseline,
        bookends_arm3=arm3,
        movement=movement,
        vetoed=vetoed,
        claim=claim,
    )


@dataclass(frozen=True, slots=True)
class CreditLossesEvidence:
    """The seat verdict for one table under one family's spec."""

    admitted: bool
    detail: str


def evaluate_credit_losses_evidence(
    text: CreditLossesText, spec: CreditLossesEvidenceSpec
) -> CreditLossesEvidence:
    """The priced conjunction, returned as the seat's verdict."""
    legs = legs_for(text, spec)
    if legs.claim:
        return CreditLossesEvidence(
            True, "subject + arm-3 bookends + movement, no DA veto"
        )
    failed = [
        name
        for name, ok in (
            ("subject", legs.subject),
            ("arm-3 bookends", legs.bookends_arm3),
            ("movement", legs.movement),
        )
        if not ok
    ]
    if legs.vetoed:
        failed.append("DA veto")
    return CreditLossesEvidence(False, "no claim: " + ", ".join(failed))


def evaluate_form_test_credit_losses(
    table: TypedTable, spec: FormTestSpec
) -> CreditLossesEvidence:
    """Form-test stage adapter: resolve the seat spec, evaluate."""
    seat_spec = CREDIT_LOSSES_EVIDENCE_SPECS_BY_TEST_ID.get(spec.test_id)
    if seat_spec is None:
        return CreditLossesEvidence(False, "no credit-losses seat spec for test")
    return evaluate_credit_losses_evidence(
        CreditLossesText.from_table(table), seat_spec
    )
