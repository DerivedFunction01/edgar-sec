"""Date selection and the era bands derived from the catalog."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.engine.selection.policy import EraBand, SelectionPolicy
from edgar_sec.pipelines.filing_catalog.paths import (
    SELECTION_REPORT_FILE,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planning.policy import plan_policy
from tests.pipelines.filing_catalog.planning.policy_support import _policy


def _selection_report(
    artifacts_root: Path, meta: dict[str, object]
) -> dict[str, object]:
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(
        str(meta["plan_id"])
    )
    return json.loads((plan_dir / SELECTION_REPORT_FILE).read_text("utf-8"))


def _derived_bands_policy(**overrides: object) -> SelectionPolicy:
    return _policy(era_bands=[], **overrides)


def test_a_policy_declaring_no_bands_gets_bands_from_the_catalog(
    catalog_snapshot: tuple[dict[str, object], Path], catalog_artifacts_root: Path
) -> None:
    """The fixture's 10-K and 10-Q report in 2023 and 2024, so those years tile."""
    manifest, _ = catalog_snapshot
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _derived_bands_policy(forms=["10-K", "10-Q"]),
        catalog_artifacts_root,
    )
    bands = SelectionPolicy.from_dict(meta["selection_policy"]).era_bands
    assert bands, "automatic mode must resolve bands"
    assert bands[0].start_year == 2023
    assert bands[-1].end_year == 2025
    # The plan records the bands used, so a later rebuild cannot disagree.
    assert (
        SelectionPolicy.from_dict(meta["selection_policy"]).derives_era_bands is False
    )
    assert (
        meta["policy_fingerprint"]
        == SelectionPolicy.from_dict(meta["selection_policy"]).policy_fingerprint
    )


def test_derived_bands_follow_the_reachable_years(
    catalog_snapshot: tuple[dict[str, object], Path], catalog_artifacts_root: Path
) -> None:
    """Only a 10-Q carries the fixture's 2024 date, so that form is declared."""
    manifest, _ = catalog_snapshot
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _derived_bands_policy(
            forms=["10-Q"],
            date_selection=[
                {
                    "kind": "absolute",
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                }
            ],
        ),
        catalog_artifacts_root,
    )
    bands = SelectionPolicy.from_dict(meta["selection_policy"]).era_bands
    assert [band.start_year for band in bands] == [2024]


def test_a_declared_band_list_is_left_alone(
    catalog_snapshot: tuple[dict[str, object], Path], catalog_artifacts_root: Path
) -> None:
    manifest, _ = catalog_snapshot
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _policy(era_bands=[EraBand(name="declared", start_year=1990, end_year=1991)]),
        catalog_artifacts_root,
    )
    bands = SelectionPolicy.from_dict(meta["selection_policy"]).era_bands
    assert [band.name for band in bands] == ["declared"]


def test_a_date_selection_narrows_what_the_plan_selects(
    catalog_snapshot: tuple[dict[str, object], Path], catalog_artifacts_root: Path
) -> None:
    """The fixture reports 2023, so a 2024 window publishes empty, not stale rows."""
    manifest, _ = catalog_snapshot
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _policy(
            date_selection=[
                {
                    "kind": "absolute",
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                }
            ]
        ),
        catalog_artifacts_root,
    )
    report = _selection_report(catalog_artifacts_root, meta)
    assert report["date_selection_text"] == "2024-01-01..2024-12-31"
    assert report["form_era_allocation"]["cell_count"] == 0
    assert meta["selected_rows"] == 0


def test_the_report_states_the_selection_and_the_allocation(
    catalog_snapshot: tuple[dict[str, object], Path], catalog_artifacts_root: Path
) -> None:
    manifest, _ = catalog_snapshot
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), catalog_artifacts_root)
    report = _selection_report(catalog_artifacts_root, meta)
    assert report["date_selection"] == []
    assert report["date_selection_text"] == ""
    assert report["era_band_count"] == len(meta["selection_policy"]["era_bands"])
    assert report["derives_era_bands"] is False
    allocation = report["form_era_allocation"]
    assert {
        "cells",
        "cell_count",
        "final_target_min",
        "final_target_max",
        "unallocated",
    } <= set(allocation)


def test_a_policy_document_without_the_new_field_is_still_readable(
    catalog_snapshot: tuple[dict[str, object], Path], catalog_artifacts_root: Path
) -> None:
    """A draft written before the field existed is a policy, not an error."""
    manifest, _ = catalog_snapshot
    unfiltered = _policy().to_dict()
    unfiltered.pop("date_selection")
    meta = plan_policy(
        str(manifest["catalog_id"]),
        SelectionPolicy.from_dict(unfiltered),
        catalog_artifacts_root,
    )
    assert meta["selection_policy"]["date_selection"] == []


def test_a_selection_that_reaches_nothing_falls_back_to_the_catalogs_years(
    catalog_snapshot: tuple[dict[str, object], Path], catalog_artifacts_root: Path
) -> None:
    """The fallback is the catalog's own years, never a synthetic band."""
    manifest, _ = catalog_snapshot
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _derived_bands_policy(
            date_selection=[
                {
                    "kind": "absolute",
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                }
            ]
        ),
        catalog_artifacts_root,
    )
    bands = SelectionPolicy.from_dict(meta["selection_policy"]).era_bands
    assert [band.start_year for band in bands] == [2023, 2024]
    assert meta["selected_rows"] == 0
