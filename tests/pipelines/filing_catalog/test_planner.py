"""Unit tests for deterministic target planning."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from edgar_sec.pipelines.filing_catalog.catalog_job import materialize
from edgar_sec.pipelines.filing_catalog.paths import (
    LOCATOR_GROUPS_NAME,
    PLAN_FILE_NAME,
    SELECTION_REPORT_NAME,
    form_partition_dir,
    form_partition_name,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planner import plan
from edgar_sec.pipelines.filing_catalog.publication import (
    PlanConflictError,
    plan_bundle_complete,
)


@pytest.fixture
def catalog_id(tmp_path: Path, sample_source: Path) -> str:
    manifest = materialize(sample_source, tmp_path / "art")
    return str(manifest["catalog_id"])


@pytest.fixture
def artifacts_root(tmp_path: Path) -> Path:
    return tmp_path / "art"


def _plan_dir(artifacts_root: Path, plan_meta: dict[str, Any]) -> Path:
    return resolve_filing_catalog_paths(artifacts_root).plan_dir(plan_meta["plan_id"])


# --- the four supported filters -------------------------------------------


def test_all_forms_plans_every_target(catalog_id: str, artifacts_root: Path) -> None:
    meta = plan(catalog_id, artifacts_root)
    assert meta["selected_rows"] == 13
    assert sum(meta["counts"].values()) == 13


def test_form_filter_selects_one_partition(
    catalog_id: str, artifacts_root: Path
) -> None:
    meta = plan(catalog_id, artifacts_root, forms=("10-K",))
    assert meta["counts"] == {"10-K": 4}
    assert meta["selected_rows"] == 4


def test_amendment_policy_is_actually_enforced(
    catalog_id: str, artifacts_root: Path
) -> None:
    """v1 validated this value but never filtered on it."""
    both = plan(catalog_id, artifacts_root, amendment="both")
    original = plan(catalog_id, artifacts_root, amendment="original")
    amendments = plan(catalog_id, artifacts_root, amendment="amendments")
    assert (
        both["selected_rows"] == original["selected_rows"] + amendments["selected_rows"]
    )
    # Only 10-K/A and 8-K/A end in "/A". 10-KT and 10-KSB do not, which is the
    # whole point of the suffix rule over a membership list.
    assert amendments["counts"] == {"10-K/A": 1, "8-K/A": 1}
    assert amendments["selected_rows"] == 2
    assert original["selected_rows"] == 11
    assert amendments["plan_id"] != original["plan_id"]


def test_document_suffix_filter_narrows_the_plan(
    catalog_id: str, artifacts_root: Path
) -> None:
    htm = plan(catalog_id, artifacts_root, document_suffixes=(".htm",))
    txt = plan(catalog_id, artifacts_root, document_suffixes=(".txt",))
    assert htm["selected_rows"] == 9
    assert txt["selected_rows"] == 4
    assert htm["selected_rows"] + txt["selected_rows"] == 13


def test_limit_applies_per_form(catalog_id: str, artifacts_root: Path) -> None:
    meta = plan(catalog_id, artifacts_root, limit=2)
    assert all(count <= 2 for count in meta["counts"].values())
    assert meta["selected_rows"] == 10  # five forms have 2, two have only 1


def test_planner_refuses_a_negative_limit(
    catalog_id: str, artifacts_root: Path
) -> None:
    with pytest.raises(ValueError, match="limit must be non-negative"):
        plan(catalog_id, artifacts_root, limit=-1)


def test_planner_refuses_an_unknown_amendment_policy(
    catalog_id: str, artifacts_root: Path
) -> None:
    with pytest.raises(ValueError, match="amendment must be one of"):
        plan(catalog_id, artifacts_root, amendment="sometimes")


def test_planner_refuses_an_unsafe_form_filter(
    catalog_id: str, artifacts_root: Path
) -> None:
    with pytest.raises(ValueError, match="unsafe form filter"):
        plan(catalog_id, artifacts_root, forms=("10-K'; DROP TABLE x--",))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start_date": "2020-01-01"},
        {"end_date": "2020-01-01"},
        {"filing_date": "2020-01-01"},
    ],
)
def test_planner_refuses_date_parameters(
    catalog_id: str, artifacts_root: Path, kwargs: dict[str, Any]
) -> None:
    """Date slicing is Stage B only; a date argument must not be accepted."""
    with pytest.raises(TypeError):
        plan(catalog_id, artifacts_root, **kwargs)


def test_planner_refuses_an_unpublished_catalog(
    artifacts_root: Path,
) -> None:
    with pytest.raises(PlanConflictError, match="no published targets"):
        plan("does-not-exist", artifacts_root)


# --- plan identity and reuse ---------------------------------------------


def test_plan_identity_is_content_derived(
    catalog_id: str, artifacts_root: Path
) -> None:
    first = plan(catalog_id, artifacts_root, forms=("10-K",))
    second = plan(catalog_id, artifacts_root, forms=("10-K",))
    assert first["plan_id"] == second["plan_id"]
    assert first["request_fingerprint"] == second["request_fingerprint"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"forms": ("10-K",)},
        {"forms": ("10-Q",)},
        {"forms": ("10-K",), "amendment": "amendments"},
        {"forms": ("10-K",), "limit": 1},
        {"document_suffixes": (".htm",)},
    ],
)
def test_distinct_requests_yield_distinct_plans(
    catalog_id: str, artifacts_root: Path, kwargs: dict[str, Any]
) -> None:
    assert plan(catalog_id, artifacts_root, **kwargs)["plan_id"] not in {
        plan(catalog_id, artifacts_root, **other)["plan_id"]
        for other in (
            {"forms": ("10-K",)},
            {"forms": ("10-Q",)},
            {"forms": ("10-K",), "amendment": "amendments"},
            {"forms": ("10-K",), "limit": 1},
            {"document_suffixes": (".htm",)},
        )
        if other != kwargs
    }


def test_identical_rerun_reuses_the_bundle(
    catalog_id: str, artifacts_root: Path
) -> None:
    first = plan(catalog_id, artifacts_root, forms=("10-K",))
    plan_dir = _plan_dir(artifacts_root, first)
    shard = form_partition_dir(plan_dir, "10-K") / "data.parquet"
    stamp = shard.stat().st_mtime_ns
    second = plan(catalog_id, artifacts_root, forms=("10-K",))
    assert second["plan_id"] == first["plan_id"]
    assert plan_dir.is_dir()
    assert shard.stat().st_mtime_ns == stamp, "reuse must not rewrite the bundle"


# --- bundle structure -----------------------------------------------------


def test_bundle_contains_every_required_file(
    catalog_id: str, artifacts_root: Path
) -> None:
    meta = plan(catalog_id, artifacts_root)
    plan_dir = _plan_dir(artifacts_root, meta)
    assert plan_bundle_complete(plan_dir)
    for name in (PLAN_FILE_NAME, SELECTION_REPORT_NAME, LOCATOR_GROUPS_NAME):
        assert (plan_dir / name).is_file()


def test_amendment_forms_escape_the_partition_separator(
    catalog_id: str, artifacts_root: Path
) -> None:
    meta = plan(catalog_id, artifacts_root, forms=("8-K/A", "10-K/A"))
    targets_dir = resolve_filing_catalog_paths(artifacts_root).plan_targets_dir(
        meta["plan_id"]
    )
    partitions = sorted(p.name for p in targets_dir.glob("form=*"))
    assert partitions == ["form=10-K_A", "form=8-K_A"]
    assert meta["counts"] == {"10-K/A": 1, "8-K/A": 1}


def test_form_partition_name_escapes_only_the_separator() -> None:
    assert form_partition_name("8-K/A") == "8-K_A"
    assert form_partition_name("10-K") == "10-K"
    assert form_partition_name("10-KT") == "10-KT"


def test_target_partitions_are_deterministically_ordered(
    catalog_id: str, artifacts_root: Path
) -> None:
    meta = plan(catalog_id, artifacts_root)
    plan_dir = _plan_dir(artifacts_root, meta)
    shard = pq.read_table(form_partition_dir(plan_dir, "10-K") / "data.parquet")
    keys = [(r["document_locator_key"], r["occurrence_id"]) for r in shard.to_pylist()]
    assert keys == sorted(keys)


def test_zero_row_plan_is_still_a_complete_bundle(
    catalog_id: str, artifacts_root: Path
) -> None:
    """A plan matching nothing must remain publishable and reusable."""
    meta = plan(catalog_id, artifacts_root, forms=("10-K",), amendment="amendments")
    assert meta["selected_rows"] == 0
    plan_dir = _plan_dir(artifacts_root, meta)
    assert plan_bundle_complete(plan_dir)
    assert (plan_dir / LOCATOR_GROUPS_NAME).is_file()
    assert pq.read_table(plan_dir / LOCATOR_GROUPS_NAME).num_rows == 0
    assert (
        plan(catalog_id, artifacts_root, forms=("10-K",), amendment="amendments")[
            "plan_id"
        ]
        == meta["plan_id"]
    )


def test_incomplete_bundle_is_a_conflict_not_a_silent_rewrite(
    catalog_id: str, artifacts_root: Path
) -> None:
    meta = plan(catalog_id, artifacts_root, forms=("10-K",))
    plan_dir = _plan_dir(artifacts_root, meta)
    (plan_dir / SELECTION_REPORT_NAME).unlink()
    with pytest.raises(PlanConflictError, match="incomplete plan bundle"):
        plan(catalog_id, artifacts_root, forms=("10-K",))


# --- locator projection ---------------------------------------------------


def test_locator_groups_hold_one_row_per_locator(
    catalog_id: str, artifacts_root: Path
) -> None:
    """13 occurrences across 12 locators: the shared bundle collapses to one."""
    meta = plan(catalog_id, artifacts_root)
    plan_dir = _plan_dir(artifacts_root, meta)
    locators = pq.read_table(plan_dir / LOCATOR_GROUPS_NAME)
    assert locators.num_rows == 12
    assert meta["unique_locators_count"] == 12
    keys = locators.column("document_locator_key").to_pylist()
    assert len(keys) == len(set(keys))
    assert keys == sorted(keys)


def test_locator_projection_is_the_narrow_stage_a_shape(
    catalog_id: str, artifacts_root: Path
) -> None:
    meta = plan(catalog_id, artifacts_root)
    plan_dir = _plan_dir(artifacts_root, meta)
    names = pq.read_table(plan_dir / LOCATOR_GROUPS_NAME).schema.names
    assert names == [
        "document_locator_key",
        "form",
        "representative_cik",
        "representative_accession",
        "primary_document",
        "document_path",
        "archive_url",
        "document_path_source",
    ]


def test_locator_representatives_are_deterministic(
    catalog_id: str, artifacts_root: Path, sample_source: Path
) -> None:
    """A re-plan from an independent catalog copy picks the same representative."""
    first = plan(catalog_id, artifacts_root, document_suffixes=(".txt",))
    rows_first = pq.read_table(
        _plan_dir(artifacts_root, first) / LOCATOR_GROUPS_NAME
    ).to_pylist()

    other_root = artifacts_root.parent / "art2"
    materialize(sample_source, other_root)
    second = plan(catalog_id, other_root, document_suffixes=(".txt",))
    rows_second = pq.read_table(
        _plan_dir(other_root, second) / LOCATOR_GROUPS_NAME
    ).to_pylist()
    assert rows_first == rows_second
