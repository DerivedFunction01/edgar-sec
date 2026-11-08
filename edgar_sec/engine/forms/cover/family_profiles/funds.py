"""Cover profiles for the investment-company families (N-CSR, N-Q,
NSAR, 497), composed from the shared kit in ``profiles``."""

from __future__ import annotations

from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_PHRASES
from edgar_sec.domain.forms.common.models import (
    BodyEvidencePack,
    CoverEvidencePack,
)
from edgar_sec.domain.forms.common.vocabulary import (
    COVER_EVIDENCE_TERMS,
    COVER_START_IDENTITY_TERMS,
)
from edgar_sec.domain.forms.families.form_497.taxonomy import FORM_497_ITEMS
from edgar_sec.domain.forms.families.form_ncsr.taxonomy import FORM_NCSR_ITEMS
from edgar_sec.domain.forms.families.form_nq.taxonomy import FORM_NQ_ITEMS
from edgar_sec.domain.forms.families.form_nsar.taxonomy import FORM_NSAR_ITEMS
from edgar_sec.engine.forms.cover.models import (
    BoundarySignal,
    CoverBoundaryPolicy,
)
from edgar_sec.engine.forms.cover.profiles import (
    COMMON_COVER_LABELS,
    GENERIC_PHRASE_RULES,
    CoverProfile,
    _make_profile,
)

_FORM_NCSR_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "form n-csr",
    "certified shareholder report",
    "investment company act file number",
    "exact name of registrant",
)


def build_form_ncsr_profile(family: str = "N-CSR") -> CoverProfile:
    """Cover profile for certified shareholder reports: the ICA facing
    sheet is the cover; the body is the shareholder report.
    """
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.ITEM_FALLBACK,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_FORM_NCSR_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_NCSR_COVER_LABELS,
            ),
            labels=_FORM_NCSR_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_NCSR_ITEMS),
            semantic_headings=(
                "schedule of investments",
                "financial highlights",
                "signatures",
                "signature",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_NQ_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "form n-q",
    "quarterly schedule of portfolio holdings",
    "investment company act file number",
    "exact name of registrant",
)


def build_form_nq_profile(family: str = "N-Q") -> CoverProfile:
    """Cover profile for quarterly holdings schedules: the ICA facing
    sheet is the cover; the body is the schedule of investments.
    """
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.ITEM_FALLBACK,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_FORM_NQ_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_NQ_COVER_LABELS,
            ),
            labels=_FORM_NQ_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_NQ_ITEMS),
            semantic_headings=(
                "schedule of investments",
                "controls and procedures",
                "signatures",
                "signature",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_NSAR_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "answer file",
    "registrant",
)


def build_form_nsar_profile(family: str = "NSAR") -> CoverProfile:
    """Cover profile for NSAR answer files: the keyed answer lines are
    the document; the page header block is the only cover present.
    """
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_FORM_NSAR_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_NSAR_COVER_LABELS,
            ),
            labels=_FORM_NSAR_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_NSAR_ITEMS),
            semantic_headings=(),
        ),
    )


_FORM_497_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "filed pursuant to rule 497",
    "registration no.",
    "registration statement no.",
    "prospectus",
    "prospectus supplement",
    "statement of additional information",
    "subject to completion",
)


def build_form_497_profile(family: str = "497") -> CoverProfile:
    """Cover profile for Rule 497 prospectus filings: the rule header
    block forms the cover; body vocabulary is the prospectus pack.
    """
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_FORM_497_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_497_COVER_LABELS,
            ),
            labels=_FORM_497_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_497_ITEMS),
            semantic_headings=(
                "summary",
                "risk factors",
                "use of proceeds",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


__all__ = [
    "build_form_497_profile",
    "build_form_ncsr_profile",
    "build_form_nq_profile",
    "build_form_nsar_profile",
]
