from __future__ import annotations

import pytest

from edgar_sec.pipelines.document_storage.fixture_lineage import (
    FixtureLineageError,
    check_fixture_lineage,
    fixture_lineage_status,
    is_fixture_compatible,
)

PLAN = {
    "catalog_id": "cat-1",
    "policy_corpus": "corpus-2024",
    "seed_fingerprint": "seed-abc",
    "forms": ["10-K", "10-Q"],
}
MANIFEST = dict(PLAN)


def test_matching_lineage_passes() -> None:
    check_fixture_lineage(MANIFEST, PLAN)
    assert is_fixture_compatible(MANIFEST, PLAN) is True


@pytest.mark.parametrize(
    ("field", "value", "label"),
    [
        ("catalog_id", "cat-2", "catalog"),
        ("policy_corpus", "corpus-2023", "policy corpus"),
        ("seed_fingerprint", "seed-xyz", "seed CIK set"),
    ],
)
def test_each_declared_axis_must_agree(field: str, value: str, label: str) -> None:
    manifest = {**MANIFEST, field: value}
    with pytest.raises(FixtureLineageError, match=label):
        check_fixture_lineage(manifest, PLAN)
    assert is_fixture_compatible(manifest, PLAN) is False


def test_form_selection_must_agree() -> None:
    manifest = {**MANIFEST, "forms": ["10-K"]}
    with pytest.raises(FixtureLineageError, match="form selections"):
        check_fixture_lineage(manifest, PLAN)


def test_form_comparison_is_case_and_whitespace_insensitive() -> None:
    manifest = {**MANIFEST, "forms": [" 10-k ", "10-q"]}
    check_fixture_lineage(manifest, {**PLAN, "forms": ["10-Q", "10-K"]})


def test_forms_may_be_a_bare_string() -> None:
    check_fixture_lineage({**MANIFEST, "forms": "10-K"}, {**PLAN, "forms": ["10-K"]})


def test_unrecorded_field_is_unknown_not_mismatch() -> None:
    """A fixture captured before lineage existed must stay usable."""
    with pytest.raises(FixtureLineageError):
        check_fixture_lineage({"catalog_id": "cat-9"}, PLAN)
    # But a manifest that records nothing on an axis imposes no constraint.
    check_fixture_lineage({**MANIFEST, "policy_corpus": ""}, PLAN)
    check_fixture_lineage({**MANIFEST, "catalog_id": None}, PLAN)


def test_plan_without_the_axis_imposes_no_constraint() -> None:
    check_fixture_lineage(
        {**MANIFEST, "catalog_id": "cat-legacy"}, {"forms": ["10-K", "10-Q"]}
    )


def test_legacy_manifest_with_no_lineage_passes() -> None:
    check_fixture_lineage({}, PLAN)
    check_fixture_lineage({}, {})


def test_empty_forms_lists_are_not_a_mismatch() -> None:
    check_fixture_lineage({**MANIFEST, "forms": []}, PLAN)


def test_lineage_status_classification() -> None:
    assert fixture_lineage_status({}) == "unknown"
    assert fixture_lineage_status({"catalog_id": "cat-1"}) == "partial"
    assert (
        fixture_lineage_status({"catalog_id": "cat-1", "forms": ["10-K"]}) == "recorded"
    )


def test_error_is_a_value_error() -> None:
    assert issubclass(FixtureLineageError, ValueError)
