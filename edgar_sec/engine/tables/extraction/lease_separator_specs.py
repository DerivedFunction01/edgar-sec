"""Lease separator parameter table (TEST_LEASE_SEPARATOR).
The priced legs as built: spanprod_le_2 reads the candidate's
stub+header years, assign_sibling_seat reads the debt seat's
stamped outcomes, subj_before400 reads the subject lead over
caption + prose_before tail (provenance: PROV_LEASE_SEPARATOR).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LeaseSeparatorLeg:
    """One priced leg: kind, scope, and parameters. Kinds: span
    (claim-local); assign_sibling (set-level joint assignment
    anchored on the sibling family's seat outcomes); subject
    (claim-local regex over caption + prose_before tail)."""

    leg_id: str
    kind: str
    scope: str
    limit: float = 0.0
    anchor_family: str = ""
    pattern: str = ""
    tail: int = 0


@dataclass(frozen=True)
class LeaseSeparatorSpec:
    """One family's separator: the ordered legs as priced: span
    (stub+header year span), assign_sibling (debt seat's outcomes),
    subject (financing-liability lead over caption + prose tail)."""

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
            LeaseSeparatorLeg(
                "subj_before400",
                "subject",
                "claim-local",
                pattern="financing (liability|obligation)",
                tail=400,
            ),
        ),
    ),
}
