"""Lease separator parameter table (TEST_LEASE_SEPARATOR).
The priced pair as built: spanprod_le_2 reads the candidate's
stub+header years, assign_sibling_seat reads the debt seat's
stamped outcomes (provenance: PROV_LEASE_SEPARATOR).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LeaseSeparatorLeg:
    """One priced leg: kind, scope, and parameter. Kinds: span
    (claim-local); assign_sibling (set-level joint assignment
    anchored on the sibling family's seat outcomes)."""

    leg_id: str
    kind: str
    scope: str
    limit: float = 0.0
    anchor_family: str = ""


@dataclass(frozen=True)
class LeaseSeparatorSpec:
    """One family's separator: the ordered legs as priced.
    spanprod_le_2 refuses a claim whose stub+header spans two or fewer
    distinct years; assign_sibling_seat refuses one the debt seat seated."""

    family: str
    legs: tuple[LeaseSeparatorLeg, ...]


LEASE_SEPARATOR_SPECS = {
    "lease_maturity": LeaseSeparatorSpec(
        family="lease_maturity",
        legs=(
            LeaseSeparatorLeg("spanprod_le_2", "span", "claim-local", limit=2),
            LeaseSeparatorLeg(
                "assign_sibling_seat",
                "assign_sibling",
                "set-level",
                anchor_family="debt_maturity",
            ),
        ),
    ),
}
