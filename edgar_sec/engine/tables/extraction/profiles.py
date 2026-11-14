"""Family-profile registry: the single home of classifier profiles."""

from __future__ import annotations

from dataclasses import dataclass

PROV_STEP6_VERDICT = "step6:verdict-2026-11-14"
PROV_STEP6_MEASUREMENT = "step6:measurement-2026-11-14"
PROV_STEP0_RETIREMENT = "refresh-step0:retirement-2026-11-14"
PROV_DEMOGRAPHICS = "step6:demographics-line"
PROV_LABOR = "step6:labor-capture-row"
PROV_EX13 = "step6:ex13-census"

# Strata are the Step 6 measurement strata: B is the annual
# stratum, D the quarterly stratum. Profiles carry stratum
# codes, never form names (R5: no hardcoded forms).
STRATUM_ANNUAL = "B"
STRATUM_QUARTERLY = "D"

# R6 is ruled genre-layer only: no family profile declares a
# prose window, so every profile carries this value.
PROSE_WINDOW_NONE = "none"

KIND_FAMILY = "family"
KIND_PROSE_PROFILE = "prose_profile"
KIND_GENRE_SEAT = "genre_seat"

SEAT_SIGNATURE = "signature_competition"
SEAT_ASSEMBLY = "assembly"
SEAT_NOTE_TITLE_CONTENT = "note_title_content"
SEAT_PROSE_CAPTURE = "prose_capture"
SEAT_GENRE_REFUSAL = "genre_refusal"
SEAT_REGION_GATED = "region_gated"

# Form-test declarations (R1): names only, as registry data.
# The stage and the test classes themselves build in Step 3.
TEST_WALK = "beginning_ending_walk"
TEST_LADDER = "year_ladder"
TEST_PERCENTAGE_FORM = "percentage_form"
TEST_PRIMARY_STATEMENT_SEAT = "primary_statement_seat"
TEST_COMPOSITION_TWIN = "composition_twin"
TEST_SEGMENT_FORM = "segment_form"
TEST_DERIVATIVES_EVIDENCE = "derivatives_evidence_gate"
FORM_TESTS = (
    TEST_WALK,
    TEST_LADDER,
    TEST_PERCENTAGE_FORM,
    TEST_PRIMARY_STATEMENT_SEAT,
    TEST_COMPOSITION_TWIN,
    TEST_SEGMENT_FORM,
    TEST_DERIVATIVES_EVIDENCE,
)


@dataclass(frozen=True, slots=True)
class SupportState:
    """Step 6 support for one family: precision/recall per stratum."""

    annual_precision: float | None
    annual_recall: float | None
    quarterly_precision: float | None
    quarterly_recall: float | None
    quarterly_directed_recall: float | None = None
    assembly_quarterly_precision: float | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class ExhibitLink:
    """One exhibit type declared as an evidence source (R3)."""

    exhibit_type: str
    strata: tuple[str, ...]
    provenance: str = PROV_EX13


@dataclass(frozen=True, slots=True)
class FamilyProfile:
    """One supported family's profile: support, seat, tests, links."""

    family: str
    kind: str
    support: SupportState | None
    vocabulary_seat: str
    form_tests: tuple[str, ...] = ()
    gate_bindings: tuple[str, ...] = ()
    exhibit_links: tuple[ExhibitLink, ...] = ()
    prose_window: str = PROSE_WINDOW_NONE
    region_gate: str | None = None
    shape: str | None = None
    note: str = ""
    provenance: str = PROV_STEP6_VERDICT


@dataclass(frozen=True, slots=True)
class RetiredFamily:
    """A family retired as registry data; it carries no profile."""

    family: str
    reason: str
    provenance: str = PROV_STEP0_RETIREMENT


def _support(
    annual_p: float | None,
    annual_r: float | None,
    quarterly_p: float | None,
    quarterly_r: float | None,
    **kwargs: float | str,
) -> SupportState:
    return SupportState(annual_p, annual_r, quarterly_p, quarterly_r, **kwargs)


_EX13_ANNUAL = (ExhibitLink("EX-13", (STRATUM_ANNUAL,)),)
_STATEMENT_GATES = ("toc_gate", "section_gate")

PROFILES: tuple[FamilyProfile, ...] = (
    FamilyProfile(
        "aoci_rollforward",
        KIND_FAMILY,
        _support(0.146, 0.500, 0.238, 0.278, assembly_quarterly_precision=0.083),
        SEAT_SIGNATURE,
        form_tests=(TEST_WALK,),
        gate_bindings=("aoci_gate",),
        note="assembly-seat quarterly precision is the reconciled .083",
    ),
    FamilyProfile(
        "balance_sheet",
        KIND_FAMILY,
        _support(0.231, 1.000, 0.381, 0.962),
        SEAT_SIGNATURE,
        form_tests=(TEST_PRIMARY_STATEMENT_SEAT,),
        gate_bindings=_STATEMENT_GATES,
        exhibit_links=_EX13_ANNUAL,
    ),
    FamilyProfile(
        "cash_flow",
        KIND_FAMILY,
        _support(0.576, 0.833, 0.218, 1.000),
        SEAT_SIGNATURE,
        form_tests=(TEST_PRIMARY_STATEMENT_SEAT,),
        gate_bindings=_STATEMENT_GATES,
        exhibit_links=_EX13_ANNUAL,
    ),
    FamilyProfile(
        "comprehensive_income",
        KIND_FAMILY,
        _support(0.623, 0.750, 0.871, 0.625),
        SEAT_SIGNATURE,
        form_tests=(TEST_WALK,),
        gate_bindings=("section_gate",),
        exhibit_links=_EX13_ANNUAL,
    ),
    FamilyProfile(
        "debt_maturity",
        KIND_FAMILY,
        _support(0.423, 0.167, 0.010, 0.000),
        SEAT_SIGNATURE,
        form_tests=(TEST_LADDER,),
    ),
    FamilyProfile(
        "deferred_tax",
        KIND_FAMILY,
        _support(0.589, 1.000, 0.519, None, quarterly_directed_recall=0.942),
        SEAT_SIGNATURE,
        form_tests=(TEST_WALK, TEST_COMPOSITION_TWIN),
        note="quarterly recall unmeasured on the sealed sweep (n=0); "
        "the directed rate is the recall evidence of record",
    ),
    FamilyProfile(
        "derivatives_hedging",
        KIND_FAMILY,
        _support(0.691, 0.786, 0.714, 0.826),
        SEAT_SIGNATURE,
        form_tests=(TEST_DERIVATIVES_EVIDENCE,),
        note="quarterly readings are the reconciled record read "
        "(precision .714, recall .826)",
    ),
    FamilyProfile(
        "eps_reconciliation",
        KIND_FAMILY,
        _support(0.041, 1.000, 0.477, 0.800),
        SEAT_SIGNATURE,
        form_tests=(TEST_WALK,),
    ),
    FamilyProfile(
        "equity_statement",
        KIND_FAMILY,
        _support(0.316, 1.000, 0.315, 0.769),
        SEAT_SIGNATURE,
        form_tests=(TEST_PRIMARY_STATEMENT_SEAT,),
        gate_bindings=_STATEMENT_GATES,
        exhibit_links=_EX13_ANNUAL,
    ),
    FamilyProfile(
        "fair_value",
        KIND_FAMILY,
        _support(0.812, 0.692, 0.853, 0.674),
        SEAT_SIGNATURE,
        form_tests=(TEST_COMPOSITION_TWIN,),
    ),
    FamilyProfile(
        "income_statement",
        KIND_FAMILY,
        _support(0.000, 0.733, 0.112, 0.862),
        SEAT_SIGNATURE,
        form_tests=(TEST_PRIMARY_STATEMENT_SEAT,),
        gate_bindings=_STATEMENT_GATES,
        exhibit_links=_EX13_ANNUAL,
    ),
    FamilyProfile(
        "intangibles",
        KIND_FAMILY,
        _support(0.349, 0.857, 0.543, 0.750),
        SEAT_SIGNATURE,
        form_tests=(TEST_COMPOSITION_TWIN,),
    ),
    FamilyProfile(
        "inventory",
        KIND_FAMILY,
        _support(0.710, 0.714, 0.829, 0.667),
        SEAT_SIGNATURE,
        form_tests=(TEST_COMPOSITION_TWIN,),
    ),
    FamilyProfile(
        "lease_maturity",
        KIND_FAMILY,
        _support(0.553, 1.000, 0.215, 1.000),
        SEAT_SIGNATURE,
        form_tests=(TEST_COMPOSITION_TWIN,),
    ),
    FamilyProfile(
        "pension",
        KIND_FAMILY,
        _support(0.347, 0.778, 0.525, 0.909),
        SEAT_SIGNATURE,
        form_tests=(TEST_COMPOSITION_TWIN,),
    ),
    FamilyProfile(
        "ppe",
        KIND_FAMILY,
        _support(0.539, 0.800, 0.562, 1.000),
        SEAT_SIGNATURE,
        form_tests=(TEST_COMPOSITION_TWIN,),
    ),
    FamilyProfile(
        "related_party",
        KIND_FAMILY,
        _support(0.389, 0.200, 0.643, 0.333),
        SEAT_NOTE_TITLE_CONTENT,
        gate_bindings=("content_gate",),
        note="host-form share of true instances is a named recall "
        "ceiling: its evidence sits in note prose, and R6 rules "
        "prose windows genre-layer only",
    ),
    FamilyProfile(
        "segment_reporting",
        KIND_FAMILY,
        _support(0.866, 0.276, 0.625, 0.241),
        SEAT_NOTE_TITLE_CONTENT,
        form_tests=(TEST_SEGMENT_FORM,),
        gate_bindings=("content_gate",),
    ),
    FamilyProfile(
        "stock_comp_rollforward",
        KIND_FAMILY,
        _support(0.234, 1.000, 0.255, 1.000),
        SEAT_SIGNATURE,
        form_tests=(TEST_WALK,),
    ),
    FamilyProfile(
        "tax_reconciliation",
        KIND_FAMILY,
        _support(0.432, 1.000, 0.000, None, quarterly_directed_recall=0.758),
        SEAT_SIGNATURE,
        form_tests=(TEST_PERCENTAGE_FORM,),
        note="quarterly recall unmeasured on the sealed sweep (n=0); "
        "the directed rate is the recall evidence of record",
    ),
    FamilyProfile(
        "commitments_contingencies",
        KIND_FAMILY,
        _support(0.583, 0.100, 0.417, 0.000),
        SEAT_ASSEMBLY,
        form_tests=(TEST_LADDER,),
        gate_bindings=("assembly_seat",),
    ),
    FamilyProfile(
        "labor_capture",
        KIND_PROSE_PROFILE,
        None,
        SEAT_PROSE_CAPTURE,
        shape="employee group x contract x union",
        note="prose-side converter, outside the geometry verdict: "
        "population precision/recall undefined at n=0 population "
        "specimens; directed census presence .071 (26 of 365 judged)",
        provenance=PROV_LABOR,
    ),
    FamilyProfile(
        "demographics",
        KIND_FAMILY,
        None,
        SEAT_REGION_GATED,
        region_gate="Item 1, human-capital lead-in",
        shape="demographic x geography/composition; integers and percents; no currency",
        note="owner-admitted profile: sealed presence 6 specimens, "
        "all annual stratum, base rate ~1 per 10,000 annual "
        "geometries, 0 quarterly; directed verified presence .134",
        provenance=PROV_DEMOGRAPHICS,
    ),
    FamilyProfile(
        "cover_layout",
        KIND_GENRE_SEAT,
        None,
        SEAT_GENRE_REFUSAL,
        note="genre claimant in the measured vocabulary; no Step 6 family verdict row",
    ),
    FamilyProfile(
        "shares_purchased",
        KIND_GENRE_SEAT,
        None,
        SEAT_GENRE_REFUSAL,
        note="genre claimant in the measured vocabulary; no Step 6 family verdict row",
    ),
    FamilyProfile(
        "other",
        KIND_GENRE_SEAT,
        None,
        SEAT_GENRE_REFUSAL,
        note="residual seat: genre refusals and below-floor residue "
        "land here; it competes for nothing",
    ),
)

PROFILES_BY_FAMILY = {profile.family: profile for profile in PROFILES}

RETIRED_FAMILIES: tuple[RetiredFamily, ...] = (
    RetiredFamily(
        "subsequent_events",
        "structurally undecidable from free text (Step 6 specimen "
        "proof); retired at Step 0 — no profile, does not compete",
    ),
)
RETIRED_FAMILY_NAMES = frozenset(entry.family for entry in RETIRED_FAMILIES)


def profile_for(family: str) -> FamilyProfile | None:
    """The profile for a family, or None: no profile, no claims."""
    return PROFILES_BY_FAMILY.get(family)


def competing_families() -> tuple[str, ...]:
    """Every family that may claim: profiled families, in order."""
    return tuple(
        profile.family for profile in PROFILES if profile.kind != KIND_GENRE_SEAT
    )


def is_retired(family: str) -> bool:
    """Whether a family is retired as registry data."""
    return family in RETIRED_FAMILY_NAMES
