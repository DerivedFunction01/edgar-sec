"""Deterministic target planning: filters, date selection, and bundle identity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.pipelines.cohort.ingestion import ingest_file_to_cohort
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.pipelines.filing_catalog.catalog_job import materialize
from edgar_sec.pipelines.filing_catalog.paths import (
    LOCATOR_GROUPS_FILE,
    PLAN_TARGETS_DIR,
    SELECTION_REPORT_FILE,
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


def _cohort(artifacts_root: Path, tmp_path: Path, name: str, rows: list[str]) -> Any:
    paths = resolve_cohort_paths(artifacts_root)
    roster = tmp_path / f"{name}.csv"
    roster.write_text(
        "cik,name\n" + "".join(f"{cik},entity\n" for cik in rows),
        encoding="utf-8",
    )
    return ingest_file_to_cohort(
        roster,
        catalog=CohortCatalog(paths),
        paths=paths,
        name=name,
    ).cohort


# --- the four supported filters -------------------------------------------


def test_all_forms_plans_every_target(catalog_id: str, artifacts_root: Path) -> None:
    meta = plan(catalog_id, artifacts_root)
    assert meta["selected_rows"] == 13
    assert sum(meta["counts"].values()) == 13


def test_cohort_filters_targets_and_participates_in_identity(
    catalog_id: str, artifacts_root: Path, tmp_path: Path
) -> None:
    cohort = _cohort(artifacts_root, tmp_path, "one-filer", ["320193"])
    meta = plan(catalog_id, artifacts_root, cohort=cohort.cohort_id)

    assert meta["selected_rows"] == 4
    assert meta["cohort_id"] == cohort.cohort_id
    assert meta["cohort_dataset_sha256"] == cohort.dataset_sha256
    another = _cohort(artifacts_root, tmp_path, "another-filer", ["9999999999"])
    another_plan = plan(catalog_id, artifacts_root, cohort=another.cohort_id)
    assert meta["plan_id"] != another_plan["plan_id"]
    assert meta["plan_id"] != plan(catalog_id, artifacts_root)["plan_id"]


def test_active_source_alias_resolves_for_cohort_filter(
    catalog_id: str, artifacts_root: Path, tmp_path: Path
) -> None:
    cohort = _cohort(artifacts_root, tmp_path, "active-universe", ["320193"])
    catalog = CohortCatalog(resolve_cohort_paths(artifacts_root))
    with catalog._connection() as connection:
        connection.execute(
            "UPDATE cohorts SET origin_kind = ?, origin_json = ?, pinned = 1 WHERE cohort_id = ?",
            (
                "official_source",
                json.dumps(
                    {
                        "source_name": "cik_lookup",
                        "source_snapshot_id": "a" * 64,
                    }
                ),
                cohort.cohort_id,
            ),
        )
    catalog.set_active_source_pointer("cik_lookup", cohort.cohort_id)

    meta = plan(catalog_id, artifacts_root, cohort="universe")

    assert meta["cohort_id"] == cohort.cohort_id
    assert meta["selected_rows"] == 4


def test_an_empty_cohort_publishes_zero_targets(
    catalog_id: str, artifacts_root: Path, tmp_path: Path
) -> None:
    cohort = _cohort(artifacts_root, tmp_path, "empty", [])
    meta = plan(catalog_id, artifacts_root, cohort=cohort.cohort_id)

    assert meta["selected_rows"] == 0
    assert meta["counts"] == {}
    assert plan_bundle_complete(_plan_dir(artifacts_root, meta))


def test_a_modified_cohort_dataset_fails_closed(
    catalog_id: str, artifacts_root: Path, tmp_path: Path
) -> None:
    cohort = _cohort(artifacts_root, tmp_path, "tampered", ["320193"])
    dataset = resolve_cohort_paths(artifacts_root).resolve_relative_path(
        cohort.dataset_path
    )
    dataset.write_bytes(b"not parquet")

    with pytest.raises(ValueError, match="digest mismatch"):
        plan(catalog_id, artifacts_root, cohort=cohort.cohort_id)


# Six fixture targets have a readable report_date and seven an empty one.


def test_an_empty_date_selection_plans_every_target(
    catalog_id: str, artifacts_root: Path
) -> None:
    for spelling in ("", "   ", None):
        meta = plan(catalog_id, artifacts_root, dates=spelling)
        assert meta["selected_rows"] == 13, spelling
        assert meta["date_selection"] == []
        assert meta["date_selection_text"] == ""


def test_a_year_atom_selects_only_that_report_year(
    catalog_id: str, artifacts_root: Path
) -> None:
    assert plan(catalog_id, artifacts_root, dates="2023")["selected_rows"] == 5
    assert plan(catalog_id, artifacts_root, dates="2024")["selected_rows"] == 1
    assert plan(catalog_id, artifacts_root, dates="2025")["selected_rows"] == 0


def test_quarter_and_month_atoms_select_calendar_periods(
    catalog_id: str, artifacts_root: Path
) -> None:
    """Calendar quarters of ``report_date``: the dated rows are Q2, Q3, Q4 twice, Q1."""
    assert plan(catalog_id, artifacts_root, dates="@Q1")["selected_rows"] == 1
    assert plan(catalog_id, artifacts_root, dates="@Q2")["selected_rows"] == 1
    assert plan(catalog_id, artifacts_root, dates="@Q3")["selected_rows"] == 1
    assert plan(catalog_id, artifacts_root, dates="@Q4")["selected_rows"] == 3
    assert plan(catalog_id, artifacts_root, dates="@Q1,@Q3")["selected_rows"] == 2
    assert plan(catalog_id, artifacts_root, dates="@Q2,@Q4")["selected_rows"] == 4
    assert plan(catalog_id, artifacts_root, dates="@M06")["selected_rows"] == 1
    assert plan(catalog_id, artifacts_root, dates="@M09")["selected_rows"] == 1
    assert plan(catalog_id, artifacts_root, dates="@M09,@M12")["selected_rows"] == 4
    assert plan(catalog_id, artifacts_root, dates="2024-03")["selected_rows"] == 1
    assert plan(catalog_id, artifacts_root, dates="2024-03-31")["selected_rows"] == 1


def test_recurrence_and_absolute_windows_are_unioned(
    catalog_id: str, artifacts_root: Path
) -> None:
    """Q4 2023 (three), Q1 2024 (one), June of any year (one)."""
    meta = plan(
        catalog_id,
        artifacts_root,
        dates="2023Q4,2024Q1,@M06",
    )
    assert meta["selected_rows"] == 5
    assert meta["counts"] == {"10-K": 3, "10-Q": 2}


def test_a_nonempty_selection_excludes_targets_with_no_readable_date(
    catalog_id: str, artifacts_root: Path
) -> None:
    """The empty selection keeps undated rows; a nonempty one cannot place them."""
    unfiltered = plan(catalog_id, artifacts_root)
    filtered = plan(catalog_id, artifacts_root, dates="2000..2030")
    assert unfiltered["selected_rows"] - filtered["selected_rows"] == 7
    assert filtered["selected_rows"] == 6


def test_a_form_excluded_only_by_date_publishes_no_partition(
    catalog_id: str, artifacts_root: Path
) -> None:
    """All three 8-K rows are undated, and an empty partition would read as a fact."""
    unfiltered = plan(catalog_id, artifacts_root, forms=("8-K",))
    assert unfiltered["counts"] == {"8-K": 3}

    filtered = plan(catalog_id, artifacts_root, forms=("8-K",), dates="2023")
    assert filtered["counts"] == {}
    assert filtered["selected_rows"] == 0
    assert plan_bundle_complete(_plan_dir(artifacts_root, filtered))


def test_the_date_selection_and_the_form_filter_conjoin(
    catalog_id: str, artifacts_root: Path
) -> None:
    """``10-K`` is present in both years; ``10-K/A`` carries no date."""
    meta = plan(catalog_id, artifacts_root, forms=("10-K",), dates="2023")
    assert meta["counts"] == {"10-K": 4}
    assert (
        plan(catalog_id, artifacts_root, forms=("10-K",), dates="2024")["counts"] == {}
    )


def test_a_published_partition_keeps_the_declared_target_schema(
    catalog_id: str, artifacts_root: Path
) -> None:
    """The parsed-date column must not reach the published shard."""
    from edgar_sec.domain.filing_catalog.schemas import TARGET_COLUMNS
    from edgar_sec.engine.selection.predicates import PARSED_DATE_ALIAS

    meta = plan(catalog_id, artifacts_root, dates="2023")
    directory = _plan_dir(artifacts_root, meta)
    written = sorted(directory.glob("targets/form=*/data.parquet"))
    assert written, "a filtered plan published no target partitions"
    for path in written:
        columns = pq.read_schema(path).names
        assert columns == list(TARGET_COLUMNS)
        assert PARSED_DATE_ALIAS not in columns


def test_limit_stays_a_per_form_limit_under_a_date_selection(
    catalog_id: str, artifacts_root: Path
) -> None:
    """``10-K`` and ``10-Q`` both report in 2023, so the cap applies to each."""
    meta = plan(catalog_id, artifacts_root, dates="2023", limit=1)
    assert meta["counts"] == {"10-K": 1, "10-Q": 1}
    assert meta["selected_rows"] == 2


def test_the_normalized_selection_is_recorded_in_the_plan(
    catalog_id: str, artifacts_root: Path
) -> None:
    """A report states the selection rather than leaving it to be re-derived."""
    meta = plan(catalog_id, artifacts_root, dates="@Q1[2011..2015], 2024 ")
    assert meta["date_selection"] == [
        {"kind": "absolute", "start_date": "2024-01-01", "end_date": "2024-12-31"},
        {
            "kind": "recurring",
            "granularity": "quarter",
            "values": [1],
            "start_year": 2011,
            "end_year": 2015,
        },
    ]
    assert meta["date_selection_text"] == "2024-01-01..2024-12-31,@Q1[2011..2015]"

    report_path = _plan_dir(artifacts_root, meta) / SELECTION_REPORT_FILE
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["date_selection"] == meta["date_selection"]
    assert report["date_selection_text"] == meta["date_selection_text"]


def test_equivalent_spellings_resolve_to_one_published_plan(
    catalog_id: str, artifacts_root: Path
) -> None:
    """A reworded equivalent selection must not fork a second bundle."""
    spellings = ("2023", "2023-01-01..2023-12-31", " 2023 ", "2023..2023")
    ids = {
        plan(catalog_id, artifacts_root, dates=text)["plan_id"] for text in spellings
    }
    assert len(ids) == 1
    assert plan(catalog_id, artifacts_root, dates="2023,2024")["plan_id"] not in ids


def test_the_date_selection_participates_in_plan_identity(
    catalog_id: str, artifacts_root: Path
) -> None:
    without = plan(catalog_id, artifacts_root)
    with_dates = plan(catalog_id, artifacts_root, dates="2023")
    assert without["plan_id"] != with_dates["plan_id"]


def test_an_invalid_date_selection_is_refused_before_anything_is_published(
    catalog_id: str, artifacts_root: Path
) -> None:
    with pytest.raises(ValueError, match="2024Q5"):
        plan(catalog_id, artifacts_root, dates="2024Q5")
    plans = resolve_filing_catalog_paths(artifacts_root).plans_root
    published = sorted(plans.glob("*")) if plans.is_dir() else []
    assert published == []


def test_form_filter_selects_one_partition(
    catalog_id: str, artifacts_root: Path
) -> None:
    meta = plan(catalog_id, artifacts_root, forms=("10-K",))
    assert meta["counts"] == {"10-K": 4}
    assert meta["selected_rows"] == 4


def test_form_filter_is_an_exact_allowlist(
    catalog_id: str, artifacts_root: Path
) -> None:
    """``10-K`` must not reach ``10-K/A``; an operator wanting both names both."""
    base = plan(catalog_id, artifacts_root, forms=("10-K",))
    assert base["counts"] == {"10-K": 4}
    assert "10-K/A" not in base["counts"]

    both = plan(catalog_id, artifacts_root, forms=("10-K", "10-K/A"))
    assert both["counts"] == {"10-K": 4, "10-K/A": 1}
    assert both["selected_rows"] == 5


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
    """A single bound names no selection, so it is a TypeError, not a no-op."""
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
        {"forms": ("10-K", "10-K/A")},
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
            {"forms": ("10-K", "10-K/A")},
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
    shard = (
        plan_dir
        / PLAN_TARGETS_DIR
        / f"form={form_partition_name('10-K')}"
        / "data.parquet"
    )
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
    for name in (PLAN_FILE_NAME, SELECTION_REPORT_FILE, LOCATOR_GROUPS_FILE):
        assert (plan_dir / name).is_file()


def test_amendment_forms_escape_the_partition_separator(
    catalog_id: str, artifacts_root: Path
) -> None:
    meta = plan(catalog_id, artifacts_root, forms=("8-K/A", "10-K/A"))
    targets_dir = (
        resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
        / PLAN_TARGETS_DIR
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
    shard = pq.read_table(
        plan_dir
        / PLAN_TARGETS_DIR
        / f"form={form_partition_name('10-K')}"
        / "data.parquet"
    )
    keys = [(r["document_locator_key"], r["occurrence_id"]) for r in shard.to_pylist()]
    assert keys == sorted(keys)


def test_zero_row_plan_is_still_a_complete_bundle(
    catalog_id: str, artifacts_root: Path
) -> None:
    """A plan matching nothing must remain publishable and reusable."""
    meta = plan(catalog_id, artifacts_root, forms=("NO-SUCH-FORM",))
    assert meta["selected_rows"] == 0
    plan_dir = _plan_dir(artifacts_root, meta)
    assert plan_bundle_complete(plan_dir)
    assert (plan_dir / LOCATOR_GROUPS_FILE).is_file()
    assert pq.read_table(plan_dir / LOCATOR_GROUPS_FILE).num_rows == 0
    assert (
        plan(catalog_id, artifacts_root, forms=("NO-SUCH-FORM",))["plan_id"]
        == meta["plan_id"]
    )


def test_incomplete_bundle_is_a_conflict_not_a_silent_rewrite(
    catalog_id: str, artifacts_root: Path
) -> None:
    meta = plan(catalog_id, artifacts_root, forms=("10-K",))
    plan_dir = _plan_dir(artifacts_root, meta)
    (plan_dir / SELECTION_REPORT_FILE).unlink()
    with pytest.raises(PlanConflictError, match="incomplete plan bundle"):
        plan(catalog_id, artifacts_root, forms=("10-K",))


# --- locator projection ---------------------------------------------------


def test_locator_groups_hold_one_row_per_locator(
    catalog_id: str, artifacts_root: Path
) -> None:
    """13 occurrences across 12 locators: the shared bundle collapses to one."""
    meta = plan(catalog_id, artifacts_root)
    plan_dir = _plan_dir(artifacts_root, meta)
    locators = pq.read_table(plan_dir / LOCATOR_GROUPS_FILE)
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
    names = pq.read_table(plan_dir / LOCATOR_GROUPS_FILE).schema.names
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
        _plan_dir(artifacts_root, first) / LOCATOR_GROUPS_FILE
    ).to_pylist()

    other_root = artifacts_root.parent / "art2"
    materialize(sample_source, other_root)
    second = plan(catalog_id, other_root, document_suffixes=(".txt",))
    rows_second = pq.read_table(
        _plan_dir(other_root, second) / LOCATOR_GROUPS_FILE
    ).to_pylist()
    assert rows_first == rows_second
