"""Legal proceedings, litigation, shareholder actions, and contingency taxonomy (ASC 450)."""

from __future__ import annotations

from defs.text.compounds import (
    expand_alternations,
    expand_compounds,
    expand_variants,
)

# Core litigation & proceeding terms
LEGAL_LITIGATION_TERMS: tuple[str, ...] = (
    "lawsuit",
    "lawsuits",
    "litigation",
    "arbitration proceeding",
    "arbitration proceedings",
    "arbitration hearing",
    "arbitration case",
    "legal action",
    "legal actions",
    "legal proceeding",
    "legal proceedings",
    "legal dispute",
    "legal disputes",
    "civil action",
    "civil actions",
    "civil suit",
    "civil suits",
    "civil proceeding",
    "civil proceedings",
    "criminal action",
    "criminal actions",
    "criminal proceeding",
    "criminal proceedings",
    "criminal charges",
    "administrative action",
    "administrative proceeding",
    "administrative proceedings",
    "regulatory investigation",
    "regulatory proceedings",
    "governmental investigation",
    "subpoena",
    "subpoenas",
)

# Specialized actions and shareholder suits
LEGAL_PROCEEDING_TERMS: tuple[str, ...] = expand_alternations(
    (
        "securities litigation",
        "securities fraud",
        "class action lawsuit",
        "class action lawsuits",
        "class action litigation",
        "shareholder lawsuit",
        "shareholder lawsuits",
        "shareholder litigation",
        "shareholder suit",
        "shareholder derivative",
        "shareholder derivative action",
        "shareholder derivative actions",
        "shareholder derivative lawsuit",
        "shareholder derivative lawsuits",
        "shareholder derivative litigation",
        "shareholder derivative suit",
        "derivative action",
        "derivative actions",
        "derivative lawsuit",
        "derivative lawsuits",
        "derivative litigation",
        "derivative suit",
        "derivative suits",
        "derivative claim",
        "derivative claims",
        "derivative proceeding",
        "derivative proceedings",
        "derivative settlement",
        "derivative complaint",
        "derivative plaintiff",
        "patent infringement",
        "patent litigation",
        "antitrust litigation",
        "environmental enforcement action",
        "product liability litigation",
        "breach of fiduciary duty",
    ),
    expand_compounds(
        ("shareholder", "stockholder"),
        (
            "derivative action",
            "derivative lawsuit",
            "derivative suit",
            "derivative litigation",
            "derivative claim",
        ),
    ),
)

# Parties, court actions, verdicts & settlements
LEGAL_PARTY_COURT_TERMS: tuple[str, ...] = (
    "plaintiff",
    "plaintiffs",
    "defendant",
    "defendants",
    "claimant",
    "claimants",
    "respondent",
    "respondents",
    "nominal defendant",
    "co-defendant",
    "co-defendants",
    "court case",
    "court proceeding",
    "court order",
    "judgment rendered",
    "consent decree",
    "injunctive relief",
    "injunction",
    "dismissed with prejudice",
    "dismissed without prejudice",
    "motion to dismiss",
    "summary judgment",
    "plea agreement",
    "settlement agreement",
    "settlement agreements",
    "convicted of",
    "pled guilty",
    "plea bargain",
)

# Competitor & industry peer dispute terms
LEGAL_COMPETITOR_TERMS: tuple[str, ...] = expand_variants(
    (
        "competitor litigation",
        "competitor dispute",
        "peer group dispute",
        "market participant dispute",
    )
)


# Loss contingencies (ASC 450)
LEGAL_CONTINGENCY_TERMS: tuple[str, ...] = (
    "loss contingency",
    "loss contingencies",
    "probable loss",
    "reasonably possible loss",
    "accrued legal loss",
    "accrued legal contingency",
    "range of loss cannot be estimated",
    "range of reasonably possible loss",
    "legal loss contingency",
)

LEGAL_UNIGRAM_VETOES: tuple[str, ...] = (
    "lawsuit",
    "lawsuits",
    "litigation",
    "arbitration",
    "plaintiff",
    "plaintiffs",
    "defendant",
    "defendants",
    "indicted",
    "indictment",
    "subpoena",
    "subpoenas",
    "chancery",
)

LEGAL_ALL_TERMS: tuple[str, ...] = expand_alternations(
    LEGAL_LITIGATION_TERMS,
    LEGAL_PROCEEDING_TERMS,
    LEGAL_PARTY_COURT_TERMS,
    LEGAL_COMPETITOR_TERMS,
    LEGAL_CONTINGENCY_TERMS,
)

__all__ = [
    "LEGAL_ALL_TERMS",
    "LEGAL_COMPETITOR_TERMS",
    "LEGAL_CONTINGENCY_TERMS",
    "LEGAL_LITIGATION_TERMS",
    "LEGAL_PARTY_COURT_TERMS",
    "LEGAL_PROCEEDING_TERMS",
    "LEGAL_UNIGRAM_VETOES",
]
