"""Tests for the taxonomy era attribution tool."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.tools.xbrl_discovery.era_attribution import (
    build_report,
    discover_slices,
    era_label,
    era_year,
    load_slices,
    main,
)

_COLUMNS = {
    "taxonomy": "taxonomy",
    "version": "version",
    "namespace_uri": "namespace_uri",
    "concept_qname": "concept_qname",
    "name": "name",
    "item_type": "item_type",
    "period_type": "period_type",
    "balance": "balance",
    "substitution_group": "substitution_group",
}

_SLICES = {
    ("us-gaap", "2009"): ["Assets", "Liabilities", "Revenues"],
    ("us-gaap", "2011"): ["Assets", "Liabilities", "Goodwill"],
    ("dei", "2021"): ["DocumentType", "EntityName"],
    ("dei", "2021q4"): ["DocumentType", "EntityName", "FilerName"],
    ("invest", "2013"): ["DerivativeNotionalAmount"],
}

_CURRENT = (("us-gaap", "2011"), ("dei", "2021q4"), ("invest", "2013"))


def _write_archive(root: Path) -> Path:
    """Write the synthetic archive: real parquets, production schema."""
    archive = root / "archive"
    for (taxonomy, version), names in _SLICES.items():
        directory = archive / taxonomy
        directory.mkdir(parents=True, exist_ok=True)
        rows = {column: [] for column in _COLUMNS}
        for name in names:
            rows["taxonomy"].append(taxonomy)
            rows["version"].append(version)
            rows["namespace_uri"].append(f"http://example.test/{taxonomy}/{version}")
            rows["concept_qname"].append(f"{taxonomy}:{name}")
            rows["name"].append(name)
            rows["item_type"].append("xbrli:monetaryItemType")
            rows["period_type"].append("instant")
            rows["balance"].append("debit")
            rows["substitution_group"].append("xbrli:item")
        pq.write_table(pa.table(rows), directory / f"{version}.parquet")
    return archive


def test_era_year_folds_dated_and_quarterly_versions() -> None:
    assert era_year("2009") == 2009
    assert era_year("2021q4") == 2021
    assert era_label("2025-03-27") == "2025"


def test_discover_slices_orders_quarterly_after_annual(tmp_path: Path) -> None:
    archive = _write_archive(tmp_path)
    found = discover_slices(archive)
    dei_versions = [version for taxonomy, version, _ in found if taxonomy == "dei"]
    assert dei_versions == ["2021", "2021q4"]
    assert len(found) == 5


def test_pool_width_cannot_change_loaded_sets(tmp_path: Path) -> None:
    archive = _write_archive(tmp_path)
    assert load_slices(archive, workers=1) == load_slices(archive, workers=2)


def test_concept_attribution_first_appearance_and_core(tmp_path: Path) -> None:
    report = build_report(_write_archive(tmp_path), workers=2, current_slices=_CURRENT)
    us_gaap = next(t for t in report.taxonomies if t.taxonomy == "us-gaap")
    assert us_gaap.concepts.horizon_era == "2009"
    assert us_gaap.concepts.core == frozenset(
        {"us-gaap:Assets", "us-gaap:Liabilities", "us-gaap:Revenues"}
    )
    assert us_gaap.concepts.additions == {"2011": frozenset({"us-gaap:Goodwill"})}
    assert us_gaap.concepts.removals == {"2011": frozenset({"us-gaap:Revenues"})}
    assert us_gaap.concepts.latest == frozenset(
        {"us-gaap:Assets", "us-gaap:Liabilities", "us-gaap:Goodwill"}
    )


def test_quarterly_slice_folds_into_its_year_era(tmp_path: Path) -> None:
    report = build_report(_write_archive(tmp_path), workers=2, current_slices=_CURRENT)
    dei = next(t for t in report.taxonomies if t.taxonomy == "dei")
    assert dei.concepts.horizon_era == "2021"
    assert dei.concepts.additions == {}
    assert dei.concepts.core == frozenset(
        {"dei:DocumentType", "dei:EntityName", "dei:FilerName"}
    )


def test_reconstruction_identity_per_taxonomy(tmp_path: Path) -> None:
    report = build_report(_write_archive(tmp_path), workers=2, current_slices=_CURRENT)
    for taxonomy in report.taxonomies:
        rebuilt = set(taxonomy.concepts.core)
        for added in taxonomy.concepts.additions.values():
            rebuilt |= added
        assert rebuilt == taxonomy.concepts.universe


def test_union_headlines_for_todays_vocabulary(tmp_path: Path) -> None:
    report = build_report(_write_archive(tmp_path), workers=2, current_slices=_CURRENT)
    assert report.today_concepts_by_era == {
        "2009": 2,
        "2011": 1,
        "2013": 1,
        "2021": 3,
    }
    assert report.today_concept_total == 7
    assert report.today_concept_core == 6
    assert report.today_tokens_by_era == {
        "2009": 2,
        "2011": 1,
        "2013": 3,
        "2021": 5,
    }
    assert report.today_token_total == 11
    assert report.today_token_core == 10
    assert report.full_concepts_by_era == {
        "2009": 3,
        "2011": 1,
        "2013": 1,
        "2021": 3,
    }


def test_cli_writes_the_record(tmp_path: Path) -> None:
    archive = _write_archive(tmp_path)
    out = tmp_path / "record.md"
    ret = main(
        [
            "--archive-dir",
            str(archive),
            "--workers",
            "2",
            "--out",
            str(out),
        ]
    )
    assert ret == 0
    text = out.read_text(encoding="utf-8")
    assert "# Taxonomy era attribution — run record" in text
    assert "Archive: 5 slices across 3 taxonomies" in text
    assert "| invest | 2013 | 1 | 1 | 1 |" in text
    assert "2009: 3 (core) · 2011: 1" in text
