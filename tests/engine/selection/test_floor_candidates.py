from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.selection.selector import CLASSIFICATION_DIMENSIONS
from edgar_sec.engine.selection.source import CandidateSource
from tests.engine.selection.conftest import make_locator, write_snapshot


def test_staged_floor_pool_keeps_only_cap_eligible_candidates(tmp_path: Path) -> None:
    locators = [
        make_locator(index, era="rare", company_family="repeated-family")
        for index in range(8)
    ]
    locators.append(make_locator(8, era="rare", company_family="independent-family"))
    snapshot = write_snapshot(tmp_path / "floor-candidates", locators)
    source = CandidateSource(snapshot, "candidate-seed")

    with source.session():
        con = source._require()
        columns = ", ".join(
            f"{dimension} VARCHAR NOT NULL" for dimension in CLASSIFICATION_DIMENSIONS
        )
        keys = ", ".join(CLASSIFICATION_DIMENSIONS)
        con.execute(
            "CREATE TEMP TABLE selection_signatures "
            f"({columns}, signature_count BIGINT, PRIMARY KEY ({keys}))"
        )
        source.stage_floor_candidates(
            {"era": {"rare": 2}}, CLASSIFICATION_DIMENSIONS, 1, 2
        )
        candidates = list(
            source.pool_for_staged_floor("era", "rare", 2, CLASSIFICATION_DIMENSIONS, 1)
        )

    assert {candidate["company_family"] for candidate in candidates} == {
        "repeated-family",
        "independent-family",
    }


def test_staged_exhibit_floor_deduplicates_and_excludes_selected_accessions(
    tmp_path: Path,
) -> None:
    locators = [
        make_locator(
            0,
            primary_exhibit_like=True,
            representative_accession="selected-accession",
        ),
        make_locator(
            1,
            primary_exhibit_like=True,
            representative_accession="selected-accession",
        ),
        make_locator(
            2,
            primary_exhibit_like=True,
            representative_accession="available-accession",
        ),
        make_locator(
            3,
            primary_exhibit_like=True,
            representative_accession="other-accession",
        ),
    ]
    snapshot = write_snapshot(tmp_path / "exhibit-floor-candidates", locators)
    source = CandidateSource(snapshot, "exhibit-seed")

    with source.session():
        source.register_selected(["loc-0000"])
        source.stage_floor_candidates(
            {"primary_exhibit_like": {"true": 2}},
            CLASSIFICATION_DIMENSIONS,
            None,
            3,
        )
        candidates = list(
            source.pool_for_staged_floor(
                "primary_exhibit_like", "true", 3, CLASSIFICATION_DIMENSIONS, None
            )
        )

    accessions = [candidate["representative_accession"] for candidate in candidates]
    assert set(accessions) == {"available-accession", "other-accession"}
    assert len(accessions) == len(set(accessions))
