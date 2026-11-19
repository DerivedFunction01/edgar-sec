"""Credit separator parameter table (TEST_CREDIT_SEPARATOR).
The priced claim-local legs as built, in firing order
(provenance: PROV_CREDIT_SEPARATOR); the movement vocabulary
stays homed in credit_losses_specs.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CreditSeparatorLeg:
    """One separator leg: kind and scope. Kinds: movement_count,
    loan_movement (both claim-local)."""

    leg_id: str
    kind: str
    scope: str


@dataclass(frozen=True)
class CreditSeparatorSpec:
    """One family's separator: the ordered legs plus the
    movement-count terms. The count runs over the seat home's
    movement kinds minus excluded_count_kind; the loan leg
    reads row stubs."""

    family: str
    legs: tuple[CreditSeparatorLeg, ...]
    min_movement_kinds: int
    excluded_count_kind: str
    loan_terms: tuple[str, ...]
    bookend_term: str
    bookend_qualifiers: tuple[str, ...]


CREDIT_SEPARATOR_SPECS = {
    "credit_losses_rollforward": CreditSeparatorSpec(
        family="credit_losses_rollforward",
        legs=(
            CreditSeparatorLeg("movement_count", "movement_count", "claim-local"),
            CreditSeparatorLeg("loan_movement", "loan_movement", "claim-local"),
        ),
        min_movement_kinds=2,
        excluded_count_kind="net_chargeoffs",
        loan_terms=(
            "originated",
            "draws",
            "principal",
            "collections",
            "advances",
            "new loans",
        ),
        bookend_term="allowance",
        bookend_qualifiers=("beginning", "ending", "balance"),
    ),
}
