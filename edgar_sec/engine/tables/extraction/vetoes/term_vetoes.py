"""Priced term vetoes: the priced sets as data (v2 + Step 4 v3).

HARD terms remove a family's claim outright; SCORED terms lower
its score once per claim, however many hit (any-hit). Channels
as priced: lead is caption + prose_before; body is grid text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.vetoes.term_veto_notes import NOTE_VETO_ENTRIES
from edgar_sec.engine.tables.extraction.vetoes.term_veto_statements import (
    STATEMENT_VETO_ENTRIES,
)
from edgar_sec.foundation.text.date_patterns import MONTH_ALIASES

if TYPE_CHECKING:
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
        GeometryText,
    )


@dataclass(frozen=True, slots=True)
class VetoSpec:
    """One family's priced term vetoes for one channel at one tier."""

    family: str
    channel: str
    tier: str
    terms: tuple[str, ...]


def _month_spellings() -> tuple[str, ...]:
    """The distinct month spellings as the matcher normalizes them."""
    spellings: list[str] = []
    for aliases in MONTH_ALIASES:
        for alias in aliases:
            spelling = normalize_text(alias)
            if spelling not in spellings:
                spellings.append(spelling)
    return tuple(spellings)


_MONTH_SPELLINGS = _month_spellings()

_FYE_FORM_TEMPLATES: dict[str, str] = {
    "bare": "ended {month}",
    "span": "three months ended {month}",
}


def fiscal_year_end_terms(forms: tuple[str, ...]) -> tuple[str, ...]:
    """Fiscal-year-end phrases for the adopted forms, every month."""
    return tuple(
        _FYE_FORM_TEMPLATES[form].format(month=spelling)
        for form in forms
        for spelling in _MONTH_SPELLINGS
    )


# Fiscal-year-end adoptions (register §1c): the named entries'
# literal month phrases are replaced at composition by the
# generated construction, attested forms only.
_FYE_ADOPTIONS: dict[tuple[str, str, str], tuple[str, ...]] = {
    ("balance_sheet", "lead", "scored"): ("bare",),
    ("income_statement", "lead", "scored"): ("bare",),
    ("income_statement", "body", "scored"): ("span",),
    ("comprehensive_income", "lead", "scored"): ("bare",),
    ("cash_flow", "body", "hard"): ("span",),
    ("cash_flow", "lead", "scored"): ("bare",),
    ("cash_flow", "body", "scored"): ("span",),
    ("equity_statement", "lead", "scored"): ("bare",),
    ("equity_statement", "body", "scored"): ("span",),
    ("aoci_rollforward", "body", "hard"): ("span",),
    ("eps_reconciliation", "lead", "scored"): ("bare",),
    ("eps_reconciliation", "body", "scored"): ("span",),
    ("deferred_tax", "body", "hard"): ("span",),
    ("tax_reconciliation", "lead", "hard"): ("bare",),
    ("tax_reconciliation", "body", "hard"): ("span",),
    ("intangibles", "lead", "scored"): ("bare",),
    ("pension", "lead", "scored"): ("bare",),
    ("stock_comp_rollforward", "lead", "scored"): ("bare",),
}


def _expand_fiscal_year_end(
    entry: tuple[str, str, str, tuple[str, ...]],
) -> tuple[str, str, str, tuple[str, ...]]:
    """Splice one entry's generated phrases over its literals."""
    family, channel, tier, terms = entry
    forms = _FYE_ADOPTIONS.get((family, channel, tier))
    if forms is None:
        return entry
    literals = {
        _FYE_FORM_TEMPLATES[form].format(month=spelling)
        for form in forms
        for spelling in _MONTH_SPELLINGS
    }
    expanded: list[str] = []
    spliced = False
    for term in terms:
        if term in literals:
            if not spliced:
                expanded.extend(fiscal_year_end_terms(forms))
                spliced = True
            continue
        expanded.append(term)
    return (family, channel, tier, tuple(expanded))


# Step 6 v2 sets (record: 2026-11-16-greenfield-step6-v2-
# measurement-record) plus the Step 4 v3 build-act rows (record:
# greenfield-followup-discovery/step4) and the AOCI held-row release.
TERM_VETOES: tuple[VetoSpec, ...] = tuple(
    VetoSpec(*_expand_fiscal_year_end(entry))
    for entry in STATEMENT_VETO_ENTRIES + NOTE_VETO_ENTRIES
)


LEAD_TEXT_CAP = 6000


def lead_channel_text(caption: str, prose_before: str) -> str:
    """The priced lead channel: caption + prose_before, tail-capped."""
    return caption + "\n" + prose_before[-LEAD_TEXT_CAP:]


def term_veto_hits(geometry: GeometryText) -> dict[str, dict[str, str]]:
    """First priced term-veto hit per family and tier.

    Matching is the pricing's own: normalized substring over the
    channel text; lead reads GeometryText.lead, body the grid.
    """
    hits: dict[str, dict[str, str]] = {}
    for family, tiers in term_veto_hits_by_channel(geometry).items():
        hits[family] = {
            tier: next(iter(by_channel.values())) for tier, by_channel in tiers.items()
        }
    return hits


# Form-conditioned hard-veto exemptions (greenfield intangibles
# packet): a recorded hard hit on these terms does not bar the
# family when a named form test passed on the same geometry.
HARD_VETO_FORM_EXEMPTIONS: dict[tuple[str, str], tuple[str, ...]] = {
    ("intangibles", "segment"): ("intangibles_identity_form",),
    ("intangibles", "revenue"): ("intangibles_identity_form",),
    ("intangibles", "revenues"): ("intangibles_identity_form",),
    ("intangibles", "cash flow"): ("intangibles_identity_form",),
    ("intangibles", "income tax"): ("intangibles_identity_form",),
}


def hard_veto_form_exemption(family: str, term: str) -> tuple[str, ...] | None:
    """The form tests whose pass exempts one recorded hard hit.

    Returns the named form-test ids for an exempted
    (family, term) pair, or None when the hit bars outright.
    """
    return HARD_VETO_FORM_EXEMPTIONS.get((family, term))


def _veto_index() -> TermIndex:
    """One substring index over every veto term: kind is the
    spec's position, value the term as listed. Entries carry
    the normalized term; phrase entries only."""
    return TermIndex(
        TermEntry(normalize_text(term), str(i), value=term)
        for i, spec in enumerate(TERM_VETOES)
        for term in spec.terms
    )


_VETO_INDEX = _veto_index()


def term_veto_hits_by_channel(
    geometry: GeometryText,
) -> dict[str, dict[str, dict[str, str]]]:
    """First priced hit per family, tier, and channel."""
    texts = {
        "lead": normalize_text(geometry.lead),
        "body": normalize_text(geometry.grid_text),
    }
    found = {channel: _VETO_INDEX.scan(text) for channel, text in texts.items()}
    hits: dict[str, dict[str, dict[str, str]]] = {}
    for i, spec in enumerate(TERM_VETOES):
        if not texts[spec.channel]:
            continue
        present = found[spec.channel].get(str(i), frozenset())
        for term in spec.terms:
            if term in present:
                tiers = hits.setdefault(spec.family, {})
                by_channel = tiers.setdefault(spec.tier, {})
                if spec.channel not in by_channel:
                    by_channel[spec.channel] = term
                break
    return hits
