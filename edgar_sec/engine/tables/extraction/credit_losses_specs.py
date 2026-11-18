"""Credit-losses seat parameters: the priced rule as registry data.

The subject cure's vocabularies, declared once here for the
credit_losses_evidence evaluator (measure_set_specs precedent).
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.profiles import PROV_S5_SEAT_PRICING


@dataclass(frozen=True, slots=True)
class CreditLossesEvidenceSpec:
    """Credit-losses seat parameters, declared as data.

    The claim is the priced conjunction: a rank-1 subject, the
    arm-3 bookend pair in any filed form, one movement element.
    """

    family: str
    test_id: str
    subject_phrases: tuple[tuple[str, str], ...]
    r1_keys: tuple[str, ...]
    bare_key: str
    carrier_phrases: tuple[str, ...]
    movement_elements: tuple[tuple[str, tuple[str, ...]], ...]
    movement_base_keys: tuple[str, ...]
    movement_ext_keys: tuple[str, ...]
    schedule_markers: tuple[str, ...]
    schedule_keys: tuple[str, ...]
    bookend_x_begin: tuple[str, ...]
    bookend_x_end: tuple[str, ...]
    anchor_words: tuple[str, ...]
    da_phrase: str
    provenance: str = PROV_S5_SEAT_PRICING


CREDIT_LOSSES_EVIDENCE_SPECS: dict[str, CreditLossesEvidenceSpec] = {
    "credit_losses_rollforward": CreditLossesEvidenceSpec(
        family="credit_losses_rollforward",
        test_id="credit_losses_rollforward_evidence",
        subject_phrases=(
            ("acl", "allowance for credit losses"),
            ("alll", "allowance for loan losses"),
            ("allll", "allowance for loan and lease losses"),
            ("credit_loss_bare", "credit loss"),
            ("valuation_schedule", "valuation and qualifying accounts"),
        ),
        r1_keys=("acl", "alll", "allll"),
        bare_key="credit_loss_bare",
        carrier_phrases=(
            "allowance for credit losses",
            "allowance for loan losses",
            "allowance for loan and lease losses",
            "credit loss",
        ),
        movement_elements=(
            ("provision", ("provision",)),
            (
                "writeoff",
                (
                    "write-off",
                    "writeoff",
                    "write off",
                    "write_offs",
                    "charged off",
                    "charge-off",
                    "chargeoff",
                    "charge off",
                    "losses charged",
                    "loans charged",
                ),
            ),
            ("recoveries", ("recover",)),
            (
                "pcd",
                ("purchased credit deteriorated", " pcd ", "pcd assets"),
            ),
            ("fx", ("foreign currency", "exchange rate")),
            (
                "transition",
                (
                    "adopting asc 326",
                    "adoption of asc 326",
                    "adopting the new",
                    "cumulative effect",
                ),
            ),
            (
                "sx_additions",
                (
                    "charged to costs and expenses",
                    "charged to operations",
                    "charged to other accounts",
                ),
            ),
            ("sx_deductions", ("deductions",)),
            ("net_chargeoffs", ("net charge-off", "net chargeoff")),
        ),
        movement_base_keys=(
            "provision",
            "writeoff",
            "recoveries",
            "sx_deductions",
        ),
        movement_ext_keys=(
            "sx_additions",
            "transition",
            "pcd",
            "fx",
            "net_chargeoffs",
        ),
        schedule_markers=("valuation and qualifying accounts", "schedule ii"),
        schedule_keys=("sx_additions", "sx_deductions"),
        bookend_x_begin=(
            "balance at beginning",
            "beginning of period",
            "beginning of year",
            "beginning of the period",
            "beginning of the year",
        ),
        bookend_x_end=(
            "balance at end",
            "end of period",
            "end of year",
            "end of the year",
            "balance at the end",
        ),
        anchor_words=(
            "balance",
            "allowance",
            "beginning",
            "ending",
            "end of",
            "as of",
        ),
        da_phrase="allowance for doubtful accounts",
    ),
}

CREDIT_LOSSES_EVIDENCE_SPECS_BY_TEST_ID: dict[str, CreditLossesEvidenceSpec] = {
    spec.test_id: spec for spec in CREDIT_LOSSES_EVIDENCE_SPECS.values()
}
