"""Family-profile registry: the single home of classifier profiles."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

PROV_FAMILY_SUPPORT = "verdict:family_support"
PROV_DEMOGRAPHICS = "measurement:demographics_profile"
PROV_LABOR = "measurement:labor_capture_profile"
PROV_EX13 = "census:ex13_exhibit_links"

# Strata are the measurement strata: B is the annual stratum,
# D the quarterly stratum. Profiles carry stratum codes, never
# form names (R5: no hardcoded forms).
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
SEAT_GEOMETRY_TEXT = "geometry_text"
SEAT_NOTE_TITLE_CONTENT = "note_title_content"
SEAT_PROSE_CAPTURE = "prose_capture"
SEAT_GENRE_REFUSAL = "genre_refusal"
SEAT_REGION_GATED = "region_gated"

PROV_DECLARED_SPECS = "form-tests:declared_specs"
PROV_DERIVATIVES_EVIDENCE = "form-tests:derivatives_evidence"

# Form-test declarations (R1): names only, as registry data.
# The test classes themselves are implemented outside the
# registry; only their names are data here.
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
    """Measured support for one family: precision/recall per stratum."""

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
    provenance: str = PROV_FAMILY_SUPPORT


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
        note="the residual claimant: recall is done, precision "
        "needs claim admission — the seat identity closing over "
        "the table's own totals is that admission",
    ),
    FamilyProfile(
        "cash_flow",
        KIND_FAMILY,
        _support(0.576, 0.833, 0.218, 1.000),
        SEAT_SIGNATURE,
        form_tests=(TEST_PRIMARY_STATEMENT_SEAT,),
        gate_bindings=_STATEMENT_GATES,
        exhibit_links=_EX13_ANNUAL,
        note="quarterly precision collapse (.218) is the target: "
        "summaries, recasts and sibling statements carry no "
        "three-section sum to the change in cash",
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
        note="directed located recall .06 annual / .02 quarterly: "
        "true ladders go unclaimed, so the ladder is this family's "
        "admission evidence; bucketed payments-due tables are the "
        "commitments form, never this family's ladder",
    ),
    FamilyProfile(
        "deferred_tax",
        KIND_FAMILY,
        _support(0.589, 1.000, 0.519, None, quarterly_directed_recall=0.942),
        SEAT_SIGNATURE,
        form_tests=(TEST_COMPOSITION_TWIN,),
        note="quarterly recall unmeasured on the sealed sweep (n=0); "
        "the directed rate is the recall evidence of record. "
        "Step 3 union disposition: the Step 1 TEST_WALK declaration "
        "is dropped — no walk spec was ever written for this family; "
        "its form is the composition twin, which carries a spec",
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
        note="thinnest directed coverage of the four; the directed "
        "K set (50 verified-member filings) is its specimen base; "
        "any equity-captioned grid was claimed — the column walk "
        "is the admission form",
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
        note="annual precision .000: the seat claimed everything "
        "except the statement; the descent's first leg is the "
        "priced gross_profit_leg1 identity",
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
        shape="statutory-rate anchor row, then adjustment rows, then an "
        "effective-rate row; every row in the block is percentage-valued "
        "per period column and anchor + adjustments close to the "
        "effective rate within 0.3; percentages of pre-tax income",
        note="quarterly recall unmeasured on the sealed sweep (n=0); "
        "the directed rate is the recall evidence of record. "
        "Percentage form is the precision lever (sealed annual precision "
        ".432): the provision-detail twin (dollar current/deferred "
        "expense rows, currency total) was the top annual false class "
        "(4 of 10) and deferred-tax component tables (dollar asset / "
        "liability rows as of balance dates) share the vocabulary; "
        "neither carries a percentage anchor or a closing percentage "
        "total, and incidental percentages without anchor + closure "
        "are not the form. A dollar-form reconciliation is the same "
        "family but is not this test.",
    ),
    FamilyProfile(
        "commitments_contingencies",
        KIND_FAMILY,
        _support(0.583, 0.100, 0.417, 0.000),
        SEAT_GEOMETRY_TEXT,
        form_tests=(TEST_LADDER,),
        gate_bindings=("commitments_seat",),
        note="seat relocated at refresh Step 4: directed located "
        "recall .000 on both strata under the note-title seat; "
        "the geometry-text seat claims payments-due, credit-"
        "cluster and guarantee forms in MD&A / note regions",
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


def profile_for(family: str) -> FamilyProfile | None:
    """The profile for a family, or None: no profile, no claims."""
    return PROFILES_BY_FAMILY.get(family)


def competing_families() -> tuple[str, ...]:
    """Every family that may claim: profiled families, in order."""
    return tuple(
        profile.family for profile in PROFILES if profile.kind != KIND_GENRE_SEAT
    )


def registry_fingerprint(
    profiles: tuple[FamilyProfile, ...] = PROFILES,
) -> str:
    """Sha256 over the canonical serialization of the whole registry."""
    canonical = json.dumps(
        {"profiles": [asdict(profile) for profile in profiles]},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def registry_state(
    *,
    profiles: tuple[FamilyProfile, ...] = PROFILES,
) -> str:
    """The registry-state value a plan's provenance carries."""
    return f"sha256:{registry_fingerprint(profiles)}"
