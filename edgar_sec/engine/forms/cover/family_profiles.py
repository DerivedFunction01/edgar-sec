"""Cover profiles for the notice and prospectus families (15, 12B-25,
14A, 11-K, 424B, FWP, 425), composed from the shared kit in ``profiles``.
"""

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
from edgar_sec.domain.forms.families.form_11k.evidence import Form11KEvidence
from edgar_sec.domain.forms.families.form_11k.taxonomy import FORM_11K_ITEMS
from edgar_sec.domain.forms.families.form_12b25.taxonomy import FORM_12B25_ITEMS
from edgar_sec.domain.forms.families.form_14a.evidence import Form14AEvidence
from edgar_sec.domain.forms.families.form_14a.taxonomy import FORM_14A_ITEMS
from edgar_sec.domain.forms.families.form_424b.taxonomy import FORM_424B_ITEMS
from edgar_sec.domain.forms.families.form_497.taxonomy import FORM_497_ITEMS
from edgar_sec.domain.forms.families.form_fwp.taxonomy import FORM_FWP_ITEMS
from edgar_sec.domain.forms.families.form_ncsr.taxonomy import FORM_NCSR_ITEMS
from edgar_sec.domain.forms.families.form_nq.taxonomy import FORM_NQ_ITEMS
from edgar_sec.domain.forms.families.form_nsar.taxonomy import FORM_NSAR_ITEMS
from edgar_sec.domain.forms.families.form_tender.taxonomy import (
    SCHEDULE_13E3_ITEMS,
    SCHEDULE_13E3_PRIOR_ITEMS,
    SCHEDULE_13E4_ITEMS,
    SCHEDULE_14D1F_ITEMS,
    SCHEDULE_14D1_ITEMS,
    SCHEDULE_14D9_ITEMS,
    SCHEDULE_TO_ITEMS,
)
from edgar_sec.domain.forms.families.registration.evidence import (
    RegistrationEvidence,
)
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

_FORM_424B_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "filed pursuant to rule 424",
    "registration no.",
    "registration statement no.",
    "registration number",
    "prospectus",
    "prospectus supplement",
    "preliminary prospectus",
    "pricing supplement",
    "subject to completion",
    "calculation of registration fee",
    "the date of this prospectus is",
)


def build_form_424b_profile(family: str = "424B") -> CoverProfile:
    """Cover profile for Rule 424 prospectuses: the 424(b) header block
    forms the cover; body vocabulary is the registration pack.
    """
    registration = RegistrationEvidence()
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.TOC_TRANSITION,
                BoundarySignal.ITEM_FALLBACK,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_FORM_424B_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_424B_COVER_LABELS,
            ),
            labels=_FORM_424B_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_424B_ITEMS),
            semantic_headings=(
                "prospectus summary",
                "risk factors",
                "use of proceeds",
                "plan of distribution",
                "underwriting",
                "table of contents",
                "calculation of registration fee",
                *FORWARD_LOOKING_PHRASES,
            ),
            body_ngrams=registration.body_ngrams,
            body_verbs=registration.body_verbs,
            body_terms=registration.body_terms,
            cover_terms=registration.cover_terms,
            lexical=registration.body_lexical,
        ),
    )


_FORM_15_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "certification and notice of termination of registration",
    "title of each class of securities covered by this form",
    "titles of all other classes of securities",
    "rule 12g-4",
    "rule 12h-3",
    "rule 15d-6",
    "approximate number of holders of record",
)


def build_form_15_profile(family: str = "15") -> CoverProfile:
    """Cover profile for Form 15 notices: a single-page cover carrying the
    rule-provision checkboxes; the body is footnotes plus the signature block.
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
        labels=_FORM_15_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_FORM_15_COVER_LABELS,
            labels=_FORM_15_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            semantic_headings=(
                "signature",
                "signatures",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_12B25_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "notification of late filing",
    "sec file number",
    "cusip number",
    "for period ended",
    "transition report",
    "full name of registrant",
    "registrant information",
)


def build_form_12b25_profile(family: str = "12B-25") -> CoverProfile:
    """Cover profile for Form 12b-25 notifications: the filing selections and
    Part I registrant block form the cover; Parts II–IV are the body.
    """
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.PART_FALLBACK,
                BoundarySignal.ITEM_FALLBACK,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_FORM_12B25_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_FORM_12B25_COVER_LABELS,
            labels=_FORM_12B25_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_12B25_ITEMS),
            semantic_headings=(
                "narrative",
                "other information",
                "signature",
                "signatures",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_14A_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "schedule 14a information",
    "schedule 14c information",
    "proxy statement pursuant to section 14(a)",
    "information statement pursuant to section 14(c)",
    "preliminary proxy statement",
    "definitive proxy statement",
    "name of registrant as specified in its charter",
    "name of person(s) filing proxy statement",
    "payment of filing fee",
)


def build_form_14a_profile(family: str = "14A") -> CoverProfile:
    """Cover profile for Schedule 14A/14C statements: the classification and
    fee boxes form the cover; the letter, contents, and Items 1–25 are the body.
    """
    proxy = Form14AEvidence()
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.TOC_TRANSITION,
                BoundarySignal.ITEM_FALLBACK,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_FORM_14A_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_FORM_14A_COVER_LABELS,
            labels=_FORM_14A_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_14A_ITEMS),
            semantic_headings=(
                "notice of annual meeting",
                "notice of special meeting",
                "table of contents",
                "proxy statement",
                "signature",
                "signatures",
                *FORWARD_LOOKING_PHRASES,
            ),
            body_ngrams=proxy.body_ngrams,
            body_verbs=proxy.body_verbs,
            body_terms=proxy.body_terms,
            cover_terms=proxy.cover_terms,
            lexical=proxy.body_lexical,
        ),
    )


_FORM_11K_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "form 11-k",
    "annual reports of employee stock purchase, savings and similar plans",
    "commission file number",
    "full title of the plan",
    "name of issuer of the securities held pursuant to the plan",
    "for the fiscal year ended",
    "for the transition period from",
)


def build_form_11k_profile(family: str = "11-K") -> CoverProfile:
    """Cover profile for Form 11-K plan annual reports: the (Mark One) boxes,
    commission file number, and the plan/issuer captions form the cover; the
    financial statements and schedules are the body.
    """
    plan = Form11KEvidence()
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.TOC_TRANSITION,
                BoundarySignal.ITEM_FALLBACK,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_FORM_11K_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_FORM_11K_COVER_LABELS,
            labels=_FORM_11K_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_11K_ITEMS),
            semantic_headings=(
                "financial statements and supplemental schedules",
                "report of independent registered public accounting firm",
                "signatures",
                "signature",
                *FORWARD_LOOKING_PHRASES,
            ),
            body_ngrams=plan.body_ngrams,
            body_verbs=plan.body_verbs,
            body_terms=plan.body_terms,
            cover_terms=plan.cover_terms,
            lexical=plan.body_lexical,
        ),
    )


_FORM_FWP_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "free writing prospectus",
    "filed pursuant to rule 433",
    "registration statement nos.",
    "registration statement no.",
    "issuer",
    "guarantor",
)


def build_form_fwp_profile(family: str = "FWP") -> CoverProfile:
    """Cover profile for free writing prospectuses: the Rule 433 header
    block (issuer, rule reference, registration numbers) is the cover.
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
        labels=_FORM_FWP_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_FWP_COVER_LABELS,
            ),
            labels=_FORM_FWP_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_FWP_ITEMS),
            semantic_headings=(
                "summary terms",
                "key terms",
                "risk factors",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_425_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "filed by",
    "pursuant to rule 425",
    "rule 14a-12",
    "subject company",
    "commission file no.",
    "commission file number",
)


def build_form_425_profile(family: str = "425") -> CoverProfile:
    """Cover profile for Rule 425 communications: the filed-by / subject
    company header block is the cover; the body is the communication.
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
        labels=_FORM_425_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_425_COVER_LABELS,
            ),
            labels=_FORM_425_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=(),
            semantic_headings=(
                "press release",
                "forward-looking statements",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


__all__ = [
    "build_form_11k_profile",
    "build_form_12b25_profile",
    "build_form_14a_profile",
    "build_form_15_profile",
    "build_form_424b_profile",
    "build_form_425_profile",
    "build_form_497_profile",
    "build_form_fwp_profile",
    "build_form_ncsr_profile",
    "build_form_nq_profile",
    "build_form_nsar_profile",
]


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


_TENDER_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "schedule to",
    "tender offer statement",
    "name of subject company",
    "names of filing persons",
    "name of filing person",
    "name of person filing statement",
    "title of class of securities",
    "cusip number of class of securities",
    "person authorized to receive notices and communications",
    "calculation of filing fee",
    "schedule 14d-9",
    "solicitation/recommendation statement",
    "schedule 13e-3",
    "rule 13e-3 transaction statement",
    "name of the issuer",
    "name of issuer",
    "names of persons filing statement",
    "schedule 13e-4",
    "issuer tender offer statement",
    "schedule 14d-1f",
    "check the appropriate boxes below to designate any transactions",
)

_TENDER_ITEM_SETS = (
    SCHEDULE_TO_ITEMS,
    SCHEDULE_14D9_ITEMS,
    SCHEDULE_13E3_ITEMS,
    SCHEDULE_13E3_PRIOR_ITEMS,
    SCHEDULE_13E4_ITEMS,
    SCHEDULE_14D1_ITEMS,
    SCHEDULE_14D1F_ITEMS,
)


def build_form_tender_profile(family: str = "SC TO") -> CoverProfile:
    """Cover profile for tender offer statements: the schedule facing
    sheet (subject company, filing persons, class, CUSIP, designation
    boxes) forms the cover; the body is the item sequence of its kind.
    """
    identifiers = tuple(
        dict.fromkeys(d.item for items in _TENDER_ITEM_SETS for d in items)
    )
    titles = tuple(
        dict.fromkeys(d.names[0] for items in _TENDER_ITEM_SETS for d in items)
    )
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.TOC_TRANSITION,
                BoundarySignal.ITEM_FALLBACK,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_TENDER_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_TENDER_COVER_LABELS,
            ),
            labels=_TENDER_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=identifiers,
            semantic_headings=(
                *titles,
                "signature",
                "signatures",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
        unwrap_false_tables=False,
    )
