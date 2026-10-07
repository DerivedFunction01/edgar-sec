"""Tests for RelationSpec and merge strategy configurations."""

import pyarrow as pa
import pytest

from edgar_sec.infra.storage.dag.spec import RelationSpec

TEST_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("category", pa.string()),
        ("value", pa.int64()),
    ]
)


def test_valid_relation_specs() -> None:
    upsert_spec = RelationSpec(
        name="test_table",
        schema=TEST_SCHEMA,
        primary_key=("id",),
        merge_strategy="upsert",
        sort_order=("id",),
    )
    assert upsert_spec.name == "test_table"

    append_spec = RelationSpec(
        name="events",
        schema=TEST_SCHEMA,
        primary_key=("id", "category"),
        merge_strategy="append",
        sort_order=("id",),
        tie_breaker_column="value",
        tie_breaker_op="min",
    )
    assert append_spec.tie_breaker_column == "value"

    mask_spec = RelationSpec(
        name="children",
        schema=TEST_SCHEMA,
        primary_key=("id",),
        merge_strategy="scoped_mask",
        sort_order=("id",),
        parent_relation="parents",
        parent_join_key=("id",),
    )
    assert mask_spec.parent_relation == "parents"


def test_invalid_relation_specs() -> None:
    with pytest.raises(ValueError, match="invalid relation name"):
        RelationSpec(
            name="invalid name!",
            schema=TEST_SCHEMA,
            primary_key=("id",),
            merge_strategy="upsert",
            sort_order=("id",),
        )

    with pytest.raises(ValueError, match="must define a primary key"):
        RelationSpec(
            name="test_table",
            schema=TEST_SCHEMA,
            primary_key=(),
            merge_strategy="upsert",
            sort_order=("id",),
        )

    with pytest.raises(ValueError, match="not in schema"):
        RelationSpec(
            name="test_table",
            schema=TEST_SCHEMA,
            primary_key=("missing_col",),
            merge_strategy="upsert",
            sort_order=("id",),
        )

    with pytest.raises(ValueError, match="requires parent_relation"):
        RelationSpec(
            name="children",
            schema=TEST_SCHEMA,
            primary_key=("id",),
            merge_strategy="scoped_mask",
            sort_order=("id",),
        )
