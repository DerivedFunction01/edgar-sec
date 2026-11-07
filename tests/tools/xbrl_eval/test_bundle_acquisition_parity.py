"""Bundle acquisition parity: index-based vs index-free loaded results."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from tests.support import load_fixture

_COMPONENTS = (
    "facts",
    "declarations",
    "calculation",
    "presentation",
    "definition",
    "labels",
    "namespaces",
)


def _fixture() -> dict[str, Any]:
    """The recorded parity fixture: per-accession digests from both paths."""
    return load_fixture("xbrl/bundle_acquisition_parity.json")


def _divergences(row: dict[str, Any], stage: str) -> list[str]:
    """Component names whose recorded digests differ between the paths."""
    left, right = row["results"]["index"][stage], row["results"]["free"][stage]
    out = []
    for name in _COMPONENTS:
        if left[f"{name}_sha"] != right[f"{name}_sha"] or (
            name != "namespaces" and left[f"{name}_count"] != right[f"{name}_count"]
        ):
            out.append(name)
    if left["instance_document"] != right["instance_document"]:
        out.append("instance_document")
    return out


def test_parity_fixture_covers_the_stratified_sample() -> None:
    """The fixture records the full sample with its strata intact."""
    fixture = _fixture()
    rows = fixture["accessions"]
    assert len(rows) == fixture["sample_size"] == 80
    assert {row["accession"] for row in rows} == set(fixture["sample_accessions"])
    classes = {row["cls"] for row in rows}
    assert classes == {"covered", "gated", "uncovered"}
    bands = {row["band"] for row in rows}
    assert bands == {"<=2014", "2015-2018", "2019-2022", "2023-2026"}
    for row in rows:
        assert row["status"] == "done"
        assert set(row["results"]) == {"index", "free"}


def test_loaded_results_are_identical_or_adjudicated() -> None:
    """Every divergence at either parse stage is adjudicated in the fixture."""
    fixture = _fixture()
    adjudicated = fixture["adjudications"]
    for row in fixture["accessions"]:
        for stage in ("gated", "ungated"):
            found = _divergences(row, stage)
            if not found:
                continue
            entry = adjudicated.get(row["accession"])
            assert entry is not None, f"{row['accession']} {stage}: {found}"
            assert set(found) <= set(entry["components"]), (
                f"{row['accession']} {stage}: {found} beyond adjudication"
            )
            assert entry["mechanism"]


def test_no_instance_scores_are_symmetric_or_adjudicated() -> None:
    """A path with no instance while the other loads one is a divergence."""
    fixture = _fixture()
    adjudicated = fixture["adjudications"]
    for row in fixture["accessions"]:
        index_has = row["results"]["index"]["has_instance"]
        free_has = row["results"]["free"]["has_instance"]
        if index_has != free_has:
            assert row["accession"] in adjudicated, row["accession"]


def test_divergence_detection_is_not_vacuous() -> None:
    """A mutated digest is detected as a divergence."""
    fixture = _fixture()
    row = deepcopy(fixture["accessions"][0])
    row["results"]["free"]["ungated"]["facts_sha"] = "0" * 64
    assert "facts" in _divergences(row, "ungated")
