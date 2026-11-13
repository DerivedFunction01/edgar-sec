"""Registry contents trace to the Step 3 calibration record."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.calibration import (
    LOCATION_STRENGTHS,
    PATTERNS,
    PROSE_PATTERNS,
)
from edgar_sec.engine.tables.extraction.negative_evidence import NEGATIVE_EVIDENCE
from edgar_sec.engine.tables.extraction.registry import (
    ASSIGNMENT_FLOOR,
    CALIBRATION_RECORD,
    CONTAINMENT_EDGES,
    CO_NOTE_SIBLINGS,
    FLAVORS,
    IDENTITIES,
    LANDMARK_SPECS,
    SEQUENCES,
    SHAPE_BOUNDS_BY_FAMILY,
    STRUCTURE_SPECS,
)


def test_every_spec_carries_governed_provenance() -> None:
    assert CALIBRATION_RECORD.endswith(
        "2026-11-09-table-extraction-step3-calibration.md"
    )
    specs = (
        *PATTERNS,
        *SEQUENCES,
        *PROSE_PATTERNS,
        *NEGATIVE_EVIDENCE,
        *IDENTITIES,
        *LANDMARK_SPECS,
    )
    assert specs
    governed = ("step3:", "coverage-redrive:", "repair:")
    assert all(spec.provenance.startswith(governed) for spec in specs)


def test_no_identity_alone_reaches_the_assignment_floor() -> None:
    assert IDENTITIES
    assert all(0.0 < spec.points < ASSIGNMENT_FLOOR for spec in IDENTITIES)
    assert all(
        spec.points_provenance == "step6:identity_pricing" for spec in IDENTITIES
    )


def test_only_the_measured_containment_edge_carries_standing() -> None:
    assert [(e.subset, e.parent) for e in CONTAINMENT_EDGES] == [
        ("aoci", "equity_statement")
    ]
    assert [s.families for s in CO_NOTE_SIBLINGS] == [
        ("deferred_tax", "tax_reconciliation")
    ]


def test_value_column_caps_are_the_step3_p95_values() -> None:
    caps = {
        family: SHAPE_BOUNDS_BY_FAMILY[family].columns_p95
        for family in (
            "income_statement",
            "balance_sheet",
            "cash_flow",
            "equity_statement",
        )
    }
    assert caps == {
        "income_statement": 6,
        "balance_sheet": 5,
        "cash_flow": 4,
        "equity_statement": 7,
    }


def test_balance_sheet_spine_sequence_is_registered() -> None:
    triples = {spec.terms for spec in SEQUENCES if spec.family == "balance_sheet"}
    assert ("assets", "total assets", "total liabilities") in triples


def test_thin_families_have_no_term_patterns_at_the_bar() -> None:
    families = {spec.family for spec in PATTERNS}
    assert "balance_sheet" in families
    assert "deferred_tax" not in families
    assert "fair_value" not in families


def test_negative_evidence_is_the_retained_veto_set() -> None:
    assert len(NEGATIVE_EVIDENCE) == 246
    step3 = [s for s in NEGATIVE_EVIDENCE if s.provenance.startswith("step3:")]
    repair = [s for s in NEGATIVE_EVIDENCE if s.provenance.startswith("repair:")]
    assert len(step3) == 178 and len(repair) == 68
    assert all(spec.member_presence_rate <= 0.01 for spec in step3)
    assert all(spec.member_presence_rate <= 0.02 for spec in repair)


def test_cash_flow_direct_earns_no_flavor_level() -> None:
    by_key = {(spec.family, spec.flavor): spec for spec in FLAVORS}
    assert by_key[("cash_flow", "direct")].recurs is False
    assert by_key[("cash_flow", "indirect")].recurs is True
    assert by_key[("balance_sheet", "classified")].recurs is True
    assert by_key[("balance_sheet", "unclassified")].recurs is True
    assert by_key[("income_statement", "multi_step")].recurs is True
    assert by_key[("income_statement", "single_step")].recurs is True


def test_prose_patterns_are_window_tagged_and_exclusive() -> None:
    assert {spec.window for spec in PROSE_PATTERNS} <= {"before", "after"}
    assert all(spec.exclusivity >= 0.8 for spec in PROSE_PATTERNS)
    income_before = [
        spec
        for spec in PROSE_PATTERNS
        if spec.family == "income_statement" and spec.window == "before"
    ]
    assert len(income_before) == 3


def test_location_strengths_carry_measured_counts() -> None:
    balance_sheet = next(
        spec for spec in LOCATION_STRENGTHS if spec.family == "balance_sheet"
    )
    assert ("ITEM 1", 34) in balance_sheet.items
    assert balance_sheet.note_rate == 0.222


def test_structure_specs_carry_step8d_dual_provenance() -> None:
    assert STRUCTURE_SPECS
    assert all(
        spec.provenance == "step8d:structure_census"
        and spec.discovery == "step8d:structure_drive"
        for spec in STRUCTURE_SPECS
    )
    assert all(0.0 < spec.points < ASSIGNMENT_FLOOR for spec in STRUCTURE_SPECS)
