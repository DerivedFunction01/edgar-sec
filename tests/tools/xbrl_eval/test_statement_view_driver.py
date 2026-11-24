"""Statement-view driver: sharding, merging, and classification rules."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from edgar_sec.tools.xbrl_eval.statement_view_driver import (
    merge_reports,
    shard_filings,
)


def _filing(accession: str) -> Any:
    """A shardable stand-in carrying only an accession."""
    return SimpleNamespace(accession=accession)


def test_shard_filings_partition_is_disjoint_and_complete() -> None:
    """Shards over accession order are disjoint and cover every filing."""
    filings = [_filing(f"acc-{i:02d}") for i in range(11)]
    shards = [shard_filings(filings, k, 3) for k in range(3)]
    taken = [f.accession for shard in shards for f in shard]
    assert sorted(taken) == sorted(f.accession for f in filings)
    assert len(taken) == len(set(taken))
    assert [f.accession for f in shards[0]] == ["acc-00", "acc-03", "acc-06", "acc-09"]


def test_shard_filings_rejects_out_of_range() -> None:
    """A shard index outside 0..of-1 is refused."""
    with pytest.raises(ValueError):
        shard_filings([_filing("acc-00")], 2, 2)


def test_merge_reports_rejects_overlap_and_registry_mismatch() -> None:
    """Merged shards must be disjoint and name one registry."""
    left = {"registry": "r", "filings": {"a": {"accession": "1"}}}
    right = {"registry": "r", "filings": {"b": {"accession": "2"}}}
    merged = merge_reports([left, right])
    assert set(merged["filings"]) == {"a", "b"}
    with pytest.raises(ValueError):
        merge_reports([left, left])
    with pytest.raises(ValueError):
        merge_reports([left, {"registry": "other", "filings": {}}])
