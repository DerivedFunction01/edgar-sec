"""Statement-view driver: sharding, merging, and classification rules."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.discovery.cohort import (
    canonical_probe_cohort_path,
    canonical_seed_cohort_path,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.pipelines.xbrl_review.bundles import bundle_dir_for
from edgar_sec.tools.xbrl_eval.statement_view_driver import (
    BLOCKED,
    FAITHFUL,
    HONEST,
    MECH_FACE,
    MECH_PARSE,
    MECH_ROOT,
    MECH_UNVERIFIED,
    _segment_census,
    classify_record,
    merge_reports,
    run_driver,
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


def _record(cells: dict[str, Any], *, statement: bool) -> dict[str, Any]:
    """A minimal driver record carrying the given cells."""
    return {"analysis": {"statement": statement}, "cells": cells}


def test_classify_empty_statement_graph_blocks_only_for_statement_filings() -> None:
    """An empty income graph is a missing root on statement filings only."""
    cell = {
        "kind": "statement",
        "error": None,
        "nodes": 0,
        "root": None,
        "valued_nodes": 0,
    }
    verdict = classify_record(
        _record({"statements.income_statement": cell}, statement=True)
    )
    assert verdict["statements.income_statement"] == {
        "classification": BLOCKED,
        "mechanism": MECH_ROOT,
    }
    verdict = classify_record(
        _record({"statements.income_statement": cell}, statement=False)
    )
    assert verdict["statements.income_statement"]["classification"] == HONEST


def test_classify_unavailable_statement_is_honest_even_on_statement_filings() -> None:
    """An explicit UNAVAILABLE posture is honest, not a missing root."""
    cell = {
        "kind": "statement",
        "error": None,
        "nodes": 0,
        "root": None,
        "valued_nodes": 0,
        "status": "UNAVAILABLE",
    }
    verdict = classify_record(
        _record({"statements.comprehensive_income_statement": cell}, statement=True)
    )
    assert (
        verdict["statements.comprehensive_income_statement"]["classification"] == HONEST
    )


def test_classify_scalar_verification_and_cover_parity() -> None:
    """Unverified served values and cover mismatches block; parity is faithful."""
    cells = {
        "financials.revenue": {
            "kind": "scalar",
            "error": None,
            "value": 5.0,
            "in_filed": False,
            "span_class": None,
            "span_error": None,
        },
        "financials.capex": {
            "kind": "scalar",
            "error": None,
            "value": None,
            "in_filed": None,
            "span_class": None,
            "span_error": None,
        },
        "statements.cover": {
            "kind": "cover",
            "error": None,
            "facts": 3,
            "dei_filed": 4,
        },
    }
    verdict = classify_record(_record(cells, statement=True))
    assert verdict["financials.revenue"] == {
        "classification": BLOCKED,
        "mechanism": MECH_UNVERIFIED,
    }
    assert verdict["financials.capex"]["classification"] == HONEST
    assert verdict["statements.cover"] == {
        "classification": BLOCKED,
        "mechanism": MECH_PARSE,
    }
    cells["statements.cover"] = {
        "kind": "cover",
        "error": None,
        "facts": 4,
        "dei_filed": 4,
    }
    verdict = classify_record(_record(cells, statement=True))
    assert verdict["statements.cover"]["classification"] == FAITHFUL


def test_classify_catalog_face_missing_blocks() -> None:
    """A served scalar missing from its statement face blocks the catalog cell."""
    cell = {
        "kind": "catalog",
        "error": None,
        "role_count": 12,
        "violations": [],
        "exceptions": [],
        "face_totals": [
            {"family": "IncomeStatement", "metric": "revenue", "status": "missing"}
        ],
    }
    verdict = classify_record(_record({"statements.catalog": cell}, statement=True))
    assert verdict["statements.catalog"] == {
        "classification": BLOCKED,
        "mechanism": MECH_FACE,
    }


def test_run_driver_smoke_over_smallest_probe_bundle() -> None:
    """The driver records a full cell set for the tiny dei-only 6-K."""
    report = run_driver(
        canonical_probe_cohort_path(),
        folders=["dsgx_2023_6k"],
        workers=1,
    )
    record = report["filings"]["dsgx_2023_6k"]
    assert record["form"] == "6-K"
    assert record["analysis"]["statement"] is False
    assert record["cells"]["statements.cover"]["facts"] > 0
    assert (
        record["classification"]["statements.income_statement"]["classification"]
        == HONEST
    )
    assert set(record["classification"]) == set(record["cells"])


def test_run_driver_segment_census_wiring_and_cell_fields() -> None:
    """The census flag records an empty census; the cell carries its fields."""
    report = run_driver(
        canonical_probe_cohort_path(),
        folders=["dsgx_2023_6k"],
        workers=1,
        segment_census=True,
    )
    record = report["filings"]["dsgx_2023_6k"]
    assert record["segment_census"] == []
    cell = record["cells"]["financials.segment_breakdown"]
    assert cell["classification"] is None
    assert cell["basis"] is None
    assert cell["alternates"] == 0
    assert cell["filed_member_sum"] is None


def test_segment_census_classifies_msft_overlap_with_declared_partitions() -> None:
    """MSFT revenue files two partitions; both are role-declared, one on a face."""
    xbrl = Xbrl.from_bundle(
        bundle_dir_for("0000950170-24-087843", canonical_seed_cohort_path()),
        load_domain_taxonomy(),
    )
    census = _segment_census(xbrl)
    record = next(
        row
        for row in census
        if row["concept"]
        == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
        and row["axis"] == "srt:ProductOrServiceAxis"
    )
    assert record["class"] == "overlapping_partitions"
    assert record["members_filed"] == 12
    assert record["sum_ratio"] == 2.0
    assert record["declared"] == 2
    assert record["statement_declared"] == 1
