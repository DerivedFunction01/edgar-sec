"""Seat-at-floor specs, keyed by family."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.profiles import PROV_SEAT_FLOOR_PRICING


@dataclass(frozen=True, slots=True)
class SeatFloorSpec:
    """One seat-at-floor channel, declared as data: the family
    and the priced seat tests whose pass seats it."""

    family: str
    test_ids: tuple[str, ...]
    provenance: str = PROV_SEAT_FLOOR_PRICING


# Seat-at-floor specs, keyed by family: a passed seat test seats
# the family at the claim floor (claim-path pricing, R1) — the
# families' only evidence channel is the one scoring test named.
SEAT_FLOOR_SPECS: dict[str, SeatFloorSpec] = {
    "credit_losses_rollforward": SeatFloorSpec(
        family="credit_losses_rollforward",
        test_ids=("credit_losses_rollforward_evidence",),
    ),
    "goodwill_rollforward": SeatFloorSpec(
        family="goodwill_rollforward",
        test_ids=("goodwill_rollforward_measure_set",),
    ),
    "aro_rollforward": SeatFloorSpec(
        family="aro_rollforward",
        test_ids=("aro_rollforward_evidence_gate",),
    ),
    "restructuring": SeatFloorSpec(
        family="restructuring",
        test_ids=("restructuring_rollforward_evidence",),
    ),
    "warranty": SeatFloorSpec(
        family="warranty",
        test_ids=("warranty_rollforward_evidence",),
    ),
    "shares_purchased": SeatFloorSpec(
        family="shares_purchased",
        test_ids=("shares_purchased_measure_set",),
    ),
    "combined_operations_ci": SeatFloorSpec(
        family="combined_operations_ci",
        test_ids=(
            "combined_operations_ci_measure_set",
            "combined_operations_ci_joint_measure_set",
        ),
    ),
}
