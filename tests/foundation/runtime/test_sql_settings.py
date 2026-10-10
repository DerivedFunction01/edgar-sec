from __future__ import annotations

import pytest

from edgar_sec.foundation.runtime.settings.sql import (
    DEFAULT_SQL_INSERT_BATCH_SIZE,
    get_sql_specs,
    resolve_sql_insert_batch_size,
)


def test_sql_insert_setting_uses_the_shared_default() -> None:
    assert DEFAULT_SQL_INSERT_BATCH_SIZE == 1000
    assert get_sql_specs()["sql"]["insert_batch_size"].default == (
        DEFAULT_SQL_INSERT_BATCH_SIZE
    )


def test_sql_insert_setting_honors_environment_and_explicit_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SQL_INSERT_BATCH_SIZE", "31")
    assert resolve_sql_insert_batch_size() == 31
    assert resolve_sql_insert_batch_size(5) == 5


def test_sql_insert_setting_rejects_non_positive_values() -> None:
    with pytest.raises(ValueError, match="must be >= 1"):
        resolve_sql_insert_batch_size(0)
