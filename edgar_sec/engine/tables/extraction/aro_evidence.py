"""ARO evidence gate: the priced ASC 410-20 seat rule.
Subject (S2), bookend pair (F2e), movement (M1) and the subject
exclusion (not-X) over row lines, per the adjudication base."""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.aro_evidence_specs import (
    ARO_EVIDENCE_SPECS_BY_TEST_ID,
    AroEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.form_test_specs import FormTestSpec
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import (
    MONTH_NAMES,
    NUMERIC_DATE_RE,
    YEAR_TOKEN_SEARCH_RE,
)

_MONTH_TOKEN_RE = re.compile(
    rf"\b(?:{build_alternation(MONTH_NAMES, auto_escape=True, compact=True)})\b"
)
_ABBREVIATION_RE = re.compile(r"\baros?\b")
_PROSE_TAIL = 400


@dataclass(frozen=True, slots=True)
class AroText:
    """One table's ARO evidence surface: caption, prose, row lines.
    The packet construction of record: caption stack joined with
    spaces, prose as carried, grid rows joined with " | "."""

    caption: str
    prose: str
    lines: tuple[str, ...]

    @classmethod
    def from_table(cls, table: TypedTable) -> AroText:
        """The evidence surface from a typed table's context."""
        context = table.context
        return cls(
            caption=" ".join(context.caption_stack),
            prose=context.prose_before,
            lines=tuple(" | ".join(str(cell) for cell in row) for row in context.rows),
        )


@dataclass(frozen=True, slots=True)
class AroVerdict:
    """The gate's verdict over one table: admitted, leg detail."""

    admitted: bool
    detail: str


def _lower_lines(text: AroText) -> tuple[str, ...]:
    """The row lines lowercased: the surface every leg reads."""
    return tuple(line.lower() for line in text.lines)


def _windows(text: AroText) -> tuple[str, str, str]:
    """The subject windows: caption, prose tail, first row line."""
    first = next((ln for ln in _lower_lines(text) if ln.strip()), "")
    return (text.caption.lower(), text.prose.lower()[-_PROSE_TAIL:], first)


def _years(line: str) -> list[str]:
    """Year tokens on a line, the priced 19xx/20xx shape only."""
    return [
        year for year in YEAR_TOKEN_SEARCH_RE.findall(line) if year[:2] in ("19", "20")
    ]


def _months(line: str) -> list[str]:
    """Full month names on a line, the priced grammar."""
    return [match.group(0) for match in _MONTH_TOKEN_RE.finditer(line)]


def _numeric_dates(line: str) -> list[str]:
    """Numeric dates on a line, the priced slash-separated shape."""
    return [d for d in NUMERIC_DATE_RE.findall(line) if d.count("/") == 2]


def _period_keys(line: str) -> set[tuple[str, str]]:
    """Period keys on one line: years, month names, numeric dates."""
    keys = {("y", year) for year in _years(line)}
    keys.update(("m", month) for month in _months(line))
    keys.update(("d", date) for date in _numeric_dates(line))
    return keys


def _opens_with_period(stripped: str) -> bool:
    """A bare dated line: opens with a month, year, or numeric date."""
    if _MONTH_TOKEN_RE.match(stripped):
        return True
    year = YEAR_TOKEN_SEARCH_RE.match(stripped)
    if year is not None and year.group(0)[:2] in ("19", "20"):
        return True
    date = NUMERIC_DATE_RE.match(stripped)
    return date is not None and date.group(0).count("/") == 2


def subject_lead(text: AroText, spec: AroEvidenceSpec) -> bool:
    """S_lead: the subject phrase in a subject window."""
    return any(spec.subject_phrase in window for window in _windows(text))


def subject2(text: AroText, spec: AroEvidenceSpec) -> bool:
    """S2: lead, abbreviation, full-prose, or bookend-row subject."""
    if subject_lead(text, spec):
        return True
    if any(_ABBREVIATION_RE.search(w) for w in _windows(text)):
        return True
    prose = text.prose.lower()
    if spec.subject_phrase in prose or _ABBREVIATION_RE.search(prose):
        return True
    return any(
        any(marker in line for marker in spec.bookend_markers)
        and (spec.subject_phrase in line or _ABBREVIATION_RE.search(line) is not None)
        for line in _lower_lines(text)
    )


def bookend_f2(text: AroText, spec: AroEvidenceSpec) -> bool:
    """F2: a beginning/ending pair in any priced surface form."""
    lines = _lower_lines(text)
    book_word = any("balance" in ln and "beginning" in ln for ln in lines) and any(
        "balance" in ln and ("ending" in ln or "end of" in ln) for ln in lines
    )
    dated = [ln for ln in lines if "balance" in ln and _years(ln)]
    years = {year for ln in dated for year in _years(ln)}
    months = {name for ln in dated for name in MONTH_NAMES if name in ln}
    book_date = len(dated) >= 2 and (len(years) >= 2 or len(months) >= 2)
    anchors = [ln for ln in lines if any(a in ln for a in spec.anchor_terms)]
    akeys: set[tuple[str, str]] = set()
    for ln in anchors:
        akeys |= _period_keys(ln)
    anchor_pair = len(anchors) >= 2 and len(akeys) >= 2
    anchor_word = any("beginning" in ln for ln in anchors) and any(
        "end of" in ln or "ending" in ln for ln in anchors
    )
    bare = [ln for ln in lines if _opens_with_period(ln.strip(" |"))]
    bkeys: set[tuple[str, str]] = set()
    for ln in bare:
        bkeys |= _period_keys(ln)
    bare_pair = len(bare) >= 2 and len(bkeys) >= 2
    first = _windows(text)[2]
    horiz = any(a in first for a in spec.anchor_terms) and (
        len(
            _period_keys(first)
            | ({"beginning"} if "beginning" in first else set())
            | ({"end"} if " end" in first else set())
        )
        >= 2
    )
    return book_word or book_date or anchor_pair or anchor_word or bare_pair or horiz


def _carrying_pair(lines: tuple[str, ...], spec: AroEvidenceSpec) -> bool:
    """The carrying-amount pair: begin/end markers, distinct rows."""
    begins = [
        i
        for i, ln in enumerate(lines)
        if spec.carrying_phrase in ln and ("beginning" in ln or "opening" in ln)
    ]
    ends = [
        i
        for i, ln in enumerate(lines)
        if spec.carrying_phrase in ln
        and ("ending" in ln or "end of" in ln or "closing" in ln)
    ]
    return any(b != e for b in begins for e in ends)


def bookend_f2c(text: AroText, spec: AroEvidenceSpec) -> bool:
    """F2c: F2, or the carrying-amount bookend pair."""
    return bookend_f2(text, spec) or _carrying_pair(_lower_lines(text), spec)


def bare_bookend(text: AroText, spec: AroEvidenceSpec) -> bool:
    """B: the bare period-label pair (the depth-3 element)."""
    lines = _lower_lines(text)

    def _bare(line: str, markers: tuple[str, ...]) -> bool:
        return (
            any(marker in line for marker in markers)
            and spec.bare_period_term in line
            and not any(term in line for term in spec.bare_excluded_terms)
        )

    begins = [i for i, ln in enumerate(lines) if _bare(ln, spec.bare_begin_markers)]
    ends = [i for i, ln in enumerate(lines) if _bare(ln, spec.bare_end_markers)]
    return any(b != e for b in begins for e in ends)


def bookend_f2d(text: AroText, spec: AroEvidenceSpec) -> bool:
    """F2d: F2c, or the bare period-label bookend pair."""
    return bookend_f2c(text, spec) or bare_bookend(text, spec)


def dated_subject_d(text: AroText, spec: AroEvidenceSpec) -> bool:
    """D: two dated subject lines spanning two period keys."""
    keys: set[tuple[str, str]] = set()
    dated = 0
    for line in _lower_lines(text):
        if spec.subject_phrase not in line and not _ABBREVIATION_RE.search(line):
            continue
        if not ((_months(line) and _years(line)) or _numeric_dates(line)):
            continue
        dated += 1
        keys |= _period_keys(line)
    return dated >= 2 and len(keys) >= 2


def bookend_f2e(text: AroText, spec: AroEvidenceSpec) -> bool:
    """F2e: F2d, or the dated subject-named bookend pair."""
    return bookend_f2d(text, spec) or dated_subject_d(text, spec)


def movement_types(text: AroText, spec: AroEvidenceSpec) -> tuple[str, ...]:
    """The ASC 410-20-50-1(c) movement types present, priced order."""
    lines = _lower_lines(text)
    return tuple(
        name
        for name, terms in spec.movement_types
        if any(term in line for line in lines for term in terms)
    )


def exclusion_x(text: AroText, spec: AroEvidenceSpec) -> bool:
    """X: standardized-measure or exploratory subject evidence."""
    terms = (*spec.standardized_terms, *spec.well_cost_terms)
    return any(term in window for window in _windows(text) for term in terms)


def aro_legs(text: AroText, spec: AroEvidenceSpec) -> dict[str, bool | tuple[str, ...]]:
    """Every priced leg and chassis cell, for reproduction."""
    types = movement_types(text, spec)
    lead = subject_lead(text, spec)
    f2 = bookend_f2(text, spec)
    f2c = f2 or _carrying_pair(_lower_lines(text), spec)
    bare = bare_bookend(text, spec)
    f2d = f2c or bare
    dated = dated_subject_d(text, spec)
    subj = subject2(text, spec)
    excluded = exclusion_x(text, spec)
    m1 = len(types) >= 1
    return {
        "subject_lead": lead,
        "subject2": subj,
        "bookend_f2": f2,
        "bookend_f2c": f2c,
        "bare_bookend": bare,
        "bookend_f2d": f2d,
        "dated_subject_d": dated,
        "bookend_f2e": f2d or dated,
        "movement_types": types,
        "m1": m1,
        "m2": len(types) >= 2,
        "accretion": "accretion" in types,
        "exclusion_x": excluded,
        "core2": lead and f2 and len(types) >= 2,
        "core2_m1": lead and f2 and m1,
        "lac": lead and "accretion" in types,
        "claim_f2c": subj and f2c and m1 and not excluded,
        "claim_f2d": subj and f2d and m1 and not excluded,
        "claim": subj and (f2d or dated) and m1 and not excluded,
    }


def evaluate_aro_evidence(text: AroText, spec: AroEvidenceSpec) -> AroVerdict:
    """The priced seat rule: S2 and F2e and M1 and not X."""
    legs = aro_legs(text, spec)
    if legs["claim"]:
        return AroVerdict(True, "aro walk: subject, bookend pair, movement")
    failed = [
        name
        for name, key in (
            ("subject", "subject2"),
            ("bookend pair", "bookend_f2e"),
            ("movement", "m1"),
        )
        if not legs[key]
    ]
    if legs["exclusion_x"]:
        failed.append("subject exclusion")
    return AroVerdict(False, "aro evidence refused: " + ", ".join(failed))


def evaluate_form_test_aro(table: TypedTable, spec: FormTestSpec) -> AroVerdict:
    """Stage adapter: price the family's gate over a typed table."""
    params = ARO_EVIDENCE_SPECS_BY_TEST_ID[spec.test_id]
    return evaluate_aro_evidence(AroText.from_table(table), params)
