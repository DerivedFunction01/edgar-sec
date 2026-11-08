"""Feed inventory: listing enumeration and streamed bundle extraction."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from edgar_sec.pipelines.document_acquisition.feed_inventory import (
    inventory_tarball,
    parse_bundle_header,
    parse_listing_units,
)
from tests.pipelines.document_acquisition.feed_fixtures import (
    feed_tarball,
    listing_html,
    sgml_bundle,
    sgml_nc_bundle,
)


def test_parse_listing_units_reads_dated_tarballs_only() -> None:
    listing = listing_html(
        "20240102.nc.tar.gz",
        "20240103.nc.tar.gz",
        "20240103.nc.tar.gz",
        "index.html",
    )
    units = parse_listing_units(listing)
    assert [(unit.day, unit.filename) for unit in units] == [
        (date(2024, 1, 2), "20240102.nc.tar.gz"),
        (date(2024, 1, 3), "20240103.nc.tar.gz"),
    ]


def test_parse_bundle_header_reads_sec_header_fields() -> None:
    parsed = parse_bundle_header(sgml_bundle().decode())
    assert parsed == (
        "0000320193-24-000001",
        "0000320193",
        "10-K",
        date(2024, 1, 2),
    )
    assert parse_bundle_header("no header here") is None


def test_inventory_tarball_streams_records_and_counts_malformed(
    tmp_path: Path,
) -> None:
    tarball = tmp_path / "20240102.nc.tar.gz"
    tarball.write_bytes(
        feed_tarball(
            {
                "20240102/000032019324000001/0000320193-24-000001.txt": sgml_bundle(),
                "20240102/000000000124000002/0000000001-24-000002.txt": sgml_bundle(
                    accession="0000000001-24-000002",
                    cik=1,
                    form="8-K",
                    filed=date(2024, 1, 2),
                ),
                "20240102/broken/broken.txt": b"not an sgml bundle",
                "20240102/notes/readme.md": b"ignored member",
            }
        )
    )
    outcome = inventory_tarball(
        tarball, feed_date=date(2024, 1, 2), archive_sha256="a" * 64
    )
    assert outcome.malformed_bundles == 1
    assert [record.accession for record in outcome.records] == [
        "0000320193-24-000001",
        "0000000001-24-000002",
    ]
    first = outcome.records[0]
    assert first.cik == "0000320193"
    assert first.form == "10-K"
    assert first.filing_date == date(2024, 1, 2)
    assert first.feed_date == date(2024, 1, 2)
    assert first.bundle_id.endswith("0000320193-24-000001.txt")
    assert first.archive_sha256 == "a" * 64


def test_parse_bundle_header_reads_sgml_tag_fields() -> None:
    parsed = parse_bundle_header(sgml_nc_bundle().decode())
    assert parsed == (
        "0000110471-25-000125",
        "0000110471",
        "10-Q",
        date(2025, 8, 7),
    )


def test_inventory_tarball_reads_nc_members_and_skips_correspondence(
    tmp_path: Path,
) -> None:
    tarball = tmp_path / "20250807.nc.tar.gz"
    tarball.write_bytes(
        feed_tarball(
            {
                "./0000110471-25-000125.nc": sgml_nc_bundle(),
                "./0000930413-25-002391.nc": sgml_nc_bundle(
                    accession="0000930413-25-002391",
                    cik=930413,
                    form="8-K",
                    filed=date(2025, 8, 7),
                ),
                "./0000110471-25-000125.corr01": b"correspondence, not a bundle",
                "./broken.nc": b"not an sgml bundle",
            }
        )
    )
    outcome = inventory_tarball(
        tarball, feed_date=date(2025, 8, 7), archive_sha256="c" * 64
    )
    assert outcome.malformed_bundles == 1
    assert [record.accession for record in outcome.records] == [
        "0000110471-25-000125",
        "0000930413-25-002391",
    ]
    assert outcome.records[1].cik == "0000930413"
    assert outcome.records[1].form == "8-K"
