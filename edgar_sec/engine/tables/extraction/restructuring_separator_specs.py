"""Restructuring separator parameter table (TEST_RESTRUCTURING_SEPARATOR).
The priced composition as built: nb_span_ge3 and restr_zeroact, both
claim-local over the candidate's grid (provenance:
PROV_RESTRUCTURING_SEPARATOR)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RestructuringSeparatorLeg:
    """One priced leg: kind, scope, and parameter. Kinds:
    no_bookend_span (claim-local); zero_activity (claim-local)."""

    leg_id: str
    kind: str
    scope: str
    limit: float = 0.0


@dataclass(frozen=True)
class RestructuringSeparatorSpec:
    """One family's separator: the ordered legs as priced. nb_span_ge3
    refuses a claim whose grid carries no bookend form and spans three
    or more distinct years; restr_zeroact refuses a claim whose walked
    balances are unchanged with no nonzero movement."""

    family: str
    legs: tuple[RestructuringSeparatorLeg, ...]


RESTRUCTURING_SEPARATOR_SPECS = {
    "restructuring": RestructuringSeparatorSpec(
        family="restructuring",
        legs=(
            RestructuringSeparatorLeg(
                "nb_span_ge3", "no_bookend_span", "claim-local", limit=3
            ),
            RestructuringSeparatorLeg(
                "restr_zeroact", "zero_activity", "claim-local"
            ),
        ),
    ),
}
