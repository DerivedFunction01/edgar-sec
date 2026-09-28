"""Unit tests for engine.selection.features: form families, eras, snapshots.

The load-bearing test here is
:func:`test_form_family_sql_matches_the_python_rule`. v1 carried two
implementations of one rule -- a Python loop and a hand-written ``$``-anchored
``REGEXP_REPLACE`` alternation -- and they disagreed on any form carrying two
suffixes. The SQL is now generated from the same tuple the Python consumes, so
the test runs both and demands they agree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.domain.filing_catalog.schemas import TARGET_COLUMNS
from edgar_sec.engine.selection.features import (
    FORM_FAMILY_SUFFIXES,
    IDENTITY_COLUMNS,
    FeatureSnapshotBuilder,
    SnapshotPaths,
    era_of,
    form_family,
    form_family_sql,
)
from edgar_sec.engine.selection.policy import EraBand, SelectionPolicy
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.filing_catalog.catalog_job import materialize
from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths

FORM_BATTERY = (
    "10-K",
    "10-K/A",
    "10-K_A",
    "10-K405",
    "10-Q",
    "8-K/A",
    "8-K12B",
    "20-F-POS",
    "S-1_A",
    "N-CSR",
    "6-K/A",
    # Two suffixes at once. v1's SQL alternation is $-anchored and stripped
    # only "-POS", leaving "10-K/A"; the Python loop stripped both.
    "10-K/A-POS",
    # Degenerate: nothing but suffixes, so the collapse is empty.
    "/A",
    "MEF",
    "  10-k  ",
    "",
)


def test_form_family_collapses_amendment_suffixes() -> None:
    assert form_family("10-K/A") == "10-K"
    assert form_family("10-K_A") == "10-K"
    assert form_family("20-F-POS") == "20-F"
    assert form_family("8-K/A") == "8-K"
    assert form_family("S-1_A") == "S-1"


def test_form_family_strips_every_known_suffix() -> None:
    """Each suffix the vocabulary declares must actually be collapsible."""
    for suffix in FORM_FAMILY_SUFFIXES:
        assert form_family(f"10-K{suffix}") == "10-K", suffix


def test_form_family_falls_back_to_the_original_when_nothing_remains() -> None:
    assert form_family("/A") == "/A"
    assert form_family("MEF") == "MEF"


def test_form_family_normalizes_case_and_padding() -> None:
    assert form_family("  10-k  ") == "10-K"


def test_form_family_sql_matches_the_python_rule() -> None:
    """The generated SQL and the Python function must not disagree.

    v1 kept both by hand and they diverged on double-suffix forms. Running the
    SQL over the same battery the Python tests use is the only way to keep them
    honest as the suffix tuple changes.
    """
    expression = form_family_sql("f")
    with connect() as con:
        con.execute("CREATE TEMP TABLE forms(f VARCHAR)")
        con.executemany("INSERT INTO forms VALUES (?)", [[f] for f in FORM_BATTERY])
        rows = con.execute(f"SELECT f, {expression} FROM forms").fetchall()

    assert len(rows) == len(FORM_BATTERY)
    mismatches = [
        (raw, sql, form_family(raw))
        for raw, sql in rows
        if sql != form_family(str(raw))
    ]
    assert mismatches == []


def test_form_family_sql_rejects_an_unsafe_column() -> None:
    with pytest.raises(ValueError, match="unsafe SQL column identifier"):
        form_family_sql("f) OR 1=1 --")


def test_era_of_matches_the_first_satisfying_band() -> None:
    bands = [
        EraBand(name="pre_2000", end_year=2000),
        EraBand(name="2000_2010", start_year=2000, end_year=2011),
        EraBand(name="2011_plus", start_year=2011),
    ]
    assert era_of("1998-12-31", bands) == "pre_2000"
    assert era_of("2005-06-15", bands) == "2000_2010"
    assert era_of("2023-01-01", bands) == "2011_plus"


def test_era_of_reports_unknown_rather_than_dropping_the_row() -> None:
    bands = [EraBand(name="modern", start_year=2010)]
    assert era_of(None, bands) == "unknown"
    assert era_of("", bands) == "unknown"
    assert era_of("not-a-date", bands) == "unknown"
    assert era_of("1999-12-31", bands) == "unknown"


def test_era_bands_tile_without_gaps_or_overlap() -> None:
    """Adjacent half-open bands must cover every year exactly once."""
    bands = [
        EraBand(name="a", start_year=1995, end_year=2005),
        EraBand(name="b", start_year=2005, end_year=2011),
    ]
    for year in range(1995, 2011):
        matches = [
            band.name
            for band in bands
            if band.matches(year=year, date_str=f"{year}-06-30")
        ]
        assert matches == [bands[year >= 2005].name]


def test_identity_columns_track_the_target_schema() -> None:
    """The projection is derived from the domain schema, not restated.

    A new target column must reach the snapshot without a second list to edit.
    """
    projected = [column.strip() for column in IDENTITY_COLUMNS.split(",")]
    assert projected == [c for c in TARGET_COLUMNS if c != "document_path_source"]


def test_builder_rejects_impossible_options() -> None:
    with pytest.raises(ValueError, match="gap_years must be at least 2"):
        FeatureSnapshotBuilder("t", "p", "o", _policy(), gap_years=1)
    with pytest.raises(ValueError, match="cessation_grace_years must be at least 1"):
        FeatureSnapshotBuilder("t", "p", "o", _policy(), cessation_grace_years=0)
    with pytest.raises(ValueError, match="stub_size_threshold must be at least 1"):
        FeatureSnapshotBuilder("t", "p", "o", _policy(), stub_size_threshold=0)


def test_snapshot_dir_is_content_addressed(tmp_path: Path) -> None:
    """Same inputs, same directory; any change of input, a different one."""
    builder = _builder(tmp_path, tmp_path / "t", tmp_path / "p.parquet")
    first = builder.snapshot_dir(["10-K"])
    assert first == builder.snapshot_dir(["10-K"])
    assert first != builder.snapshot_dir(["10-Q"])

    other_policy = SelectionPolicy(
        corpus_id="other", forms=["10-K"], base_content_units=1
    )
    other = FeatureSnapshotBuilder(
        builder.target_root, builder.profile_path, builder.output_root, other_policy
    )
    assert other.snapshot_dir(["10-K"]) != first


def test_builds_a_feature_snapshot_from_the_published_catalog(
    tmp_path: Path, sample_source: Path
) -> None:
    """End to end over the committed catalog fixture.

    The builder is the only place the policy's forms, the catalog targets, the
    registrant profiles, and company-family clustering meet. Running it against
    real materialized output is what proves the five stages compose.
    """
    artifacts_root = tmp_path / "artifacts"
    manifest = materialize(sample_source, artifacts_root)
    catalog_id = str(manifest["catalog_id"])
    paths = resolve_filing_catalog_paths(artifacts_root)

    builder = FeatureSnapshotBuilder(
        target_root=paths.snapshot_targets_dir(catalog_id),
        profile_path=paths.snapshot_profiles_file(catalog_id),
        output_root=artifacts_root,
        policy=_policy(),
    )
    snapshot = builder.build()

    assert isinstance(snapshot, SnapshotPaths)
    assert snapshot.manifest.is_file()
    assert snapshot.occurrence_features.is_file()
    assert snapshot.locator_features.is_file()

    # Intermediate stage files must not survive: they are several times the
    # size of the final snapshot and are pure build scratch.
    for scratch in ("occurrence_base", "lifecycle", "size_bands", "cross_form"):
        assert not (snapshot.snapshot_dir / f"{scratch}.parquet").exists()

    with connect() as con:
        occurrences = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{snapshot.occurrence_features}')"
        ).fetchone()[0]
        locators = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{snapshot.locator_features}')"
        ).fetchone()[0]
        families = con.execute(
            "SELECT COUNT(DISTINCT company_family) FROM "
            f"read_parquet('{snapshot.locator_features}')"
        ).fetchone()[0]

    # The policy asks for 10-K only. The fixture also carries one 10-K/A, and
    # the form filter must exclude it rather than fold it in.
    assert occurrences == 4
    assert locators == 4
    assert families > 1, "clustering collapsed distinct registrants into one family"


def test_rebuilding_the_same_snapshot_reuses_the_published_one(
    tmp_path: Path, sample_source: Path
) -> None:
    """A second build must not rewrite a snapshot it already produced.

    Feature building is the expensive half of selection, and the snapshot is
    content-addressed precisely so a rerun can skip it.
    """
    artifacts_root = tmp_path / "artifacts"
    manifest = materialize(sample_source, artifacts_root)
    catalog_id = str(manifest["catalog_id"])
    paths = resolve_filing_catalog_paths(artifacts_root)

    builder = _builder(
        artifacts_root,
        paths.snapshot_targets_dir(catalog_id),
        paths.snapshot_profiles_file(catalog_id),
    )
    first = builder.build()
    stamp = first.manifest.stat().st_mtime_ns
    second = builder.build()

    assert second == first
    assert second.manifest.stat().st_mtime_ns == stamp


def test_builder_reports_a_catalog_with_no_targets(tmp_path: Path) -> None:
    empty = tmp_path / "filing_targets"
    empty.mkdir()
    builder = FeatureSnapshotBuilder(empty, tmp_path / "p.parquet", tmp_path, _policy())
    with pytest.raises(FileNotFoundError, match="no target part files"):
        builder.build()


def _policy() -> SelectionPolicy:
    return SelectionPolicy(
        corpus_id="test_corpus",
        forms=["10-K"],
        era_bands=[EraBand(name="modern", start_year=2010)],
        base_content_units=2,
        seed_cik_path="__absent__",
    )


def _builder(
    artifacts_root: Path, target_root: Path, profile_path: Path
) -> FeatureSnapshotBuilder:
    return FeatureSnapshotBuilder(
        target_root=target_root,
        profile_path=profile_path,
        output_root=artifacts_root,
        policy=_policy(),
    )
