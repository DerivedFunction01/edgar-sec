"""Unit tests for the immutable plan-publication contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.pipelines.filing_catalog.paths import REQUIRED_PLAN_FILES
from edgar_sec.pipelines.filing_catalog.publication import (
    TARGET_PLAN_SCHEMA_VERSION,
    PlanConflictError,
    plan_bundle_complete,
    plan_identity,
    publish_plan_bundle,
    reuse_existing_plan,
    staged_plan_bundle,
    write_plan_documents,
)


def _stage_bundle(staging: Path, *, counts: dict[str, int] | None = None) -> None:
    counts = counts if counts is not None else {"10-K": 1}
    for form in counts:
        partition = staging / "targets" / f"form={form}"
        partition.mkdir(parents=True, exist_ok=True)
        (partition / "data.parquet").write_bytes(b"PAR1stub")
    (staging / "locator_groups.parquet").write_bytes(b"PAR1stub")
    write_plan_documents(
        staging,
        {"plan_id": "p1", "scope": "deterministic", "counts": counts},
        {"scope": "deterministic", "counts": counts},
    )


# --- identity -------------------------------------------------------------


def test_plan_identity_is_stable_and_order_independent() -> None:
    a = plan_identity({"catalog": "c", "forms": ["10-K"], "limit": 1})
    b = plan_identity({"limit": 1, "forms": ["10-K"], "catalog": "c"})
    assert a == b
    assert len(a) == 24


def test_plan_identity_separates_distinct_requests() -> None:
    base = plan_identity({"catalog": "c", "forms": ["10-K"]})
    assert base != plan_identity({"catalog": "c", "forms": ["10-Q"]})
    assert base != plan_identity({"catalog": "d", "forms": ["10-K"]})


# --- completeness ---------------------------------------------------------


def test_nothing_published_is_not_complete(tmp_path: Path) -> None:
    assert not plan_bundle_complete(tmp_path / "absent")


def test_all_required_files_are_required(tmp_path: Path) -> None:
    bundle = tmp_path / "p1"
    bundle.mkdir()
    for name in REQUIRED_PLAN_FILES:
        assert not plan_bundle_complete(bundle)
        (bundle / name).write_bytes(b"x")
    assert not plan_bundle_complete(bundle)  # targets/ still missing


def test_complete_bundle_is_detected(tmp_path: Path) -> None:
    bundle = tmp_path / "p1"
    bundle.mkdir()
    _stage_bundle(bundle)
    assert plan_bundle_complete(bundle)


def test_empty_counts_plan_is_complete(tmp_path: Path) -> None:
    """A plan that matched nothing is legitimately complete, not truncated."""
    bundle = tmp_path / "p1"
    bundle.mkdir()
    (bundle / "targets").mkdir()
    (bundle / "locator_groups.parquet").write_bytes(b"x")
    write_plan_documents(
        bundle, {"plan_id": "p1", "scope": "deterministic", "counts": {}}, {}
    )
    assert plan_bundle_complete(bundle)


def test_a_missing_shard_makes_the_bundle_incomplete(tmp_path: Path) -> None:
    bundle = tmp_path / "p1"
    bundle.mkdir()
    _stage_bundle(bundle, counts={"10-K": 1, "10-Q": 1})
    (bundle / "targets" / "form=10-Q" / "data.parquet").unlink()
    assert not plan_bundle_complete(bundle)


def test_an_unreadable_plan_json_is_not_complete(tmp_path: Path) -> None:
    bundle = tmp_path / "p1"
    bundle.mkdir()
    _stage_bundle(bundle)
    (bundle / "plan.json").write_text("{not json", encoding="utf-8")
    assert not plan_bundle_complete(bundle)


# --- reuse ----------------------------------------------------------------


def test_reuse_returns_none_when_nothing_is_published(tmp_path: Path) -> None:
    assert reuse_existing_plan(tmp_path / "p1", "p1", "deterministic") is None


def test_reuse_returns_the_published_document(tmp_path: Path) -> None:
    bundle = tmp_path / "p1"
    bundle.mkdir()
    _stage_bundle(bundle)
    reused = reuse_existing_plan(bundle, "p1", "deterministic")
    assert reused is not None
    assert reused["plan_id"] == "p1"


def test_reuse_raises_on_a_different_plan_id(tmp_path: Path) -> None:
    bundle = tmp_path / "p1"
    bundle.mkdir()
    _stage_bundle(bundle)
    with pytest.raises(PlanConflictError, match="different request"):
        reuse_existing_plan(bundle, "other", "deterministic")


def test_reuse_raises_on_a_different_scope(tmp_path: Path) -> None:
    bundle = tmp_path / "p1"
    bundle.mkdir()
    _stage_bundle(bundle)
    with pytest.raises(PlanConflictError, match="different request"):
        reuse_existing_plan(bundle, "p1", "policy")


def test_reuse_raises_when_expected_meta_diverges(tmp_path: Path) -> None:
    bundle = tmp_path / "p1"
    bundle.mkdir()
    _stage_bundle(bundle)
    with pytest.raises(PlanConflictError, match="diverges"):
        reuse_existing_plan(
            bundle, "p1", "deterministic", expected_meta={"amendment": "amendments"}
        )


def test_reuse_accepts_matching_expected_meta(tmp_path: Path) -> None:
    bundle = tmp_path / "p1"
    bundle.mkdir()
    _stage_bundle(bundle)
    reused = reuse_existing_plan(
        bundle, "p1", "deterministic", expected_meta={"plan_id": "p1"}
    )
    assert reused is not None


def test_reuse_raises_on_an_incomplete_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "p1"
    bundle.mkdir()
    (bundle / "targets").mkdir()
    (bundle / "plan.json").write_text(
        json.dumps({"plan_id": "p1", "scope": "deterministic", "counts": {}}),
        encoding="utf-8",
    )
    with pytest.raises(PlanConflictError, match="incomplete plan bundle"):
        reuse_existing_plan(bundle, "p1", "deterministic")


# --- atomic publication ---------------------------------------------------


def test_staging_yields_a_sibling_of_the_destination(tmp_path: Path) -> None:
    """os.replace is only atomic within one filesystem."""
    final = tmp_path / "plans" / "p1"
    with staged_plan_bundle(final, "p1") as staging:
        assert staging.parent == final.parent
        assert staging != final
        _stage_bundle(staging)
    assert plan_bundle_complete(final)


def test_a_failed_publication_leaves_nothing_behind(tmp_path: Path) -> None:
    final = tmp_path / "plans" / "p1"
    with (
        pytest.raises(RuntimeError, match="boom"),
        staged_plan_bundle(final, "p1") as staging,
    ):
        _stage_bundle(staging)
        raise RuntimeError("boom")
    assert not final.exists()
    assert not staging.exists(), "staging must be cleaned up on failure"


def test_publication_refuses_to_clobber_an_appearing_bundle(tmp_path: Path) -> None:
    final = tmp_path / "plans" / "p1"
    final.parent.mkdir(parents=True)
    with (
        pytest.raises(PlanConflictError, match="appeared at"),
        staged_plan_bundle(final, "p1") as staging,
    ):
        _stage_bundle(staging)
        # simulate a concurrent publisher winning the race
        final.mkdir()
    assert not staging.exists()


def test_publish_moves_the_whole_bundle(tmp_path: Path) -> None:
    final = tmp_path / "plans" / "p1"
    final.parent.mkdir(parents=True)
    staging = tmp_path / "plans" / ".staging"
    staging.mkdir()
    _stage_bundle(staging)
    publish_plan_bundle(staging, final)
    assert plan_bundle_complete(final)
    assert not staging.exists()


def test_target_plan_schema_version_is_declared() -> None:
    assert TARGET_PLAN_SCHEMA_VERSION == "1.0"
