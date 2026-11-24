"""EPS refusal parameters: the priced forms as data.
The precision-p3 packets' vocabularies and surfaces,
declared once here for the eps_refusal_evidence evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    PROV_EPS_REFUSAL_PRICING,
    TEST_EPS_ADJACENCY_REFUSAL,
    TEST_EPS_PROFORMA_REFUSAL,
)


@dataclass(frozen=True, slots=True)
class EpsRefusalSpec:
    """One EPS claim-refusal form's parameters, as data.
    The priced vocabularies and the prose-tail surface."""

    family: str
    test_id: str
    prose_tail_chars: int = 1600
    identity_phrases: tuple[str, ...] = ()
    prose_extra_phrases: tuple[str, ...] = ()
    share_phrases: tuple[str, ...] = ()
    amount_phrases: tuple[str, ...] = ()
    proforma_phrases: tuple[str, ...] = ()
    as_reported_phrase: str = ""
    provenance: str = PROV_EPS_REFUSAL_PRICING


# EPS identity: prose naming an EPS subject. The identity
# leg reads these over note, caption, and carrying prose.
EPS_IDENTITY_PHRASES = (
    "earnings per share",
    "income per share",
    "loss per share",
    "net income per share",
    "net loss per share",
    "per share data",
    "per share amounts",
    "per share information",
)

# Prose-only extras: the carrying-prose leg also admits
# antidilution and share-count prose as EPS identity.
EPS_PROSE_EXTRA_PHRASES = (
    "antidilutive",
    "anti dilutive",
    "weighted average shares",
    "diluted earnings",
    "diluted net income",
    "diluted net loss",
)

# The canonical row vocabulary, generic forms only:
# share-count row phrases and per-share amount row phrases.
EPS_SHARE_ROW_PHRASES = (
    "shares outstanding",
    "shares used",
    "shares issuable",
    "average shares",
    "shares basic",
    "shares diluted",
)
EPS_AMOUNT_ROW_PHRASES = (
    "per share",
    "per common share",
    "per unit",
    "per common unit",
)

# Pro-forma markers: the pro-forma leg reads these over
# prose, caption, and the geometry's own row texts.
EPS_PROFORMA_PHRASES = (
    "pro forma",
    "proforma",
)

# EPS refusal specs, keyed by test_id: the one literal home
# of the forms' parameters, priced by the precision-p3 pass
# over the Round 2 verdict population (kills 2/2, touches 0).
EPS_REFUSAL_SPECS_BY_TEST_ID: dict[str, EpsRefusalSpec] = {
    "eps_adjacency_refusal": EpsRefusalSpec(
        family="eps_reconciliation",
        test_id="eps_adjacency_refusal",
        identity_phrases=EPS_IDENTITY_PHRASES,
        prose_extra_phrases=EPS_PROSE_EXTRA_PHRASES,
        share_phrases=EPS_SHARE_ROW_PHRASES,
        amount_phrases=EPS_AMOUNT_ROW_PHRASES,
    ),
    "eps_proforma_refusal": EpsRefusalSpec(
        family="eps_reconciliation",
        test_id="eps_proforma_refusal",
        proforma_phrases=EPS_PROFORMA_PHRASES,
        as_reported_phrase="as reported",
    ),
}

# The refusal kinds' form-test entries (family, kind,
# test_id, points), composed into FORM_TEST_SPECS by
# form_test_specs with the shared refusal provenance.
EPS_REFUSAL_TEST_ENTRIES: tuple[tuple[str, str, str, float], ...] = (
    ("eps_reconciliation", TEST_EPS_ADJACENCY_REFUSAL, "eps_adjacency_refusal", 0.0),
    ("eps_reconciliation", TEST_EPS_PROFORMA_REFUSAL, "eps_proforma_refusal", 0.0),
)
