"""Input manifest ingestion and fingerprinting tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
from tests.support import fixture_path


def test_mini_manifest_yields_four_usable_ciks() -> None:
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))

    assert manifest.ciks == (
        "0000001985",
        "0000001761",
        "0000000020",
        "0000037996",
    )
    assert manifest.row_count == 4
    assert manifest.duplicate_count == 1
    assert manifest.input_name == "cik_sec_mini.csv"
    assert len(manifest.input_fingerprint) == 64


def test_mini_manifest_records_skipped_rows() -> None:
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    values = {entry["value"].strip() for entry in manifest.skipped}
    assert "not-a-cik" in values
    assert "99999999999" in values
    assert "" in values


def test_fingerprint_is_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    first = tmp_path / "a.csv"
    first.write_text("cik,name\n1,A\n2,B\n", encoding="utf-8")
    second = tmp_path / "b.csv"
    second.write_text("cik,name\n1,A\n2,B\n", encoding="utf-8")
    third = tmp_path / "c.csv"
    third.write_text("cik,name\n1,A\n2,C\n", encoding="utf-8")

    assert (
        read_cik_manifest(first).input_fingerprint
        == read_cik_manifest(second).input_fingerprint
    )
    assert (
        read_cik_manifest(first).input_fingerprint
        != read_cik_manifest(third).input_fingerprint
    )


def test_empty_cell_does_not_become_cik_zero(tmp_path: Path) -> None:
    manifest_path = tmp_path / "empty.csv"
    manifest_path.write_text("cik,name\n,A\n ,B\n7,C\n", encoding="utf-8")
    manifest = read_cik_manifest(manifest_path)
    assert manifest.ciks == ("0000000007",)
    assert "0000000000" not in manifest.ciks


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_cik_manifest(tmp_path / "nope.csv")


def test_manifest_with_no_usable_ciks_raises(tmp_path: Path) -> None:
    manifest_path = tmp_path / "bad.csv"
    manifest_path.write_text("cik,name\nnope,A\nalso-bad,B\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no usable CIKs"):
        read_cik_manifest(manifest_path)
