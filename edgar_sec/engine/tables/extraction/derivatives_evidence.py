"""Derivatives-evidence gate: U/A evidence over one geometry's text.

Evaluates the gate parameters declared as registry data in
form_test_specs.DERIVATIVES_EVIDENCE_SPECS; a claim requires
underlying/notional or accounting-effects evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from edgar_sec.engine.tables.extraction.leadin_segmentation import leadin_segment
from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.form_test_specs import (
    DERIVATIVES_EVIDENCE_SPECS,
    DERIVATIVES_EVIDENCE_SPECS_BY_TEST_ID,
    DerivativesEvidenceSpec,
    FormTestSpec,
)
from edgar_sec.engine.tables.extraction.typed_rows import RowKind, TypedTable
from edgar_sec.foundation.text.dates import MONTH_WORD_RE, YEAR_TOKEN_SEARCH_RE


def _is_period_label(label: str) -> bool:
    """A stub label naming a period: a month range or a dated month."""
    months = MONTH_WORD_RE.findall(label)
    return len(months) >= 2 or (
        bool(months) and YEAR_TOKEN_SEARCH_RE.search(label) is not None
    )


_FORWARD_LOOKING = ("forward-looking", "forward looking")
_INSTRUMENT_ROW_BASES = ("swap", "swaps", "forward", "forwards", "futures")
_COMMODITY_EFFECTS = ("unrealized", "gain/loss", "(gain)/loss")


@lru_cache(maxsize=None)
def _term_pattern(term: str) -> re.Pattern[str]:
    """One term's word-boundary pattern, compiled once per term."""
    return re.compile(r"\b" + re.escape(term) + r"\b")


def _present(term: str, text: str) -> bool:
    if " " in term or "-" in term:
        return term in text
    return _term_pattern(term).search(text) is not None


@dataclass(frozen=True, slots=True)
class DerivativesText:
    """One geometry's gate text: framing, stub labels, grid cells."""

    caption: str = ""
    notehead: str = ""
    lead_title: str = ""
    leadin: str = ""
    stubs: tuple[str, ...] = ()
    headers: tuple[str, ...] = ()
    grid: tuple[str, ...] = ()

    @property
    def subject(self) -> str:
        """Framing plus stub and header text: the table's subject."""
        parts = (
            self.caption,
            self.notehead,
            self.lead_title,
            *self.stubs,
            *self.headers,
        )
        return normalize_text(" ".join(part for part in parts if part))

    @property
    def evidence(self) -> str:
        """Subject plus every grid cell: the geometry's own text."""
        return normalize_text(self.subject + " " + " ".join(self.grid))

    @classmethod
    def from_geometry(cls, geometry) -> DerivativesText:
        """Gate text from a competition GeometryText (duck-typed)."""
        stubs = tuple(normalize_text(stub) for stub in geometry.stubs)
        return cls(
            caption=normalize_text(geometry.caption),
            notehead=normalize_text(geometry.notehead),
            lead_title=normalize_text(geometry.lead_title),
            leadin=normalize_text(geometry.leadin),
            stubs=stubs,
            headers=tuple(
                normalize_text(cell) for cell in getattr(geometry, "headers", ())
            ),
            grid=stubs,
        )

    @classmethod
    def from_table(cls, table: TypedTable) -> DerivativesText:
        """Gate text from a typed table: framing plus the full grid."""
        from edgar_sec.engine.tables.extraction.competition import (
            geometry_text_from_table,
        )

        geometry = geometry_text_from_table(table, evaluate_stage=False)
        context = table.context
        consumed = table.caption.consumed_rows
        first_data = next(
            (i for i, row in enumerate(table.rows) if row.kind is RowKind.DATA),
            len(table.rows),
        )
        zone = max(consumed + table.header_rows, consumed + first_data)
        headers = tuple(
            normalize_text(cell)
            for row in context.rows[:zone]
            for cell in row
            if cell.strip()
        )
        grid = tuple(
            normalize_text(cell) for row in context.rows for cell in row if cell.strip()
        )
        return cls(
            caption=normalize_text(geometry.caption),
            notehead=normalize_text(geometry.notehead),
            lead_title=normalize_text(geometry.lead_title),
            leadin=normalize_text(geometry.leadin),
            stubs=tuple(normalize_text(stub) for stub in geometry.stubs),
            headers=headers,
            grid=grid,
        )


@dataclass(frozen=True, slots=True)
class DerivativesEvidence:
    """The gate verdict for one geometry under one family's spec."""

    admitted: bool
    evidence_class: str
    strong: bool
    detail: str


_REFUSED_N = DerivativesEvidence(False, "N", False, "no U/A evidence")


def _base_in_lines(base: str, lines: tuple[str, ...]) -> bool:
    return any(_present(base, line) for line in lines)


def _unambiguous(
    spec: DerivativesEvidenceSpec, lines: tuple[str, ...]
) -> tuple[str, ...]:
    """Unambiguous bases present, with the forward guards applied."""
    found = []
    for base in spec.unambiguous_bases:
        if base not in ("forward", "forwards"):
            if _base_in_lines(base, lines):
                found.append(base)
            continue
        for line in lines:
            if not _present(base, line):
                continue
            if any(phrase in line for phrase in _FORWARD_LOOKING):
                continue
            if any(_present(term, line) for term in spec.commercial_terms):
                continue
            found.append(base)
            break
    return tuple(found)


def _ambiguous(spec: DerivativesEvidenceSpec, lines: tuple[str, ...]) -> frozenset[str]:
    """Distinct ambiguous bases, equity-prefixed ones discounted.

    A prefixed base counts only inside a triple on its own line:
    the suffix-lookbehind rule of the design algebra.
    """
    found: set[str] = set()
    for line in lines:
        bases = {base for base in spec.ambiguous_bases if _present(base, line)}
        for stem, base in spec.stem_bases:
            if stem in line:
                bases.add(base)
        if len(bases) < 3:
            for prefix in spec.equity_prefixes:
                for base in list(bases):
                    if f"{prefix} {base}" in line:
                        bases.discard(base)
        found.update(bases)
    return frozenset(found)


def _instrument_row(spec: DerivativesEvidenceSpec, stubs: tuple[str, ...]) -> bool:
    """A stub label naming an instrument, not an income-statement line."""
    for label in stubs:
        if "related to" in label:
            continue
        if any(_present(base, label) for base in _INSTRUMENT_ROW_BASES):
            return True
    return False


def evaluate_derivatives_evidence(
    text: DerivativesText,
    spec: DerivativesEvidenceSpec,
) -> DerivativesEvidence:
    """Evaluate one geometry's text against the family's gate spec."""
    subject = text.subject
    evidence = text.evidence
    lines = (text.caption, text.notehead, text.lead_title, *text.stubs, *text.headers)
    grid_lines = (*lines, *text.grid)
    unamb_subject = _unambiguous(spec, lines)
    unamb_grid = _unambiguous(spec, grid_lines)
    unamb_leadin = _unambiguous(spec, (text.leadin,))
    amb = _ambiguous(spec, lines)
    designation = tuple(
        phrase for phrase in spec.designation_phrases if phrase in subject
    )
    designation_leadin = tuple(
        phrase for phrase in spec.designation_phrases if phrase in text.leadin
    )
    anchors = tuple(term for term in spec.anchor_terms if term in evidence)
    aoci_subject = any(
        phrase in text.caption + " " + text.lead_title + " " + " ".join(text.stubs[:3])
        for phrase in spec.aoci_subject_phrases
    )
    if (
        aoci_subject
        and "notional" not in evidence
        and not _instrument_row(spec, text.stubs)
    ):
        return DerivativesEvidence(
            False, "E", False, "aoci-components subject: equity carve-out"
        )
    comp = any(term in evidence + " " + text.leadin for term in spec.equity_comp_terms)
    if comp and not unamb_grid and not designation:
        return DerivativesEvidence(
            False, "E", False, "equity-compensation evidence only"
        )
    npns = any(phrase in evidence + " " + text.leadin for phrase in spec.npns_phrases)
    nonforward = tuple(
        base for base in unamb_grid if base not in ("forward", "forwards")
    )
    if npns and not nonforward and not designation and len(amb) < 2:
        return DerivativesEvidence(False, "C", False, "npns exclusion")
    period_rows = sum(1 for stub in text.stubs if _is_period_label(stub))
    listing = bool(unamb_grid) and period_rows >= spec.min_period_rows
    if unamb_grid:
        strong = bool(unamb_subject) or listing
        return DerivativesEvidence(
            True, "U", strong, "unambiguous: " + ", ".join(unamb_grid)
        )
    if designation:
        return DerivativesEvidence(
            True, "A", True, "designation: " + ", ".join(designation)
        )
    suffix = any(
        any(_present(base, line) for base in amb)
        and any(_present(term, line) for term in spec.suffix_terms)
        for line in lines
    )
    if len(amb) >= 2:
        return DerivativesEvidence(
            True, "A", False, "ambiguous dual: " + ", ".join(sorted(amb))
        )
    if amb and suffix:
        return DerivativesEvidence(
            True, "A", False, "ambiguous + suffix: " + ", ".join(sorted(amb))
        )
    if amb and anchors:
        return DerivativesEvidence(
            True, "A", True, "ambiguous + anchor: " + ", ".join(anchors)
        )
    offsetting = any(phrase in subject for phrase in spec.offsetting_phrases) and (
        bool(designation)
        or "financial instruments" in subject
        or "financial assets" in subject
    )
    if offsetting:
        return DerivativesEvidence(True, "A", True, "offsetting form")
    effects = any(phrase in subject for phrase in spec.effects_phrases) or any(
        phrase in text.leadin for phrase in spec.effects_leadin_phrases
    )
    if effects:
        return DerivativesEvidence(True, "A", True, "asc 815 effects form")
    anchor_kinds = ("notional" in subject) + (
        "fair value" in subject or "fair market value" in subject
    )
    if anchor_kinds >= 2 and "contract" in evidence + " " + text.leadin:
        return DerivativesEvidence(
            True, "A", True, "position anchors: notional + fair value"
        )
    if spec.commodity_header in subject and any(
        term in subject for term in _COMMODITY_EFFECTS
    ):
        return DerivativesEvidence(
            True, "A", False, "commodity contracts, accounting effects"
        )
    if designation_leadin and anchors:
        return DerivativesEvidence(
            True,
            "A",
            False,
            "designation in leadin + anchor: " + ", ".join(designation_leadin),
        )
    if unamb_leadin and "contracts" in " ".join(text.stubs):
        return DerivativesEvidence(
            True, "C", False, "contract volumes on context: " + ", ".join(unamb_leadin)
        )
    return _REFUSED_N


def derivatives_evidence_for_geometry(
    geometry, family: str = "derivatives_hedging"
) -> DerivativesEvidence:
    """The gate verdict for one competition geometry, by family."""
    spec = DERIVATIVES_EVIDENCE_SPECS.get(family)
    if spec is None:
        return _REFUSED_N
    return evaluate_derivatives_evidence(DerivativesText.from_geometry(geometry), spec)


@dataclass(frozen=True, slots=True)
class DerivativesSubject:
    """The rank-1 subject verdict for one geometry."""

    subject: bool
    detail: str


_NO_SUBJECT = DerivativesSubject(False, "no subject evidence in framing")
_SUBJECT_ANCHORS = ("notional", "risk management")


def _subject_framing(text: DerivativesText, leadin: str) -> tuple[str, ...]:
    """Framing lines: caption, headers, the lead-in's final paragraph.

    The lead title and the notehead are not framing.
    """
    segment = leadin_segment(leadin or "")
    paragraphs = [line for line in segment.split("\n") if line.strip()]
    final = normalize_text(paragraphs[-1]) if paragraphs else ""
    return tuple(part for part in (text.caption, final, *text.headers) if part)


def derivatives_subject_for_geometry(
    geometry, family: str = "derivatives_hedging"
) -> DerivativesSubject:
    """Rank-1 core verdict: a derivative subject in the framing.

    A1: a spec base, designation phrase, hedge stem, or anchor in
    the framing. A2: offsetting framing plus instrument rows.
    """
    spec = DERIVATIVES_EVIDENCE_SPECS.get(family)
    if spec is None:
        return _NO_SUBJECT
    text = DerivativesText.from_geometry(geometry)
    lines = _subject_framing(text, geometry.leadin or "")
    framing = " ".join(lines)
    unambiguous = _unambiguous(spec, lines)
    if unambiguous:
        return DerivativesSubject(True, "subject: " + ", ".join(unambiguous))
    designation = tuple(p for p in spec.designation_phrases if p in framing)
    if designation:
        return DerivativesSubject(True, "subject: " + ", ".join(designation))
    if "hedg" in framing:
        return DerivativesSubject(True, "subject: hedging")
    anchors = tuple(term for term in _SUBJECT_ANCHORS if term in framing)
    if anchors:
        return DerivativesSubject(True, "subject: " + ", ".join(anchors))
    if any(phrase in framing for phrase in spec.offsetting_phrases) and (
        _instrument_row(spec, text.stubs)
    ):
        return DerivativesSubject(True, "subject: offsetting form")
    return _NO_SUBJECT


def evaluate_form_test_derivatives(
    table: TypedTable, spec: FormTestSpec
) -> DerivativesEvidence:
    """Stage adapter: evaluate a declared gate spec over a table."""
    gate_spec = DERIVATIVES_EVIDENCE_SPECS_BY_TEST_ID.get(spec.test_id)
    if gate_spec is None:
        return _REFUSED_N
    return evaluate_derivatives_evidence(DerivativesText.from_table(table), gate_spec)
