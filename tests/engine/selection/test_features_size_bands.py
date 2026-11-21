"""Tests for family-relative size bands in selection features."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.selection.features import SIZE_BAND_NAMES, UNKNOWN_SIZE_BAND
from edgar_sec.infra.storage.duckdb import connect
from tests.engine.selection.features_support import SIZE_SAMPLES, banded, make_builder


def test_size_band_is_relative_to_its_own_family(tmp_path: Path) -> None:
    """The property absolute thresholds cannot provide: two families 200x apart in
    scale band identically.
    """
    small = {"10-K": list(SIZE_SAMPLES)}
    # Same distribution shape, scaled by 200.
    large = {"4": [size * 200 for size in SIZE_SAMPLES]}

    small_bands = banded(tmp_path, small)
    large_bands = banded(tmp_path, large)
    small_labels = [row["size_band"] for row in small_bands]
    large_labels = [row["size_band"] for row in large_bands]

    # Each sample is 5x the previous, so one per band off the family median.
    assert small_labels == list(SIZE_BAND_NAMES)

    # Anchoring on the family rather than the corpus is the whole point.
    assert large_labels == small_labels
    assert small_bands[0]["reported_size"] * 200 == large_bands[0]["reported_size"]


def test_size_band_is_monotone_in_size(tmp_path: Path) -> None:
    bands = banded(tmp_path, {"10-K": list(SIZE_SAMPLES), "4": [1_000]})
    order = {name: index for index, name in enumerate(SIZE_BAND_NAMES)}
    by_form: dict[str, list[int]] = {}
    for row in bands:
        by_form.setdefault(row["form"], []).append(order[row["size_band"]])
    for form, ranks in by_form.items():
        assert ranks == sorted(ranks), f"{form} bands are not monotone: {ranks}"


def test_size_band_reports_unknown_without_a_size(tmp_path: Path) -> None:
    bands = banded(tmp_path, {"10-K": [1_000]})
    assert bands[0]["size_band"] == "median"

    builder = make_builder(tmp_path, tmp_path / "t", tmp_path / "p.parquet")
    with connect() as con:
        rows = con.execute(
            "SELECT "
            + builder._size_band_sql("reported_size", "median_size")
            + " FROM (SELECT NULL::BIGINT AS reported_size, NULL::DOUBLE AS median_size)"
        ).fetchall()
    assert rows[0][0] == UNKNOWN_SIZE_BAND


def test_the_size_anchor_is_one_row_per_family(tmp_path: Path) -> None:
    """The anchor is a rounding error against the rows it is joined to."""
    builder = make_builder(tmp_path, tmp_path / "t", tmp_path / "p.parquet")
    with connect() as con:
        con.execute("CREATE TABLE targets (form VARCHAR, reported_size BIGINT)")
        con.executemany(
            "INSERT INTO targets VALUES (?, ?)",
            [["10-K", 1000], ["10-K/A", 2000], ["4", 3000], ["4", 4000]],
        )
        anchor = con.execute(
            "SELECT * FROM ("
            + builder._size_band_anchor_sql(
                """SELECT form, reported_size,
                          'key-' || row_number() OVER () AS document_locator_key,
                          'occ-' || row_number() OVER () AS occurrence_id
                   FROM targets"""
            )
            + ") ORDER BY form_family"
        ).fetchall()
    # 10-K and 10-K/A collapse to one family; 4 is the other.
    assert [(row[0], row[1]) for row in anchor] == [("10-K", 1500.0), ("4", 3500.0)]


def test_copied_accession_does_not_weight_the_size_anchor_twice(
    tmp_path: Path,
) -> None:
    builder = make_builder(tmp_path, tmp_path / "t", tmp_path / "p.parquet")
    with connect() as con:
        con.execute(
            "CREATE TABLE targets (form VARCHAR, reported_size BIGINT, "
            "document_locator_key VARCHAR, occurrence_id VARCHAR)"
        )
        con.executemany(
            "INSERT INTO targets VALUES (?, ?, ?, ?)",
            [
                ["10-K", 100, "doc-a", "occ-1"],
                ["10-K", 200, "doc-b", "occ-2"],
            ],
        )
        baseline = con.execute(
            "SELECT median_size FROM ("
            + builder._size_band_anchor_sql("SELECT * FROM targets")
            + ")"
        ).fetchone()[0]
        con.execute(
            "INSERT INTO targets VALUES (?, ?, ?, ?)",
            ["10-K", 100, "doc-a", "occ-3"],
        )
        with_cofiler = con.execute(
            "SELECT median_size FROM ("
            + builder._size_band_anchor_sql("SELECT * FROM targets")
            + ")"
        ).fetchone()[0]
    assert baseline == with_cofiler == 150
