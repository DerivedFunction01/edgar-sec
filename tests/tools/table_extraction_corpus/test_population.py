"""Step 9 population accession: fixture inventory, shape, label totals."""

from __future__ import annotations

import json
from pathlib import Path

POPULATION = (
    Path(__file__).resolve().parents[2] / "fixtures" / "table_extraction_population"
)
LABEL_KEYS = {
    "table_index",
    "final_family",
    "aligned_family",
    "provenance",
    "audited",
    "split",
}
PROVENANCES = {"aligned", "aligned_negative", "signature", "adjudicated", None}
SPLITS = {"derivation", "heldout"}
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
ERAS = {"pre2010", "y2010s", "ixbrl"}

_CACHE: list[dict] | None = None


def _fixtures() -> list[dict]:
    """Load every population fixture once per test session."""
    global _CACHE
    if _CACHE is None:
        _CACHE = [
            json.loads(path.read_text())
            for path in sorted(POPULATION.glob("*.json"))
            if "summary" not in path.name
        ]
    return _CACHE


def _summary(name: str) -> dict:
    """Read one accession summary file from the population dir."""
    return json.loads((POPULATION / name).read_text())


def test_population_inventory() -> None:
    """3,000 fixtures plus the two accession summaries, all built ok."""
    names = {path.name for path in POPULATION.glob("*.json")}
    assert len(names) == 3002
    assert "build-summary.json" in names
    assert "finalize-summary.json" in names
    build = _summary("build-summary.json")
    assert build["filings"] == 3000
    assert build["statuses"] == {"ok": 3000}
    assert len(_fixtures()) == 3000


def test_fixture_shape_and_labels() -> None:
    """Every fixture is a Step 9 filing with well-formed geometry labels."""
    for fixture in _fixtures():
        assert fixture["population"] == "step9-3000"
        assert fixture["status"] == "ok"
        assert fixture["form"] in FORMS
        assert fixture["era"] in ERAS
        path = POPULATION / f"{fixture['accession']}.json"
        assert path.exists()
        for geometry in fixture["geometries"]:
            label = geometry["label"]
            assert set(label) == LABEL_KEYS
            assert label["table_index"] == geometry["table_index"]
            assert label["split"] in SPLITS
            assert label["provenance"] in PROVENANCES
            if label["audited"]:
                assert label["provenance"] == "adjudicated"
            if label["final_family"] is not None:
                assert isinstance(label["final_family"], str)
                assert label["final_family"]


def test_adjudication_totals_match_finalize_summary() -> None:
    """Adjudicated labels in the fixtures equal the finalize record."""
    finalize = _summary("finalize-summary.json")
    applied: dict[str, int] = {}
    ambiguous = 0
    for fixture in _fixtures():
        for geometry in fixture["geometries"]:
            label = geometry["label"]
            if label["provenance"] != "adjudicated":
                continue
            assert label["audited"]
            if label["final_family"] is None:
                ambiguous += 1
            else:
                family = label["final_family"]
                applied[family] = applied.get(family, 0) + 1
    assert sum(applied.values()) == finalize["verdicts_applied"]
    assert applied == finalize["applied_by_family"]
    assert ambiguous == finalize["ambiguous_left_unlabelled"]
