"""Annual report evidence definitions and semantic anchors."""

from __future__ import annotations

from dataclasses import dataclass, field

from defs.sec_forms.forms.annual.sequences import ANNUAL_ADDITIONAL_PHRASE_RULES
from defs.sec_forms.forms.annual.vocabulary import (
    INCORPORATED_REFERENCE_TERMS,
    PUBLIC_FLOAT_PHRASES,
    SHARES_PHRASES,
)
from defs.text import PhraseSequenceRule


@dataclass(frozen=True, slots=True)
class AnnualReportEvidence:
    """Evidence specific to annual and foreign annual reports."""

    incorporated_reference_terms: tuple[str, ...] = INCORPORATED_REFERENCE_TERMS
    cover_end_signals: tuple[str, ...] = (
        "table of contents",
        "part i",
        "item 1",
    )
    shape_terms: tuple[str, ...] = (
        *PUBLIC_FLOAT_PHRASES,
        *SHARES_PHRASES,
    )
    body_ngrams: tuple[str, ...] = (
        "collective bargaining",
        "labor union",
        "market segments",
        "worldwide",
        "employees",
        "customers",
        "suppliers",
        "facilities",
        "competition",
    )
    body_verbs: tuple[str, ...] = (
        "provides",
        "operates",
        "manufactures",
    )
    semantic_headings: tuple[str, ...] = (
        "management's discussion and analysis",
        "risk factors",
        "forward-looking statements",
        "safe harbor",
        "quantitative and qualitative disclosures",
        "properties",
        "legal proceedings",
        "market for registrant's common equity",
        "selected financial data",
        "changes in and disagreements with accountants",
        "controls and procedures",
        "directors, executive officers",
        "executive compensation",
        "security ownership",
        "certain relationships",
        "principal accountant fees",
        "exhibit and financial statement schedules",
    )
    healing_rules: tuple[PhraseSequenceRule, ...] = field(
        default_factory=lambda: tuple(ANNUAL_ADDITIONAL_PHRASE_RULES)
    )


__all__ = ["AnnualReportEvidence"]
