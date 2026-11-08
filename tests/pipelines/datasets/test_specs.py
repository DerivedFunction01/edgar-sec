"""Dataset specs: member-to-relation mapping and the adopted set census."""

from __future__ import annotations

import pytest

from edgar_sec.pipelines.datasets.specs import DATASET_SPECS, spec_for


def test_adopted_sets_are_exactly_bdc_nmfp_mfrr() -> None:
    assert sorted(DATASET_SPECS) == ["bdc", "mfrr", "nmfp"]


def test_bdc_member_mapping_skips_soi_and_root_members() -> None:
    spec = spec_for("bdc")
    assert spec.relation_for("datasets/sub.tsv") == "bdc_sub"
    assert spec.relation_for("datasets/num.tsv") == "bdc_num"
    assert spec.relation_for("soi.tsv") is None
    assert spec.relation_for("bdc_metadata.json") is None
    assert spec.is_submission_member("datasets/sub.tsv")


def test_nmfp_member_mapping_strips_the_prefix() -> None:
    spec = spec_for("nmfp")
    assert spec.relation_for("NMFP_SUBMISSION.tsv") == "nmfp_submission"
    assert spec.relation_for("NMFP_SCHPORTFOLIOSECURITIES.tsv") == (
        "nmfp_schportfoliosecurities"
    )
    assert spec.relation_for("NMFP_metadata.json") is None


def test_mfrr_member_mapping() -> None:
    spec = spec_for("mfrr")
    assert spec.relation_for("sub.tsv") == "mfrr_sub"
    assert spec.relation_for("scn.tsv") == "mfrr_scn"


def test_unknown_set_is_refused() -> None:
    with pytest.raises(ValueError):
        spec_for("nport")
