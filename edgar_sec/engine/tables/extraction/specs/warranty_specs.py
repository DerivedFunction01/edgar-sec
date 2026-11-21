"""Warranty seat parameters: the priced core as registry data.
The dialect cure's vocabularies, declared once here for the
warranty_evidence evaluator (credit_losses_specs precedent).
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.profiles import PROV_WARRANTY_PRICING


@dataclass(frozen=True, slots=True)
class WarrantyEvidenceSpec:
    """Warranty-evidence gate parameters, declared as data.
    The claim is the priced conjunction: an anchored subject,
    the bookend pair in any filed form, one movement type."""

    family: str
    test_id: str
    subject_pattern: str
    prose_tail_chars: int
    header_zone_lines: int
    frag_zone_lines: int
    abbrev_months: tuple[str, ...]
    anchors: tuple[str, ...]
    move_types: tuple[tuple[str, tuple[str, ...]], ...]
    extra_move_terms: tuple[tuple[str, str], ...]
    provenance: str = PROV_WARRANTY_PRICING


# Warranty-evidence gate specs, keyed by family: the one literal
# home of the gate kind's parameters, priced on the completed
# adjudication base by the base, cure, and depth-2 passes.
WARRANTY_EVIDENCE_SPECS: dict[str, WarrantyEvidenceSpec] = {
    "warranty": WarrantyEvidenceSpec(
        family="warranty",
        test_id="warranty_rollforward_evidence",
        subject_pattern=r"warrant(y|ies)",
        prose_tail_chars=400,
        header_zone_lines=3,
        frag_zone_lines=12,
        abbrev_months=(
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "sept",
            "oct",
            "nov",
            "dec",
        ),
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
                "accrual",
                (
                    "accrual",
                    "additions",
                    "provision",
                    "warranties issued",
                    "issued",
                    "charges",
                    "costs incurred",
                ),
            ),
            (
                "claims",
                (
                    "claims",
                    "settlements",
                    "settled",
                    "payments",
                    "paid",
                    "cash paid",
                ),
            ),
            (
                "adjustment",
                (
                    "adjustments",
                    "changes in estimates",
                    "change in estimate",
                    "revisions",
                    "deductions",
                ),
            ),
            ("fx", ("foreign currency", "translation", "currency")),
            (
                "usage",
                ("consumption", "fulfilled", "utilization", "utilized"),
            ),
        ),
        extra_move_terms=(
            ("charged", "accrual"),
            ("expenditures", "claims"),
            ("usage", "usage"),
            ("warranty expense", "accrual"),
            ("repairs", "claims"),
            ("replacements", "claims"),
            ("charge-off", "adjustment"),
            ("charge off", "adjustment"),
            ("charged off", "adjustment"),
            ("incurred", "accrual"),
        ),
    ),
}

# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy.
WARRANTY_EVIDENCE_SPECS_BY_TEST_ID: dict[str, WarrantyEvidenceSpec] = {
    spec.test_id: spec for spec in WARRANTY_EVIDENCE_SPECS.values()
}
