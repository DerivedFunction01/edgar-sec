"""Note-title families: governed provenance, floor-tier pricing."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.note_titles import (
    NOTE_TITLE_SPECS,
    NOTE_TITLES_BY_FAMILY,
)
from edgar_sec.engine.tables.extraction.registry import (
    ASSIGNMENT_FLOOR,
    FAMILY_PRIORITY,
)


def test_specs_carry_dual_step8c_provenance() -> None:
    assert NOTE_TITLE_SPECS
    assert all(spec.provenance == "step8c:note_census" for spec in NOTE_TITLE_SPECS)
    assert all(spec.discovery == "step8c:context_drive" for spec in NOTE_TITLE_SPECS)


def test_claims_are_floor_tier_and_measured_exclusive() -> None:
    for spec in NOTE_TITLE_SPECS:
        assert spec.points == ASSIGNMENT_FLOOR
        assert spec.exclusivity >= 0.90
        assert spec.support >= 25


def test_families_rank_below_the_named_families() -> None:
    positions = {family: i for i, family in enumerate(FAMILY_PRIORITY)}
    for spec in NOTE_TITLE_SPECS:
        assert positions[spec.family] > positions["equity_statement"]
        assert positions[spec.family] < positions["other"]
    assert set(NOTE_TITLES_BY_FAMILY) == {spec.family for spec in NOTE_TITLE_SPECS}
