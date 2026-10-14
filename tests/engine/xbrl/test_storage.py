"""Tests for linkbase Parquet serialization and deserialization."""

from pathlib import Path

from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.discovery import DiscoveredLinkbase, LinkbaseType
from edgar_sec.engine.xbrl.storage import (
    linkbases_to_arrow_table,
    read_linkbase_parquet,
    write_linkbase_parquet,
)


def _sample_linkbases() -> tuple[DiscoveredLinkbase, ...]:
    acc = AccessionNumber.from_any("0000950170-24-087843")
    cik = Cik(789019)
    return (
        DiscoveredLinkbase(
            accession=acc,
            cik=cik,
            linkbase_type=LinkbaseType.CALCULATION,
            document_type="EX-101.CAL",
            filename="msft-20240630_cal.xml",
            archive_url="https://www.sec.gov/Archives/cal.xml",
            byte_size=284500,
            sequence=3,
            description="Calculation Linkbase",
        ),
        DiscoveredLinkbase(
            accession=acc,
            cik=cik,
            linkbase_type=LinkbaseType.PRESENTATION,
            document_type="EX-101.PRE",
            filename="msft-20240630_pre.xml",
            archive_url="https://www.sec.gov/Archives/pre.xml",
            byte_size=451200,
            sequence=6,
            description="Presentation Linkbase",
        ),
    )


def test_linkbases_arrow_conversion() -> None:
    """Verify Arrow table schema and length."""
    table = linkbases_to_arrow_table(_sample_linkbases())
    assert table.num_rows == 2
    assert "linkbase_type" in table.column_names
    assert table.column("linkbase_type")[0].as_py() == "calculation"


def test_parquet_round_trip(tmp_path: Path) -> None:
    """Verify atomic Parquet serialization and round-trip read."""
    dest = tmp_path / "linkbases.parquet"
    items = _sample_linkbases()
    written = write_linkbase_parquet(items, dest)
    assert written == 2
    assert dest.exists()

    table = read_linkbase_parquet(dest)
    assert table.num_rows == 2
    assert table.column("filename").to_pylist() == [
        "msft-20240630_cal.xml",
        "msft-20240630_pre.xml",
    ]
