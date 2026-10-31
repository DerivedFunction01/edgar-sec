from __future__ import annotations

import pytest

from edgar_sec.foundation.runtime.settings.parquet import (
    DEFAULT_PARQUET_READ_BATCH_SIZE,
    DEFAULT_ROW_GROUP_SIZE,
    get_parquet_specs,
    resolve_parquet_read_batch_size,
    resolve_row_group_size,
)


def test_row_group_setting_uses_the_shared_default() -> None:
    assert get_parquet_specs()["parquet"]["row_group_size"].default == (
        DEFAULT_ROW_GROUP_SIZE
    )


def test_row_group_setting_honors_environment_and_explicit_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PARQUET_ROW_GROUP_SIZE", "17")
    assert resolve_row_group_size() == 17
    assert resolve_row_group_size(3) == 3


def test_parquet_read_batch_honors_environment_and_explicit_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PARQUET_READ_BATCH_SIZE", "29")
    assert resolve_parquet_read_batch_size() == 29
    assert resolve_parquet_read_batch_size(6) == 6
    assert get_parquet_specs()["parquet"]["read_batch_size"].default == (
        DEFAULT_PARQUET_READ_BATCH_SIZE
    )


def test_row_group_setting_rejects_non_positive_values() -> None:
    with pytest.raises(ValueError, match="row_group_size"):
        resolve_row_group_size(0)
