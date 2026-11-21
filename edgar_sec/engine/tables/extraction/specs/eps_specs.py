"""EPS seat parameters: the priced rule as data.
The depth-3 detector cell's vocabularies and thresholds,
declared once here for the eps_evidence evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.profiles import PROV_R18_SEAT_PRICING


@dataclass(frozen=True, slots=True)
class EpsEvidenceSpec:
    """EPS seat parameters, declared as data.
    The priced rule's vocabularies and thresholds."""

    family: str
    test_id: str
    lead_term: str
    anatomy_terms: tuple[str, ...]
    walk_terms: tuple[str, ...]
    title_terms: tuple[str, ...]
    change_terms: tuple[str, ...]
    foot_threshold: int = 60
    walk_min_rows: int = 3
    provenance: str = PROV_R18_SEAT_PRICING


# EPS seat specs, keyed by family: the one literal home of
# the kind's parameters, priced by the depth-3 run over the
# R18 population (seat 30 TP / 0 FP / 0 FN).
EPS_EVIDENCE_SPECS: dict[str, EpsEvidenceSpec] = {
    "eps_reconciliation": EpsEvidenceSpec(
        family="eps_reconciliation",
        test_id="eps_evidence",
        lead_term="basic and",
        anatomy_terms=(
            "per share",
            "per common",
            "per unit",
            "denominator",
            "numerator",
            "shares",
            "dilutive",
            "diluted",
            "basic",
            "weighted",
            "equivalents",
        ),
        walk_terms=(
            "revenue",
            "sales",
            "cost of",
            "gross profit",
            "gross margin",
            "operating expense",
            "operating income",
            "operating loss",
            "selling",
            "general and administrative",
            "research and development",
            "r&d",
            "s&m",
            "g&a",
            "depreciation",
            "amortization",
            "interest income",
            "interest expense",
            "interest and dividend",
            "noninterest",
            "provision for",
            "income tax",
            "total expenses",
            "costs and expenses",
            "other income",
            "other expense",
            "earnings before",
            "income before",
            "loss before",
            "commissions and fees",
            "fee revenue",
            "service charges",
        ),
        title_terms=(
            "statements of operations",
            "statements of income",
            "statements of earnings",
            "statement of operations",
            "statement of income",
            "statement of earnings",
            "statements of comprehensive",
            "statement of comprehensive",
            "results of operations",
            "quarterly results",
        ),
        change_terms=("% change", "percentage change", "variance"),
    ),
}

# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy.
EPS_EVIDENCE_SPECS_BY_TEST_ID: dict[str, EpsEvidenceSpec] = {
    spec.test_id: spec for spec in EPS_EVIDENCE_SPECS.values()
}
