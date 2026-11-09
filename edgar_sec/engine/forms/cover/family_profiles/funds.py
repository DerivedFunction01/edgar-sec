"""Cover profiles for the investment-company families (N-CSR, N-Q,
NSAR, 497, 40-17G, 40-17F1, 40-17F2, 40-APP, N-30D, N-VP, 24F-2, N-23C notices), composed from the shared kit
in ``profiles``."""

from __future__ import annotations

from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_PHRASES
from edgar_sec.domain.forms.common.models import (
    BodyEvidencePack,
    CoverEvidencePack,
    ItemDefinition,
)
from edgar_sec.domain.forms.common.vocabulary import (
    COVER_EVIDENCE_TERMS,
    COVER_START_IDENTITY_TERMS,
)
from edgar_sec.domain.forms.families.form_24f2.taxonomy import FORM_24F2_ITEMS
from edgar_sec.domain.forms.families.form_4017f1.taxonomy import FORM_4017F1_ITEMS
from edgar_sec.domain.forms.families.form_4017f2.taxonomy import FORM_4017F2_ITEMS
from edgar_sec.domain.forms.families.form_4017g.taxonomy import FORM_4017G_ITEMS
from edgar_sec.domain.forms.families.form_40app.taxonomy import FORM_40APP_ITEMS
from edgar_sec.domain.forms.families.form_497.taxonomy import FORM_497_ITEMS
from edgar_sec.domain.forms.families.form_n23c.taxonomy import (
    FORM_N23C1_ITEMS,
    FORM_N23C2_ITEMS,
    FORM_N23C3_ITEMS,
)
from edgar_sec.domain.forms.families.form_n30d.taxonomy import FORM_N30D_ITEMS
from edgar_sec.domain.forms.families.form_nvp.taxonomy import FORM_NVP_ITEMS
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


_FORM_4017G_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "investment company blanket bond",
    "fidelity bond",
    "rule 17g-1",
)


def build_form_4017g_profile(family: str = "40-17G") -> CoverProfile:
    """Cover profile for fidelity-bond filings: the transmittal letter
    and bond face form the cover; the instrument blocks are the body.
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
        labels=_FORM_4017G_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_FORM_4017G_COVER_LABELS,
            labels=_FORM_4017G_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_4017G_ITEMS),
            semantic_headings=(
                "declarations",
                "insuring agreements",
                "signatures",
                "signature",
            ),
        ),
    )


_FORM_4017F_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "certificate of accounting of securities and similar investments",
    "investment company act file number",
    "date examination completed",
)

_FORM_4017F1_COVER_LABELS: tuple[str, ...] = (
    *_FORM_4017F_COVER_LABELS,
    "form n-17f-1",
    "pursuant to rule 17f-1",
)

_FORM_4017F2_COVER_LABELS: tuple[str, ...] = (
    *_FORM_4017F_COVER_LABELS,
    "form n-17f-2",
    "pursuant to rule 17f-2",
)


def _build_form_4017f_profile(
    family: str, labels: tuple[str, ...], items: tuple[ItemDefinition, ...]
) -> CoverProfile:
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
        labels=labels,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *labels,
            ),
            labels=labels,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in items),
            semantic_headings=(
                "instructions",
                "management statement",
                "report of independent",
                "signatures",
                "signature",
            ),
        ),
    )


def build_form_4017f1_profile(family: str = "40-17F1") -> CoverProfile:
    """Cover profile for N-17f-1 certificates: the certificate face is
    the cover; the statements and accountant's report are the body.
    """
    return _build_form_4017f_profile(
        family, _FORM_4017F1_COVER_LABELS, FORM_4017F1_ITEMS
    )


def build_form_4017f2_profile(family: str = "40-17F2") -> CoverProfile:
    """Cover profile for N-17f-2 certificates: the certificate face is
    the cover; the statements and accountant's report are the body.
    """
    return _build_form_4017f_profile(
        family, _FORM_4017F2_COVER_LABELS, FORM_4017F2_ITEMS
    )


_FORM_40APP_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "form 40-app",
    "application for an order",
    "exemptive application",
    "investment company act of 1940",
    "file no. 812-",
)


def build_form_40app_profile(family: str = "40-APP") -> CoverProfile:
    """Cover profile for exemptive applications: the face sheet naming
    the applicants and the order sought is the cover; the application
    body follows it.
    """
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.TOC_TRANSITION,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_FORM_40APP_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_40APP_COVER_LABELS,
            ),
            labels=_FORM_40APP_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_40APP_ITEMS),
            semantic_headings=(
                "introduction",
                "summary of application",
                "procedural matters",
                "verification",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_N30D_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "form n-30d",
    "form n-30b-2",
    "shareholder report",
    "semiannual report",
    "investment company act file number",
    "exact name of registrant",
)


def build_form_n30d_profile(family: str = "N-30D") -> CoverProfile:
    """Cover profile for shareholder reports: any facing-sheet header
    is the cover; the body is the shareholder report itself.
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
        labels=_FORM_N30D_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_N30D_COVER_LABELS,
            ),
            labels=_FORM_N30D_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_N30D_ITEMS),
            semantic_headings=(
                "schedule of investments",
                "financial highlights",
                "letter to shareholders",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_NVP_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "form n-vp",
    "notice document",
    "summary prospectus",
    "separate account",
    "variable annuity",
    "variable life insurance",
    "investment company act file number",
    "exact name of registrant",
)


def build_form_nvp_profile(family: str = "N-VP") -> CoverProfile:
    """Cover profile for variable-product filings: the facing sheet
    and notice header form the cover; the body is the key-information
    sequence or the financial-statements block.
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
        labels=_FORM_NVP_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_NVP_COVER_LABELS,
            ),
            labels=_FORM_NVP_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_NVP_ITEMS),
            semantic_headings=(
                "key information",
                "fees and expenses",
                "signatures",
                "signature",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_24F2_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "form 24f-2",
    "annual notice of securities sold",
    "pursuant to rule 24f-2",
    "investment company act file number",
    "securities act file number",
)


def build_form_24f2_profile(family: str = "24F-2NT") -> CoverProfile:
    """Cover profile for Rule 24f-2 fee notices: the form's face-sheet
    captions form the cover; the numbered items are the body.
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
        labels=_FORM_24F2_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_FORM_24F2_COVER_LABELS,
            labels=_FORM_24F2_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_24F2_ITEMS),
            semantic_headings=(
                "calculation of registration fee",
                "signatures",
                "signature",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_N23C1_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "form n-23c-1",
    "statement by registered closed-end investment company",
    "report for calendar month ending",
)


def build_form_n23c1_profile(family: str = "N-23C-1") -> CoverProfile:
    """Cover profile for Rule 23c-1 purchase statements: the face sheet
    is the cover; the statement and its transaction table are the body.
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
        labels=_FORM_N23C1_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_N23C1_COVER_LABELS,
            ),
            labels=_FORM_N23C1_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_N23C1_ITEMS),
            semantic_headings=(
                "remarks",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_N23C2_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "rule 23c-2 notice of intention to redeem securities",
    "notice of intention to redeem securities",
    "under the investment company act of 1940",
    "investment company act file no.",
)


def build_form_n23c2_profile(family: str = "N-23C-2") -> CoverProfile:
    """Cover profile for Rule 23c-2 redemption notices: the notice
    heading block is the cover; the numbered statements are the body.
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
        labels=_FORM_N23C2_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_N23C2_COVER_LABELS,
            ),
            labels=_FORM_N23C2_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_N23C2_ITEMS),
            semantic_headings=(
                "signature",
                "signatures",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_N23C3_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "form n-23c-3",
    "notification of repurchase offer",
    "pursuant to rule 23c-3",
    "investment company act file number",
    "exact name of registrant",
)


def build_form_n23c3_profile(family: str = "N-23C-3") -> CoverProfile:
    """Cover profile for Rule 23c-3 repurchase offers: the notification
    face is the cover; the offer terms and request form are the body.
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
        labels=_FORM_N23C3_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_N23C3_COVER_LABELS,
            ),
            labels=_FORM_N23C3_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_N23C3_ITEMS),
            semantic_headings=(
                "repurchase offer terms",
                "repurchase request form",
                "signatures",
                "signature",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


__all__ = [
    "build_form_24f2_profile",
    "build_form_4017f1_profile",
    "build_form_4017f2_profile",
    "build_form_4017g_profile",
    "build_form_40app_profile",
    "build_form_497_profile",
    "build_form_n23c1_profile",
    "build_form_n23c2_profile",
    "build_form_n23c3_profile",
    "build_form_n30d_profile",
    "build_form_nvp_profile",
    "build_form_ncsr_profile",
    "build_form_nq_profile",
    "build_form_nsar_profile",
]
