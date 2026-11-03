"""Tests for the per-vintage taxonomy archive and its reproduction pin."""

import hashlib
import json

from edgar_sec.engine.xbrl.taxonomy.archive import (
    CURRENT_SLICES,
    archived_taxonomies,
    bundle_namespaces,
    core_prefixes,
    current_table,
    load_slice,
    namespace_key,
    slice_table,
    slice_versions,
    standard_prefixes,
    table_for_namespaces,
)

# Canonical serialization of the retired standard_item_types.json, hashed
# the day the archive replaced it; see the Step 4 batch log.
_RETIRED_TABLE_SHA256 = (
    "1027f18d536540b1af00354a09c2f69c96eb5e53310da10ae93cb77a5634591b"
)
_RETIRED_TABLE_SIZE = 18130


def test_namespace_key_reads_each_host_pattern() -> None:
    """Namespace URIs map to their (taxonomy, version); dated forms fold."""
    assert namespace_key("http://fasb.org/us-gaap/2024") == ("us-gaap", "2024")
    assert namespace_key("http://fasb.org/us-gaap/2011-01-31") == ("us-gaap", "2011")
    assert namespace_key("http://xbrl.us/us-gaap/2009-01-31") == ("us-gaap", "2009")
    assert namespace_key("http://fasb.org/srt/2023") == ("srt", "2023")
    assert namespace_key("http://xbrl.sec.gov/dei/2011-01-31") == ("dei", "2011")
    assert namespace_key("http://xbrl.sec.gov/dei/2021q4") == ("dei", "2021q4")
    assert namespace_key("http://xbrl.sec.gov/ecd/2022q4") == ("ecd", "2022q4")
    assert namespace_key("http://xbrl.sec.gov/cyd/2024") == ("cyd", "2024")
    assert namespace_key("http://xbrl.sec.gov/ffd/2026") == ("ffd", "2026")
    assert namespace_key("http://xbrl.sec.gov/ffd/2025q4") == ("ffd", "2025q4")
    assert namespace_key("https://xbrl.ifrs.org/taxonomy/2025-03-27/ifrs-full") == (
        "ifrs",
        "2025-03-27",
    )
    assert namespace_key("http://example.com/us-gaap/2024") is None


def test_archive_reproduces_the_retired_table_exactly() -> None:
    """The retired JSON's own slice union still equals it entry for entry."""
    table: dict[str, str] = {}
    for taxonomy, version in CURRENT_SLICES:
        if taxonomy in ("ifrs", "ffd"):
            continue
        table.update(slice_table(taxonomy, version))
    assert len(table) == _RETIRED_TABLE_SIZE
    canonical = json.dumps(table, indent=1, sort_keys=True) + "\n"
    assert hashlib.sha256(canonical.encode()).hexdigest() == _RETIRED_TABLE_SHA256


def test_current_table_resolves_ifrs_item_types() -> None:
    """The default table now carries the current IFRS slice's item types."""
    table = current_table()
    assert table["ifrs-full:Assets"] == "xbrli:monetaryItemType"
    assert len(table) > _RETIRED_TABLE_SIZE


def test_current_table_resolves_ffd_item_types() -> None:
    """The default table carries the current ffd slice's item types."""
    table = current_table()
    assert table["ffd:FormTp"] == "ffd:submissionTypeItemType"
    assert table["ffd:NrrtvMaxAggtOfferingPric"].endswith("Monetary2ItemType")


def test_prefix_sets_derive_from_the_slice_inventory() -> None:
    """Standard is the archived inventory; core is its candidacy subset."""
    assert archived_taxonomies() == (
        "cyd",
        "dei",
        "ecd",
        "ffd",
        "ifrs",
        "srt",
        "us-gaap",
    )
    assert standard_prefixes() == frozenset(
        {"us-gaap", "dei", "srt", "ecd", "cyd", "ifrs-full", "ffd"}
    )
    assert core_prefixes() == frozenset({"us-gaap", "dei", "srt"})
    assert core_prefixes() <= standard_prefixes()
    # Member vocabularies carry no slices and are not concept taxonomies.
    assert not {"country", "currency", "xbrli"} & standard_prefixes()
    # Slice-less standard taxonomies join only when their slices exist.
    assert not {"invest", "rxp", "oef"} & standard_prefixes()


def test_archive_covers_every_published_span() -> None:
    """Slice inventories match the published-release spans in the batch log."""
    assert slice_versions("us-gaap") == (
        "2009",
        "2011",
        "2012",
        "2013",
        "2014",
        "2015",
        "2016",
        "2017",
        "2018",
        "2019",
        "2020",
        "2021",
        "2022",
        "2023",
        "2024",
        "2025",
        "2026",
    )
    assert slice_versions("dei") == (
        "2011",
        "2012",
        "2013",
        "2014",
        "2018",
        "2019",
        "2020",
        "2021",
        "2021q4",
        "2022",
        "2022q4",
        "2023",
        "2024",
        "2025",
        "2026",
    )
    assert slice_versions("srt")[0] == "2018"
    assert slice_versions("ecd")[0] == "2022"
    assert slice_versions("cyd") == ("2024", "2025", "2026")
    assert slice_versions("ffd") == ("2024", "2024q2", "2025", "2025q4", "2026")
    assert len(slice_versions("ifrs")) == 12


def test_slice_rows_carry_the_full_declaration() -> None:
    """One parse yields item type, period type, balance, substitution group."""
    declarations = {d.concept_qname: d for d in load_slice("us-gaap", "2024")}
    assets = declarations["us-gaap:Assets"]
    assert assets.item_type == "xbrli:monetaryItemType"
    assert assets.period_type == "instant"
    assert assets.balance == "debit"
    assert declarations["us-gaap:Liabilities"].balance == "credit"


def test_every_slice_records_its_true_namespace() -> None:
    """Each slice's recorded namespace resolves back to its own slice."""
    import pyarrow.parquet as pq

    from edgar_sec.engine.xbrl.taxonomy.archive import TAXONOMY_PREFIXES, slice_path

    for taxonomy in TAXONOMY_PREFIXES:
        for version in slice_versions(taxonomy):
            rows = pq.read_table(slice_path(taxonomy, version)).to_pylist()
            assert rows, (taxonomy, version)
            namespaces = {row["namespace_uri"] for row in rows}
            assert len(namespaces) == 1
            assert namespace_key(namespaces.pop()) == (taxonomy, version)


def test_vintage_table_merges_only_its_own_vintage() -> None:
    """A concept absent from the filing's vintage merges nothing."""
    table_2011 = table_for_namespaces({"us-gaap": "http://fasb.org/us-gaap/2011-01-31"})
    assert "us-gaap:Assets" in table_2011
    # ASC 606's revenue concept did not exist in the 2011 taxonomy.
    assert (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" not in table_2011
    )
    current = slice_table(*CURRENT_SLICES[0])
    assert "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" in current


def test_unarchived_vintage_merges_nothing() -> None:
    """dei 2009 has no slice (unobtainable); its namespace table is empty."""
    assert table_for_namespaces({"dei": "http://xbrl.sec.gov/dei/2009-01-31"}) == {}


def test_bundle_namespaces_reads_captured_map(tmp_path) -> None:
    """A bundle's captured namespaces.json is the namespace map source."""
    captured = {
        "us-gaap": "http://fasb.org/us-gaap/2024",
        "dei": "http://xbrl.sec.gov/dei/2024",
    }
    (tmp_path / "namespaces.json").write_text(json.dumps(captured), encoding="utf-8")
    assert bundle_namespaces(tmp_path) == captured


def test_bundle_namespaces_missing_file_is_empty(tmp_path) -> None:
    """A bundle with no captured map yields an empty namespace map."""
    assert bundle_namespaces(tmp_path) == {}


def test_ifrs_slice_resolves_by_release_date() -> None:
    """IFRS declarations answer under the ifrs-full prefix and dated vintage."""
    table = table_for_namespaces(
        {"ifrs-full": "https://xbrl.ifrs.org/taxonomy/2025-03-27/ifrs-full"}
    )
    assert table["ifrs-full:Assets"] == "xbrli:monetaryItemType"
    declarations = {d.concept_qname: d for d in load_slice("ifrs", "2025-03-27")}
    assert declarations["ifrs-full:Assets"].period_type == "instant"
