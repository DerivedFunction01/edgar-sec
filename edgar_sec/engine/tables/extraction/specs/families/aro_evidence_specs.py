"""ARO evidence spec registry: the kind's parameter table.

The priced ASC 410-20 seat vocabulary, keyed by family; the
evaluator lives in aro_evidence, the cross-kind form-test
entries in form_test_specs."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.subjects.profiles import PROV_ARO_BASE


@dataclass(frozen=True, slots=True)
class AroEvidenceSpec:
    """ARO evidence-gate parameters, declared as data.
    The priced ASC 410-20 seat vocabulary: subject, bookend
    anchors and markers, movement types, subject exclusions."""

    family: str
    test_id: str
    subject_phrase: str
    bookend_markers: tuple[str, ...]
    anchor_terms: tuple[str, ...]
    carrying_phrase: str
    bare_begin_markers: tuple[str, ...]
    bare_end_markers: tuple[str, ...]
    bare_period_term: str
    bare_excluded_terms: tuple[str, ...]
    movement_types: tuple[tuple[str, tuple[str, ...]], ...]
    standardized_terms: tuple[str, ...]
    well_cost_terms: tuple[str, ...]
    provenance: str = PROV_ARO_BASE


# ARO evidence-gate specs, keyed by family: the one literal home
# of the kind's parameters, priced on the 129-specimen
# adjudication base (joined core P .968 / R 1.000, corpus).
ARO_EVIDENCE_SPECS: dict[str, AroEvidenceSpec] = {
    "aro_rollforward": AroEvidenceSpec(
        family="aro_rollforward",
        test_id="aro_rollforward_evidence_gate",
        subject_phrase="asset retirement",
        bookend_markers=("beginning", "ending", "end of", "opening", "closing"),
        anchor_terms=(
            "balance",
            "accrual",
            "accrued",
            "liability",
            "liabilities",
            "reserve",
            "obligation",
            "obligations",
        ),
        carrying_phrase="carrying amount",
        bare_begin_markers=("beginning", "opening"),
        bare_end_markers=("ending", "end of", "closing"),
        bare_period_term="period",
        bare_excluded_terms=("balance", "carrying"),
        movement_types=(
            ("accretion", ("accretion",)),
            (
                "incurred",
                (
                    "liabilities incurred",
                    "incurred",
                    "additions",
                    "new liabilities",
                    "costs incurred",
                ),
            ),
            (
                "settlement",
                (
                    "settlements",
                    "settled",
                    "payments",
                    "paid",
                    "cash paid",
                    "expenditures",
                    "spending",
                ),
            ),
            (
                "revision",
                (
                    "revisions",
                    "changes in estimates",
                    "change in estimate",
                    "adjustments",
                ),
            ),
            ("fx", ("foreign currency", "translation", "currency")),
        ),
        standardized_terms=("standardized measure",),
        well_cost_terms=("exploratory", "well cost"),
    ),
}

# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy.
ARO_EVIDENCE_SPECS_BY_TEST_ID: dict[str, AroEvidenceSpec] = {
    spec.test_id: spec for spec in ARO_EVIDENCE_SPECS.values()
}


@dataclass(frozen=True, slots=True)
class AroAssignmentSpec:
    """ARO joint-assignment parameters, declared as data.
    The family, the co-claim target that stands, and the
    refusal detail the pass stamps on the removed claim."""

    family: str
    target_family: str
    detail: str


# ARO joint assignment: the priced L_JOINT leg — a geometry
# carrying both the ARO claim and a warranty claim is
# assigned to warranty; the bare co-claim touches no true.
ARO_ASSIGNMENT_SPEC = AroAssignmentSpec(
    family="aro_rollforward",
    target_family="warranty",
    detail="aro assignment: warranty co-claim stands",
)
