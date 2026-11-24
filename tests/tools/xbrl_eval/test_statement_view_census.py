"""Statement-view segment census."""

from __future__ import annotations

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.discovery.cohort import canonical_seed_cohort_path
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.pipelines.xbrl_review.bundles import bundle_dir_for
from edgar_sec.tools.xbrl_eval.statement_view_census import _segment_census


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
