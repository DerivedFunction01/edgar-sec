"""Credit-losses seat: the priced conjunction over one table's text.

Evaluates the seat parameters declared as registry data in
credit_losses_specs.CREDIT_LOSSES_EVIDENCE_SPECS: a rank-1
subject, arm-3 bookends, a movement element, the DA veto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex
from edgar_sec.engine.tables.extraction.specs.families.credit_losses_specs import (
    CREDIT_LOSSES_EVIDENCE_SPECS_BY_TEST_ID,
    CreditLossesEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.date_patterns import (
    ISO_DATE_RE,
    MONTH_PATTERN,
    NUMERIC_DATE_RE,
    ORDINAL_SUFFIX_PATTERN,
    STRICT_MONTH_PATTERN,
    YEAR_TOKEN_PATTERN,
    month_name_to_index,
)

_RE_DATE_FULL = re.compile(
    rf"\b({STRICT_MONTH_PATTERN})\s+\d{{1,2}}(?:{ORDINAL_SUFFIX_PATTERN})?,?\s+"
    rf"({YEAR_TOKEN_PATTERN})\b",
    re.IGNORECASE,
)
_RE_DATE_MY = re.compile(
    rf"\b({STRICT_MONTH_PATTERN})\s+({YEAR_TOKEN_PATTERN})\b", re.IGNORECASE
)
_RE_BARE_END = re.compile(
    rf"allowance[^\n|]*,\s*(?:{STRICT_MONTH_PATTERN})\s+\d{{1,2}}\b", re.IGNORECASE
)
_RE_ASOF_PREP = re.compile(r"(allowance|balance)[^\n|]*\bas of\b", re.IGNORECASE)
_RE_ACLTOK = re.compile(r"(?<![a-z])acl(?![a-z])")
_RE_ALLLTOK = re.compile(r"(?<![a-z])alll(?![a-z])")
_RE_ALL_STUB = re.compile(r"^all\s+(balance|at)\b")
_STUB_PREFIX_ALT = build_alternation(
    ["balance", r"allowance(?:\s+for\s+[a-z ]+?)?", "alll", "acl"],
    sort_longest_first=False,
)
_RE_STUB_DATE = re.compile(
    rf"^{_STUB_PREFIX_ALT}?\s*,?\s*"
    rf"({MONTH_PATTERN})\s+(\d{{1,2}})(?:{ORDINAL_SUFFIX_PATTERN})?\s*,?\s*"
    rf"({YEAR_TOKEN_PATTERN})?$"
)
_RE_SEP = re.compile(r"[|\n]+")


def _stub_text(cell: str) -> str:
    """One stub cell normalized: lowered, collapsed, edge-stripped."""
    return " ".join(str(cell).lower().split()).strip(" ,")


@dataclass(frozen=True, slots=True)
class CreditLossesText:
    """One table's seat text: drawn geometry and prose context."""

    drawn: str = ""
    prose: str = ""
    stubs: tuple[str, ...] = ()
    head_line: str = ""

    @classmethod
    def from_table(cls, table: TypedTable) -> CreditLossesText:
        """Seat text from a typed table: caption, grid, prose_before."""
        context = table.context
        caption = " ".join(context.caption_stack)
        grid = "\n".join("|".join(row) for row in context.rows)
        stubs = tuple(
            _stub_text(row[0]) for row in context.rows if row and str(row[0]).strip()
        )
        head_line = ""
        for row in context.rows:
            if any(str(cell).strip() for cell in row):
                head_line = " | ".join(str(cell) for cell in row).lower()
                break
        return cls(
            drawn=(caption + " \n " + grid).lower(),
            prose=(context.prose_before or "").lower(),
            stubs=stubs,
            head_line=head_line,
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
    stub_pair: bool = False
    token_subject: bool = False
    transposed: bool = False


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


@lru_cache(maxsize=None)
def _spec_index(spec: CreditLossesEvidenceSpec) -> TermIndex:
    """One index over the spec's term census: subject phrases
    by key, bookends, anchors, movement elements, schedule
    markers, carriers. Every entry phrase-kind."""
    entries = []
    entries += [
        TermEntry(phrase, "subject", value=key) for key, phrase in spec.subject_phrases
    ]
    entries += [TermEntry(phrase, "bookend_begin") for phrase in spec.bookend_x_begin]
    entries += [TermEntry(phrase, "bookend_end") for phrase in spec.bookend_x_end]
    entries += [
        TermEntry("beginning", "lit_beginning"),
        TermEntry("ending", "lit_ending"),
        TermEntry("opening balance", "arm_begin_lit"),
        TermEntry("opening allowance", "arm_begin_lit"),
        TermEntry("closing balance", "arm_end_lit"),
    ]
    entries += [TermEntry(word, "anchor") for word in spec.anchor_words]
    for key, terms in spec.movement_elements:
        entries += [TermEntry(term, "element", value=key) for term in terms]
    entries += [
        TermEntry(marker, "schedule_marker") for marker in spec.schedule_markers
    ]
    entries += [
        TermEntry(phrase, "carrier", value=phrase) for phrase in spec.carrier_phrases
    ]
    entries.append(TermEntry(spec.da_phrase, "da"))
    return TermIndex(entries)


def _bookends(drawn: str, spec: CreditLossesEvidenceSpec) -> tuple[bool, bool]:
    """(baseline, arm-3) bookend verdicts over the drawn text."""
    drawn_kinds = set(_spec_index(spec).scan(drawn))
    beginning = "lit_beginning" in drawn_kinds
    ending = "lit_ending" in drawn_kinds
    n_asof = sum(1 for line in drawn.split("|") if _RE_ASOF_PREP.search(line))
    baseline = (
        (beginning and ending) or n_asof >= 2 or _RE_BARE_END.search(drawn) is not None
    )
    segments = _RE_SEP.split(drawn)
    arm1 = (
        beginning or "bookend_begin" in drawn_kinds or "arm_begin_lit" in drawn_kinds
    ) and (ending or "bookend_end" in drawn_kinds or "arm_end_lit" in drawn_kinds)
    asof_dates: set[tuple[int, int]] = set()
    anchored_dates: set[tuple[int, int]] = set()
    for segment in segments:
        keys = _dates_in(segment)
        if not keys:
            continue
        if _RE_ASOF_PREP.search(segment):
            asof_dates |= keys
        if "anchor" in _spec_index(spec).scan(segment):
            anchored_dates |= keys
    arm3 = arm1 or len(asof_dates) >= 2 or len(anchored_dates) >= 2
    return baseline, arm3


def _movement(drawn: str, spec: CreditLossesEvidenceSpec) -> bool:
    """Movement: one element, or a Schedule II valuation marker."""
    hits = _spec_index(spec).scan(drawn)
    element_keys = hits.get("element", frozenset())
    elements = {key: key in element_keys for key, _terms in spec.movement_elements}
    n_base = sum(elements[key] for key in spec.movement_base_keys)
    moves_ext = n_base >= 1 or any(elements[key] for key in spec.movement_ext_keys)
    schedule = "schedule_marker" in hits or any(
        elements[key] for key in spec.schedule_keys
    )
    return moves_ext or schedule


def _stub_pair(text: CreditLossesText) -> bool:
    """Dated-stub bookends: two distinct (month, day) stub keys."""
    keys: set[tuple[int, int]] = set()
    for stub in text.stubs:
        match = _RE_STUB_DATE.match(stub)
        if match:
            index = month_name_to_index(match.group(1))
            if index is not None:
                keys.add((index, int(match.group(2))))
    return len(keys) >= 2


def _token_subject(text: CreditLossesText) -> bool:
    """Abbreviation-carried subject: ALLL token or ALL stub."""
    if _RE_ALLLTOK.search(text.drawn):
        return True
    return any(_RE_ALL_STUB.match(stub) for stub in text.stubs)


def legs_for(
    text: CreditLossesText, spec: CreditLossesEvidenceSpec
) -> CreditLossesLegs:
    """Every leg of the priced claim over one table's text."""
    drawn, prose = text.drawn, text.prose
    index = _spec_index(spec)
    subjects = set(index.scan(drawn).get("subject", frozenset()))
    r1 = bool(subjects & set(spec.r1_keys))
    bare = spec.bare_key in subjects
    acltok = _RE_ACLTOK.search(drawn) is not None
    collapsed = _RE_SEP.sub(" ", drawn)
    carrier = bool(index.scan(prose).get("carrier", frozenset())) or bool(
        index.scan(collapsed).get("carrier", frozenset())
        - index.scan(drawn).get("carrier", frozenset())
    )
    subject = r1 or bare or acltok or carrier
    baseline, arm3 = _bookends(drawn, spec)
    movement = _movement(drawn, spec)
    vetoed = (
        carrier
        and not (r1 or bare or acltok)
        and ("da" in index.scan(drawn) or "da" in index.scan(prose))
    )
    stub_pair = _stub_pair(text)
    token_subject = _token_subject(text)
    transposed = len(_dates_in(text.head_line)) >= 2
    claim = subject and arm3 and movement and not vetoed
    claim = claim or (subject and movement and not vetoed and stub_pair)
    claim = claim or (
        token_subject and movement and not vetoed and (arm3 or transposed)
    )
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
        stub_pair=stub_pair,
        token_subject=token_subject,
        transposed=transposed,
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
        if legs.subject and legs.bookends_arm3 and legs.movement and not legs.vetoed:
            return CreditLossesEvidence(
                True, "subject + arm-3 bookends + movement, no DA veto"
            )
        if legs.token_subject:
            via = "arm-3 bookends" if legs.bookends_arm3 else "transposed bookends"
            return CreditLossesEvidence(
                True, f"token subject + {via} + movement, no DA veto"
            )
        return CreditLossesEvidence(
            True, "subject + dated-stub bookends + movement, no DA veto"
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
