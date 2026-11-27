"""Derivatives-evidence gate: U/A evidence over one geometry's text.

Evaluates the gate parameters declared as registry data in
derivatives_evidence_specs.DERIVATIVES_EVIDENCE_SPECS; a claim
requires underlying/notional or accounting-effects evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from edgar_sec.engine.tables.extraction.cascade.leadin_segmentation import (
    leadin_segment,
)
from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.specs.families.derivatives_evidence_specs import (
    DERIVATIVES_EVIDENCE_SPECS,
    DERIVATIVES_EVIDENCE_SPECS_BY_TEST_ID,
    DerivativesEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.core.typed_rows import RowKind, TypedTable
from edgar_sec.foundation.text.date_patterns import MONTH_WORD_RE, YEAR_TOKEN_SEARCH_RE


def _is_period_label(label: str) -> bool:
    """A stub label naming a period: a month range or a dated month."""
    months = MONTH_WORD_RE.findall(label)
    return len(months) >= 2 or (
        bool(months) and YEAR_TOKEN_SEARCH_RE.search(label) is not None
    )


_FORWARD_LOOKING = ("forward-looking", "forward looking")
_INSTRUMENT_ROW_BASES = ("swap", "swaps", "forward", "forwards", "futures")
_COMMODITY_EFFECTS = ("unrealized", "gain/loss", "(gain)/loss")


_UNAMBIGUOUS = "unambiguous"
_AMBIGUOUS = "ambiguous"
_STEM = "stem"
_DESIGNATION = "designation"
_ANCHOR = "anchor"
_SUFFIX = "suffix"
_COMMERCIAL = "commercial"
_NPNS = "npns"
_EQUITY_COMP = "equity_comp"
_EQUITY_PREFIXED = "equity_prefixed"
_AOCI_SUBJECT = "aoci_subject"
_COMMODITY_HEADER = "commodity_header"
_EFFECTS = "effects"
_EFFECTS_LEADIN = "effects_leadin"
_OFFSETTING = "offsetting"
_INSTRUMENT_ROW = "instrument_row"
_FORWARD_LOOKING_KIND = "forward_looking"
_SUBJECT_ANCHOR = "subject_anchor"


@lru_cache(maxsize=None)
def _spec_index(spec: DerivativesEvidenceSpec) -> TermIndex:
    """The spec's unified term index: each form once, with its kinds.

    Match mode is the consulting list's own: bases, suffix and
    commercial terms match on word boundaries; phrase lists match
    as literal substrings; stems and equity-prefixed compounds
    report the base they credit or discount.
    """
    entries: list[TermEntry] = []

    def add(terms: tuple[str, ...], kind: str, word: bool = False) -> None:
        entries.extend(TermEntry(term, kind, word=word) for term in terms)

    add(spec.unambiguous_bases, _UNAMBIGUOUS, word=True)
    add(spec.ambiguous_bases, _AMBIGUOUS, word=True)
    entries.extend(
        TermEntry(stem, _STEM, value=base) for stem, base in spec.stem_bases
    )
    add(spec.designation_phrases, _DESIGNATION)
    add(spec.anchor_terms, _ANCHOR)
    add(spec.suffix_terms, _SUFFIX, word=True)
    add(spec.commercial_terms, _COMMERCIAL, word=True)
    add(spec.npns_phrases, _NPNS)
    add(spec.equity_comp_terms, _EQUITY_COMP)
    entries.extend(
        TermEntry(f"{prefix} {base}", _EQUITY_PREFIXED, value=base)
        for prefix in spec.equity_prefixes
        for base in spec.ambiguous_bases
    )
    add(spec.aoci_subject_phrases, _AOCI_SUBJECT)
    entries.append(TermEntry(spec.commodity_header, _COMMODITY_HEADER))
    add(spec.effects_phrases, _EFFECTS)
    add(spec.effects_leadin_phrases, _EFFECTS_LEADIN)
    add(spec.offsetting_phrases, _OFFSETTING)
    add(_INSTRUMENT_ROW_BASES, _INSTRUMENT_ROW, word=True)
    add(_FORWARD_LOOKING, _FORWARD_LOOKING_KIND)
    add(_SUBJECT_ANCHORS, _SUBJECT_ANCHOR)
    return TermIndex(entries)


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
        from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
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


def _hits(
    index: TermIndex, lines: tuple[str, ...]
) -> list[dict[str, frozenset[str]]]:
    """One traversal per line: every evidence kind collected at once."""
    return [index.scan(line) for line in lines]


def _unambiguous(
    spec: DerivativesEvidenceSpec, line_hits: list[dict[str, frozenset[str]]]
) -> tuple[str, ...]:
    """Unambiguous bases present, with the forward guards applied."""
    found = []
    for base in spec.unambiguous_bases:
        if base not in ("forward", "forwards"):
            if any(base in hits.get(_UNAMBIGUOUS, ()) for hits in line_hits):
                found.append(base)
            continue
        for hits in line_hits:
            if base not in hits.get(_UNAMBIGUOUS, ()):
                continue
            if hits.get(_FORWARD_LOOKING_KIND):
                continue
            if hits.get(_COMMERCIAL):
                continue
            found.append(base)
            break
    return tuple(found)


def _ambiguous(line_hits: list[dict[str, frozenset[str]]]) -> frozenset[str]:
    """Distinct ambiguous bases, equity-prefixed ones discounted.

    A prefixed base counts only inside a triple on its own line:
    the suffix-lookbehind rule of the design algebra.
    """
    found: set[str] = set()
    for hits in line_hits:
        bases = set(hits.get(_AMBIGUOUS, ())) | set(hits.get(_STEM, ()))
        if len(bases) < 3:
            bases -= set(hits.get(_EQUITY_PREFIXED, ()))
        found.update(bases)
    return frozenset(found)


def _instrument_row(index: TermIndex, stubs: tuple[str, ...]) -> bool:
    """A stub label naming an instrument, not an income-statement line."""
    for label in stubs:
        if "related to" in label:
            continue
        if index.scan(label).get(_INSTRUMENT_ROW):
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
    index = _spec_index(spec)
    line_hits = _hits(index, lines)
    grid_hits = line_hits + _hits(index, text.grid)
    leadin_hits = index.scan(text.leadin)
    subject_hits = index.scan(subject)
    evidence_hits = index.scan(evidence)
    leadin_scan = [leadin_hits]
    unamb_subject = _unambiguous(spec, line_hits)
    unamb_grid = _unambiguous(spec, grid_hits)
    unamb_leadin = _unambiguous(spec, leadin_scan)
    amb = _ambiguous(line_hits)
    designation = tuple(
        phrase
        for phrase in spec.designation_phrases
        if phrase in subject_hits.get(_DESIGNATION, ())
    )
    designation_leadin = tuple(
        phrase
        for phrase in spec.designation_phrases
        if phrase in leadin_hits.get(_DESIGNATION, ())
    )
    anchors = tuple(
        term for term in spec.anchor_terms if term in evidence_hits.get(_ANCHOR, ())
    )
    aoci_subject = bool(
        index.scan(
            text.caption + " " + text.lead_title + " " + " ".join(text.stubs[:3])
        ).get(_AOCI_SUBJECT)
    )
    if (
        aoci_subject
        and "notional" not in evidence
        and not _instrument_row(index, text.stubs)
    ):
        return DerivativesEvidence(
            False, "E", False, "aoci-components subject: equity carve-out"
        )
    comp_hits = index.scan(evidence + " " + text.leadin)
    comp = bool(comp_hits.get(_EQUITY_COMP))
    if comp and not unamb_grid and not designation:
        return DerivativesEvidence(
            False, "E", False, "equity-compensation evidence only"
        )
    npns = bool(comp_hits.get(_NPNS))
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
        bool(hits.get(_AMBIGUOUS, frozenset()) & amb) and bool(hits.get(_SUFFIX))
        for hits in line_hits
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
    offsetting = bool(subject_hits.get(_OFFSETTING)) and (
        bool(designation)
        or "financial instruments" in subject
        or "financial assets" in subject
    )
    if offsetting:
        return DerivativesEvidence(True, "A", True, "offsetting form")
    effects = bool(subject_hits.get(_EFFECTS)) or bool(
        leadin_hits.get(_EFFECTS_LEADIN)
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
    if subject_hits.get(_COMMODITY_HEADER) and any(
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
    index = _spec_index(spec)
    unambiguous = _unambiguous(spec, _hits(index, lines))
    if unambiguous:
        return DerivativesSubject(True, "subject: " + ", ".join(unambiguous))
    framing_hits = index.scan(framing)
    designation = tuple(
        p for p in spec.designation_phrases if p in framing_hits.get(_DESIGNATION, ())
    )
    if designation:
        return DerivativesSubject(True, "subject: " + ", ".join(designation))
    if "hedg" in framing:
        return DerivativesSubject(True, "subject: hedging")
    anchors = tuple(
        term for term in _SUBJECT_ANCHORS if term in framing_hits.get(_SUBJECT_ANCHOR, ())
    )
    if anchors:
        return DerivativesSubject(True, "subject: " + ", ".join(anchors))
    if framing_hits.get(_OFFSETTING) and _instrument_row(index, text.stubs):
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
