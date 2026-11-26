"""Goodwill foreign-subject separator parameter table
(TEST_GOODWILL_FOREIGN_SEPARATOR). The priced composition as
built (provenance: PROV_GOODWILL_FOREIGN_SEPARATOR)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GoodwillForeignSeparatorLeg:
    """One priced leg: kind, scope, and parameter. Kinds:
    foreign_subject_zone, goodwill_not_bound (all claim-local);
    the separator fires on the conjunction."""

    leg_id: str
    kind: str
    scope: str
    limit: float = 0.0


@dataclass(frozen=True)
class GoodwillForeignSeparatorSpec:
    """One family's foreign-subject separator: the priced legs,
    held conjunctively — a foreign walked subject bound in the
    stub/header zone, with goodwill not a bound subject there."""

    family: str
    legs: tuple[GoodwillForeignSeparatorLeg, ...]


# The intangible-asset class vocabulary whose binding in a
# stub/header zone marks a foreign walked subject.
FOREIGN_CLASS_TERMS = (
    "customer relationship",
    "customer trust",
    "customer list",
    "trade name",
    "trademark",
    "patent",
    "masthead",
    "core deposit",
    "publishing right",
    "land use right",
    "rare earth quota",
    "franchise right",
    "developed technology",
    "capitalized software",
    "covenant not to compete",
    "non-compete",
    "subscriber relationship",
    "advertiser relationship",
)

# Statement titles whose binding in the header zone marks the
# geometry as a primary-statement page, not a note walk.
STATEMENT_TITLE_TERMS = (
    "statements of operations",
    "statements of cash flows",
    "consolidated statements",
    "cash flows from operating activities",
)


GOODWILL_FOREIGN_SEPARATOR_SPECS = {
    "goodwill_rollforward": GoodwillForeignSeparatorSpec(
        family="goodwill_rollforward",
        legs=(
            GoodwillForeignSeparatorLeg(
                "foreign_subject_zone", "foreign_subject_zone", "claim-local"
            ),
            GoodwillForeignSeparatorLeg(
                "goodwill_not_bound", "goodwill_not_bound", "claim-local"
            ),
        ),
    ),
}
