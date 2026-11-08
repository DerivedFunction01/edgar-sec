"""Typed options for the Feed-archives ingest command."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from edgar_sec.pipelines.document_acquisition.options import (
    feed_ingest_options,
    iter_days,
    parse_day,
)


def test_parse_day_accepts_iso_and_refuses_other_shapes() -> None:
    assert parse_day("2024-01-02") == date(2024, 1, 2)
    with pytest.raises(ValueError):
        parse_day("01/02/2024")
    with pytest.raises(ValueError):
        parse_day("2024-13-01")


def test_iter_days_is_inclusive_and_ordered() -> None:
    days = iter_days(date(2024, 1, 30), date(2024, 2, 2))
    assert days == (
        date(2024, 1, 30),
        date(2024, 1, 31),
        date(2024, 2, 1),
        date(2024, 2, 2),
    )
    with pytest.raises(ValueError):
        iter_days(date(2024, 2, 2), date(2024, 1, 30))


def test_feed_ingest_options_defaults_to_feed_branch(tmp_path: Path) -> None:
    options = feed_ingest_options(
        start=date(2024, 1, 1),
        end=date(2024, 1, 2),
        artifacts_root=tmp_path,
    )
    assert options.branch == "feed_archives"
    assert options.acquisition_paths().artifacts_root == tmp_path.resolve()
    with pytest.raises(ValueError):
        feed_ingest_options(start=date(2024, 1, 3), end=date(2024, 1, 2))
