"""Location expectations for annual filings, owned by the family module.

Measured Item hosting and note-membership per classifier family, plus the
page-marker namespace expected in each region of a 10-K / 10-Q. The
classifier consults this data through its policy interface; it embeds none.
"""

from __future__ import annotations

from dataclasses import dataclass

CALIBRATION_RECORD = "run-logs/2026-11-09-table-extraction-step3-calibration.md"
STUDY_RECORD = "run-logs/2026-11-08-table-taxonomy-extractor-study.md"
STEP8C_RECORD = "run-logs/2026-11-10-table-extraction-step8c.md"
PROV_LOCATION = "step3:location_strengths"
PROV_NAMESPACE = "study:page-marker-namespaces"
PROV_PROFILE = "step8c:form_profile"

PRIOR_FORMS: tuple[str, ...] = ("10-K", "10-K/A", "10-Q", "10-Q/A")


@dataclass(frozen=True, slots=True)
class FamilyLocation:
    """One family's measured hosting: Item counts and note membership."""

    family: str
    geometries: int
    items: tuple[tuple[str | None, int], ...]
    note_rate: float
    unlocated_rate: float
    provenance: str = PROV_LOCATION


@dataclass(frozen=True, slots=True)
class NamespaceExpectation:
    """The page-marker namespace expected in one region of a form."""

    form: str
    region: str
    namespace: str
    provenance: str = PROV_NAMESPACE


FAMILY_LOCATIONS: tuple[FamilyLocation, ...] = (
    FamilyLocation("aoci", 8, ((None, 4), ("ITEM 16", 2), ("ITEM 1", 2)), 0.875, 0.125),
    FamilyLocation(
        "balance_sheet",
        117,
        (("ITEM 1", 34), ("ITEM 8", 29), ("ITEM 16", 17), (None, 13), ("ITEM 15", 11)),
        0.222,
        0.034,
    ),
    FamilyLocation(
        "cash_flow",
        151,
        (
            ("ITEM 8", 39),
            ("ITEM 1", 37),
            ("ITEM 7", 20),
            ("ITEM 16", 16),
            ("ITEM 2", 16),
        ),
        0.238,
        0.013,
    ),
    FamilyLocation("cover_layout", 1, ((None, 1),), 0.0, 0.0),
    FamilyLocation(
        "debt_maturity",
        6,
        (("ITEM 1", 2), ("ITEM 7A", 1), ("ITEM 16", 1), ("ITEM 8", 1), (None, 1)),
        0.833,
        0.167,
    ),
    FamilyLocation(
        "deferred_tax",
        44,
        (("ITEM 16", 19), ("ITEM 8", 16), ("ITEM 15", 3), (None, 3), ("ITEM 7A", 1)),
        0.864,
        0.045,
    ),
    FamilyLocation("derivatives_hedging", 2, ((None, 1), ("ITEM 16", 1)), 1.0, 0.0),
    FamilyLocation(
        "eps_reconciliation",
        24,
        (("ITEM 1", 7), ("ITEM 16", 5), ("ITEM 8", 5), ("ITEM 4", 3), ("ITEM 2", 1)),
        0.917,
        0.042,
    ),
    FamilyLocation(
        "equity_statement", 9, (("ITEM 8", 4), ("ITEM 1", 3), ("ITEM 4", 2)), 0.0, 0.0
    ),
    FamilyLocation(
        "fair_value",
        18,
        (("ITEM 1", 9), ("ITEM 8", 3), ("ITEM 4", 3), ("ITEM 16", 2), (None, 1)),
        0.889,
        0.056,
    ),
    FamilyLocation(
        "income_statement",
        154,
        (
            ("ITEM 8", 34),
            ("ITEM 1", 33),
            ("ITEM 7", 23),
            ("ITEM 16", 16),
            ("ITEM 2", 14),
        ),
        0.26,
        0.019,
    ),
    FamilyLocation(
        "intangibles", 4, (("ITEM 8", 2), ("ITEM 1", 1), ("ITEM 16", 1)), 1.0, 0.0
    ),
    FamilyLocation(
        "inventory",
        18,
        (("ITEM 1", 7), ("ITEM 8", 5), ("ITEM 16", 3), ("ITEM 7", 1), ("ITEM 4", 1)),
        0.889,
        0.0,
    ),
    FamilyLocation(
        "lease_maturity",
        17,
        (("ITEM 8", 6), ("ITEM 16", 5), ("ITEM 1", 3), ("ITEM 5", 1), (None, 1)),
        0.824,
        0.059,
    ),
    FamilyLocation(
        "other",
        6413,
        (
            ("ITEM 8", 1477),
            ("ITEM 1", 875),
            ("ITEM 15", 728),
            (None, 682),
            ("ITEM 7", 578),
        ),
        0.567,
        0.022,
    ),
    FamilyLocation("pension", 4, (("ITEM 8", 2), ("ITEM 1", 2)), 1.0, 0.0),
    FamilyLocation("ppe", 3, (("ITEM 1", 3),), 1.0, 0.0),
    FamilyLocation("shares_purchased", 2, (("ITEM 1", 1), ("ITEM 15", 1)), 1.0, 0.0),
    FamilyLocation(
        "stock_comp_rollforward",
        8,
        (("ITEM 16", 2), ("ITEM 1", 2), ("ITEM 5", 1), ("ITEM 15", 1), (None, 1)),
        0.75,
        0.125,
    ),
    FamilyLocation(
        "tax_reconciliation",
        22,
        (("ITEM 16", 10), ("ITEM 8", 6), ("ITEM 15", 2), (None, 2), ("ITEM 7A", 1)),
        0.955,
        0.045,
    ),
)

NAMESPACE_EXPECTATIONS: tuple[NamespaceExpectation, ...] = (
    NamespaceExpectation("10-K", "front_matter", "roman"),
    NamespaceExpectation("10-K", "body", "arabic"),
    NamespaceExpectation("10-K", "financial_statements", "F"),
    NamespaceExpectation("10-K", "appendix", "A"),
    NamespaceExpectation("10-Q", "front_matter", "roman"),
    NamespaceExpectation("10-Q", "body", "arabic"),
    NamespaceExpectation("10-Q", "financial_statements", "F"),
    NamespaceExpectation("10-Q", "appendix", "A"),
)


def location_priors(form: str) -> tuple[tuple[str, str, float], ...]:
    """Policy-shaped (family, Item, share) priors for a form, or none.

    Shares are the measured Item counts over each family's derivation
    geometries; Items with no detected section carry no prior.
    """
    if form not in PRIOR_FORMS:
        return ()
    return tuple(
        (spec.family, item, count / spec.geometries)
        for spec in FAMILY_LOCATIONS
        for item, count in spec.items
        if item is not None
    )


STATEMENT_ORDER: tuple[str, ...] = (
    "balance_sheet",
    "income_statement",
    "cash_flow",
    "equity_statement",
)


@dataclass(frozen=True, slots=True)
class OrderRate:
    """How often the earlier statement's first table precedes the later's."""

    earlier: str
    later: str
    rate: float
    pairs: int
    provenance: str = PROV_PROFILE


ORDER_RATES: tuple[OrderRate, ...] = (
    OrderRate("balance_sheet", "income_statement", 0.543, 70),
    OrderRate("balance_sheet", "cash_flow", 0.761, 88),
    OrderRate("balance_sheet", "equity_statement", 1.000, 6),
    OrderRate("income_statement", "cash_flow", 0.932, 74),
    OrderRate("income_statement", "equity_statement", 1.000, 6),
    OrderRate("cash_flow", "equity_statement", 0.600, 5),
)


@dataclass(frozen=True, slots=True)
class SatellitePlacement:
    """Where note-satellite tables sit relative to the statements."""

    geometries: int
    after_first_statement: int
    after_last_statement: int
    provenance: str = PROV_PROFILE


SATELLITE_PLACEMENT = SatellitePlacement(176, 176, 101)


@dataclass(frozen=True, slots=True)
class SecondSetPlacement:
    """Where second statement sets sit relative to the primary set."""

    members: int
    after_last_statement: int
    after_notes_begin: int
    provenance: str = PROV_PROFILE


SECOND_SET_PLACEMENT = SecondSetPlacement(160, 69, 105)


@dataclass(frozen=True, slots=True)
class FormProfile:
    """One form's measured statement inventory over derivation filings.

    Inventory shares are filings carrying at least one labelled
    geometry of the family over the form's derivation filings.
    """

    form: str
    filings: int
    inventory: tuple[tuple[str, float], ...]
    provenance: str = PROV_PROFILE


FORM_PROFILES: tuple[FormProfile, ...] = (
    FormProfile(
        "10-K",
        112,
        (
            ("balance_sheet", 0.420),
            ("income_statement", 0.339),
            ("cash_flow", 0.420),
            ("equity_statement", 0.036),
        ),
    ),
    FormProfile(
        "10-K/A",
        19,
        (
            ("balance_sheet", 0.316),
            ("income_statement", 0.158),
            ("cash_flow", 0.368),
            ("equity_statement", 0.000),
        ),
    ),
    FormProfile(
        "10-Q",
        70,
        (
            ("balance_sheet", 0.586),
            ("income_statement", 0.529),
            ("cash_flow", 0.600),
            ("equity_statement", 0.043),
        ),
    ),
    FormProfile(
        "10-Q/A",
        4,
        (
            ("balance_sheet", 0.000),
            ("income_statement", 0.250),
            ("cash_flow", 0.500),
            ("equity_statement", 0.000),
        ),
    ),
)


def form_profile(form: str) -> FormProfile | None:
    """The measured anatomy profile for a form, or None when unmeasured."""
    for profile in FORM_PROFILES:
        if profile.form == form:
            return profile
    return None


def order_rate(earlier: str, later: str) -> OrderRate | None:
    """The measured canonical-order rate for a statement pair, or None."""
    for spec in ORDER_RATES:
        if spec.earlier == earlier and spec.later == later:
            return spec
    return None
