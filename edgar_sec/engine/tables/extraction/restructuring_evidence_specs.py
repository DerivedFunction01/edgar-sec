"""Restructuring-evidence gate specs: the kind's declared data.
The evaluator consumes these parameters as data; the stage
adapter resolves the same parameters by test_id at load.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.profiles import (
    PROV_RESTRUCTURING_PRICING,
)


@dataclass(frozen=True, slots=True)
class RestructuringEvidenceSpec:
    """Restructuring-evidence gate parameters, declared as data.
    The claim is the priced conjunction: subject anchored, a bookend
    pair in any filed form, a movement type, no loan context."""

    family: str
    test_id: str
    subject_terms: tuple[str, ...]
    prose_tail_chars: int
    anchors: tuple[str, ...]
    move_types: tuple[tuple[str, tuple[str, ...]], ...]
    extra_move_terms: tuple[tuple[str, str], ...]
    costs_row_term: str
    costs_row_type: str
    costs_row_excluded_term: str
    loan_terms: tuple[str, ...]
    head_prose_chars: int
    head_text_chars: int
    loan_full_chars: int
    header_zone_lines: int = 3
    provenance: str = PROV_RESTRUCTURING_PRICING


# Restructuring-evidence gate specs, keyed by family: the one
# literal home of the gate kind's parameters, priced on the
# completed adjudication base (444 specimens).
RESTRUCTURING_EVIDENCE_SPECS: dict[str, RestructuringEvidenceSpec] = {
    "restructuring": RestructuringEvidenceSpec(
        family="restructuring",
        test_id="restructuring_rollforward_evidence",
        subject_terms=(
            "restructuring",
            "exit cost",
            "exit activities",
            "employee separation",
            "separation costs",
            "reduction in force",
        ),
        prose_tail_chars=400,
        anchors=(
            "balance",
            "accrual",
            "accrued",
            "liability",
            "liabilities",
            "reserve",
            "obligation",
            "obligations",
        ),
        move_types=(
            (
                "charge",
                (
                    "charges",
                    "incurred",
                    "costs incurred",
                    "accrued",
                    "additions",
                    "provision",
                    "expensed",
                    "charged to expense",
                    "charged to earnings",
                    "costs charged",
                ),
            ),
            (
                "payment",
                (
                    "payments",
                    "paid",
                    "settlements",
                    "settled",
                    "cash paid",
                    "spending",
                    "uses",
                    "utilization",
                    "utilized",
                    "amounts applied",
                    "outflow",
                    "deductions",
                ),
            ),
            (
                "adjustment",
                (
                    "adjustments",
                    "revisions",
                    "changes in estimates",
                    "change in estimate",
                ),
            ),
            ("reversal", ("reversals", "reversed")),
            ("fx", ("foreign currency", "translation", "currency")),
            ("accretion", ("accretion",)),
        ),
        extra_move_terms=(
            ("accruals", "charge"),
            ("expenditures", "payment"),
        ),
        costs_row_term="costs",
        costs_row_type="charge",
        costs_row_excluded_term="balance",
        loan_terms=(
            "troubled debt",
            "allowance for credit losses",
            "impaired loans",
            "loan modifications",
            "modifications to borrowers",
            "nonaccrual loans",
            "mortgage servicing rights",
            "credit loss",
        ),
        head_prose_chars=400,
        head_text_chars=2500,
        loan_full_chars=4000,
        header_zone_lines=3,
    ),
}

# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy.
RESTRUCTURING_EVIDENCE_SPECS_BY_TEST_ID: dict[str, RestructuringEvidenceSpec] = {
    spec.test_id: spec for spec in RESTRUCTURING_EVIDENCE_SPECS.values()
}
