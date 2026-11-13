"""Reconciliation: successor fixtures against the retained corpus."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from tests.support import fixture_path

_RETAINED = fixture_path("taxonomy_corpus")
_SUCCESSOR = fixture_path("table_extraction_corpus")
_CONTEXT_KEYS = {
    "caption_stack",
    "scale",
    "location",
    "preceding",
    "prose_before",
    "prose_after",
    "structured_location",
    "breaks",
    "issues",
    "label",
}


def _filing_names(directory: Path) -> list[str]:
    return sorted(
        p.name
        for p in directory.glob("*.json")
        if p.stem[0].isdigit() and "-" in p.stem
    )


def _load(directory: Path, name: str) -> dict:
    return json.loads((directory / name).read_text(encoding="utf-8"))


def test_every_retained_filing_present() -> None:
    assert _filing_names(_SUCCESSOR) == _filing_names(_RETAINED)


def test_geometry_counts_alignment_and_labels() -> None:
    total = 0
    labeled = 0
    splits = {"derivation": 0, "heldout": 0}
    for name in _filing_names(_RETAINED):
        retained = _load(_RETAINED, name)
        successor = _load(_SUCCESSOR, name)
        assert successor["status"] == "ok"
        assert successor["population"] == "retained-409"
        r_geos = retained["geometries"]
        s_geos = successor["geometries"]
        total += len(s_geos)
        retained_labels = {lab["table_index"]: lab for lab in retained["labels"]}
        if successor["builder"].get("label_alignment") == "content-match":
            # Drift filing: labels were re-attached by content match;
            # every successor label must be a retained label, verbatim.
            retained_multiset = Counter(
                json.dumps(lab, sort_keys=True) for lab in retained["labels"]
            )
            for geo in s_geos:
                if geo["label"] is None:
                    continue
                key = json.dumps(geo["label"], sort_keys=True)
                assert retained_multiset[key] > 0, name
                retained_multiset[key] -= 1
                labeled += 1
                splits[geo["label"]["split"]] += 1
            continue
        assert [g["table_index"] for g in s_geos] == [g["table_index"] for g in r_geos]
        for geo in s_geos:
            assert geo["label"] == retained_labels[geo["table_index"]]
            labeled += 1
            splits[geo["label"]["split"]] += 1
    # 18,902 retained geometries; three explained retained-only drift
    # fragments and one successor-only fragment give 18,900 successor
    # geometries, 18,899 of them label-carrying.
    assert total == 18900
    assert labeled == 18899
    assert splits == {"derivation": 9565, "heldout": 9334}


def test_context_fields_present_and_failures_marked() -> None:
    for name in _filing_names(_SUCCESSOR):
        successor = _load(_SUCCESSOR, name)
        for geo in successor["geometries"]:
            assert _CONTEXT_KEYS <= set(geo)
            assert geo["breaks"].keys() == {"inside", "before", "after"}
            if geo["location"] is None:
                assert geo["issues"], name
