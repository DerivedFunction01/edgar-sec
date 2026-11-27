"""Goodwill sibling-mass separator parameter table
(TEST_GOODWILL_SIBLING_SEPARATOR). The priced composition as
built (provenance: PROV_GOODWILL_SIBLING_SEPARATOR)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GoodwillSiblingSeparatorLeg:
    """One priced leg: kind, scope, and parameter. Kinds:
    sibling_mass, goodwill_not_stub_subject (all claim-local);
    the separator fires on the conjunction."""

    leg_id: str
    kind: str
    scope: str
    limit: float = 0.0


@dataclass(frozen=True)
class GoodwillSiblingSeparatorSpec:
    """One family's sibling-mass separator: the priced legs,
    held conjunctively — at least two stub rows carrying
    sibling intangibles-class terms, and no stub row binding
    goodwill as a subject of the grid."""

    family: str
    legs: tuple[GoodwillSiblingSeparatorLeg, ...]


# The sibling intangibles-class vocabulary: a stub row
# carrying any of these terms counts toward the sibling mass.
SIBLING_CLASS_TERMS = (
    "intangible",
    "masthead",
    "trademark",
    "customer",
    "patent",
    "license",
    "trade name",
    "copyright",
    "franchise",
    "noncompete",
    "non-compete",
    "favorable",
    "deferred financing",
    "indefinite",
)


GOODWILL_SIBLING_SEPARATOR_SPECS = {
    "goodwill_rollforward": GoodwillSiblingSeparatorSpec(
        family="goodwill_rollforward",
        legs=(
            GoodwillSiblingSeparatorLeg(
                "sibling_mass", "sibling_mass", "claim-local", 2.0
            ),
            GoodwillSiblingSeparatorLeg(
                "goodwill_not_stub_subject",
                "goodwill_not_stub_subject",
                "claim-local",
            ),
        ),
    ),
}
