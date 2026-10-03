"""Tests for feature dimensions and the generated catalog snapshot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.filing_catalog.schemas import (
    PROFILE_SCHEMA,
    TARGET_COLUMNS,
    TARGET_SCHEMA,
)
from edgar_sec.engine.selection.features import (
    FORM_FAMILY_SUFFIXES,
    IDENTITY_COLUMNS,
    SIZE_BAND_NAMES,
    UNKNOWN_FOREIGN_STATUS,
    UNKNOWN_SIZE_BAND,
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
    # Multiple suffixes must be collapsed in sequence.
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
    """The projection is derived from the domain schema, not restated. A new
    target column must reach the snapshot without a second list to edit.
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
    """The only place the policy's forms, the catalog targets, the registrant
    profiles, and company-family clustering meet.
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

    # Stage files are pure build scratch and must not survive.
    for scratch in ("occurrence_base", "lifecycle", "cross_form"):
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

    # The fixture also carries a 10-K/A; the form filter must exclude it.
    assert occurrences == 4
    assert locators == 4
    assert families > 1, "clustering collapsed distinct registrants into one family"


def test_rebuilding_the_same_snapshot_reuses_the_published_one(
    tmp_path: Path, sample_source: Path
) -> None:
    """Content-addressing exists so a rerun skips the expensive half of selection."""
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


def _families_by_cik(locators: Path) -> dict[str, str]:
    with connect() as con:
        rows = con.execute(
            f"SELECT representative_cik, company_family FROM read_parquet('{locators}')"
        ).fetchall()
    return {cik: family for cik, family in rows}


def test_the_seed_set_does_not_influence_company_family(
    tmp_path: Path, sample_source: Path
) -> None:
    """A seed set is a mandatory-filer list, never a family boundary: an operator
    manifest must not be able to redefine corporate identity for a published plan.
    """
    artifacts_root = tmp_path / "artifacts"
    manifest = materialize(sample_source, artifacts_root)
    catalog_id = str(manifest["catalog_id"])
    paths = resolve_filing_catalog_paths(artifacts_root)

    seed_csv = tmp_path / "seed-cik.csv"
    seed_csv.write_text(
        "cik,seed_group,coverage_tags,notes\n0000320193,anchor,,\n", encoding="utf-8"
    )
    seeded = SelectionPolicy(
        corpus_id="test_corpus",
        forms=["10-K"],
        era_bands=[EraBand(name="modern", start_year=2010)],
        base_content_units=2,
        seed_cik_path=str(seed_csv),
    )

    def families_under(policy: SelectionPolicy) -> dict[str, str]:
        builder = FeatureSnapshotBuilder(
            target_root=paths.snapshot_targets_dir(catalog_id),
            profile_path=paths.snapshot_profiles_file(catalog_id),
            output_root=artifacts_root,
            policy=policy,
        )
        return _families_by_cik(builder.build().locator_features)

    # Same profiles, two different seed manifests: identical families.
    assert families_under(seeded) == families_under(_policy())
    # A seeded registrant's family is the profile-derived one.
    assert families_under(seeded)["0000320193"] == "apple fixture"


_SIZE_SAMPLES = (400, 2_000, 8_000, 32_000, 128_000)


def _banded(tmp_path: Path, sizes_by_form: dict[str, list[int]]) -> list[dict]:
    builder = _builder(tmp_path, tmp_path / "t", tmp_path / "p.parquet")
    rows = [
        {"form": form, "reported_size": size}
        for form, sizes in sizes_by_form.items()
        for size in sizes
    ]
    with connect() as con:
        con.execute("CREATE TABLE targets (form VARCHAR, reported_size BIGINT)")
        con.executemany(
            "INSERT INTO targets VALUES (?, ?)",
            [[row["form"], row["reported_size"]] for row in rows],
        )
        union = "SELECT form, reported_size FROM targets"
        anchor = builder._size_band_anchor_sql(union)
        band = builder._size_band_sql("t.reported_size", "a.median_size")
        return [
            dict(zip(("form", "reported_size", "size_band"), row, strict=True))
            for row in con.execute(
                f"""
                WITH size_anchor AS ({anchor})
                SELECT t.form, t.reported_size, {band} AS size_band
                FROM targets t
                LEFT JOIN size_anchor a
                       ON a.form_family = {form_family_sql("t.form")}
                ORDER BY t.form, t.reported_size
                """
            ).fetchall()
        ]


def test_size_band_is_relative_to_its_own_family(tmp_path: Path) -> None:
    """The property absolute thresholds cannot provide: two families 200x apart in
    scale band identically.
    """
    small = {"10-K": list(_SIZE_SAMPLES)}
    # Same distribution shape, scaled by 200.
    large = {"4": [size * 200 for size in _SIZE_SAMPLES]}

    small_bands = _banded(tmp_path, small)
    large_bands = _banded(tmp_path, large)
    small_labels = [row["size_band"] for row in small_bands]
    large_labels = [row["size_band"] for row in large_bands]

    # Each sample is 5x the previous, so one per band off the family median.
    assert small_labels == list(SIZE_BAND_NAMES)

    # Anchoring on the family rather than the corpus is the whole point.
    assert large_labels == small_labels
    assert small_bands[0]["reported_size"] * 200 == large_bands[0]["reported_size"]


def test_size_band_is_monotone_in_size(tmp_path: Path) -> None:
    bands = _banded(tmp_path, {"10-K": list(_SIZE_SAMPLES), "4": [1_000]})
    order = {name: index for index, name in enumerate(SIZE_BAND_NAMES)}
    by_form: dict[str, list[int]] = {}
    for row in bands:
        by_form.setdefault(row["form"], []).append(order[row["size_band"]])
    for form, ranks in by_form.items():
        assert ranks == sorted(ranks), f"{form} bands are not monotone: {ranks}"


def test_size_band_reports_unknown_without_a_size(tmp_path: Path) -> None:
    bands = _banded(tmp_path, {"10-K": [1_000]})
    assert bands[0]["size_band"] == "median"

    builder = _builder(tmp_path, tmp_path / "t", tmp_path / "p.parquet")
    with connect() as con:
        rows = con.execute(
            "SELECT "
            + builder._size_band_sql("reported_size", "median_size")
            + " FROM (SELECT NULL::BIGINT AS reported_size, NULL::DOUBLE AS median_size)"
        ).fetchall()
    assert rows[0][0] == UNKNOWN_SIZE_BAND


def test_the_size_anchor_is_one_row_per_family(tmp_path: Path) -> None:
    """The anchor is a rounding error against the rows it is joined to."""
    builder = _builder(tmp_path, tmp_path / "t", tmp_path / "p.parquet")
    with connect() as con:
        con.execute("CREATE TABLE targets (form VARCHAR, reported_size BIGINT)")
        con.executemany(
            "INSERT INTO targets VALUES (?, ?)",
            [["10-K", 1000], ["10-K/A", 2000], ["4", 3000], ["4", 4000]],
        )
        anchor = con.execute(
            "SELECT * FROM ("
            + builder._size_band_anchor_sql("SELECT form, reported_size FROM targets")
            + ") ORDER BY form_family"
        ).fetchall()
    # 10-K and 10-K/A collapse to one family; 4 is the other.
    assert [(row[0], row[1]) for row in anchor] == [("10-K", 1500.0), ("4", 3500.0)]


# The producer writes '' for an absent field; the committed fixture has none.

_PROFILE_DEFAULTS: dict[str, Any] = {
    "identity": {"name": "Example Co", "former_names": []},
    "classification": {
        "entity_type": "operating",
        "sic_code": "3571",
        "sic_description": "Electronic Computers",
        "owner_org": None,
        "filer_category": "Accelerated Filer",
    },
    "identifiers": {"ein": None, "lei": None},
    "contact": {
        "phone": None,
        "website": None,
        "investor_website": None,
        "description": None,
    },
    "incorporation": {"state": "DE", "state_description": "Delaware"},
    "reporting": {"fiscal_year_end": "1231"},
    "insider_transactions": {"owner_exists": None, "issuer_exists": None},
    "addresses": {
        "mailing": None,
        "business": {"city": "NEW YORK", "state_or_country": "NY"},
    },
    "listings": [],
    "anomalies": [],
    "input_name": "synthetic",
    "status": "ok",
    "profile_schema_version": "1.0.0",
}

# Named so a struct-field rename cannot make these tests vacuous: an unresolvable
# accessor reads NULL, indistinguishable from an absent value.
_PROJECTED_FIELDS = (
    "identity",
    "classification",
    "incorporation",
    "addresses",
)

_TARGET_DEFAULTS: dict[str, Any] = {
    "occurrence_id": "occ-0001",
    "document_locator_key": "0000000001/2021/doc.htm",
    "source_cik": "0000000001",
    "accession": "0000000001-21-000001",
    "form": "10-K",
    "filing_date": "2021-03-01",
    "report_date": "2020-12-31",
    "primary_document": "doc.htm",
    "document_path": "doc.htm",
    "archive_url": "https://www.sec.gov/Archives/edgar/data/1/doc.htm",
    "document_path_source": "primary_document",
    "reported_size": 500_000,
    "is_xbrl": True,
    "is_inline_xbrl": True,
    "is_xbrl_numeric": True,
}


def _profile_row(cik: str, **overrides: Any) -> dict[str, Any]:
    """Structs merge field-by-field, so a test can blank ``owner_org`` without
    restating the other classification fields.
    """
    row: dict[str, Any] = {field.name: None for field in PROFILE_SCHEMA}
    for name, value in _PROFILE_DEFAULTS.items():
        row[name] = value
    row["cik"] = cik
    for name, value in overrides.items():
        if name in _PROJECTED_FIELDS and isinstance(value, dict):
            row[name] = {**row[name], **value}
        else:
            row[name] = value
    return row


def _write_profiles(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=PROFILE_SCHEMA), path)
    return path


def _write_targets(target_root: Path, rows: list[dict[str, Any]]) -> Path:
    target_root.mkdir(parents=True, exist_ok=True)
    merged = [{**_TARGET_DEFAULTS, **row} for row in rows]
    pq.write_table(
        pa.Table.from_pylist(merged, schema=TARGET_SCHEMA),
        target_root / "part-00000.parquet",
    )
    return target_root


def _projected(builder: FeatureSnapshotBuilder) -> dict[str, dict[str, Any]]:
    with connect() as con:
        cursor = con.execute(f"SELECT * FROM ({builder._profiles_sql()})")
        names = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
    return {
        row[names.index("profile_cik")]: dict(zip(names, row, strict=True))
        for row in rows
    }


_PROFILE_ROW = _profile_row("0000000001")

_ABSENT_PROFILE = _profile_row(
    "0000000001",
    identity={"name": "Blank Co"},
    classification={
        "entity_type": "",
        "sic_code": "",
        "sic_description": "",
        "owner_org": "",
        "filer_category": "",
    },
    incorporation={"state": "", "state_description": ""},
    addresses={"business": None},
)


def test_profiles_sql_reads_a_populated_profile_as_written(tmp_path: Path) -> None:
    """Baseline against the absent-value cases below: without it a correction could
    pass by flattening every value to the absent marker.
    """
    builder = _builder(
        tmp_path,
        tmp_path / "t",
        _write_profiles(tmp_path / "p.parquet", [_PROFILE_ROW]),
    )
    row = _projected(builder)["0000000001"]
    assert row["sic_code"] == "3571"
    assert row["owner_org_presence"] == "no_org"
    assert row["filer_category_primary"] == "Accelerated Filer"
    assert row["entity_type"] == "operating"
    assert row["state_of_incorporation"] == "DE"
    assert row["state_of_business"] == "NY"
    assert row["company_name"] == "Example Co"
    assert row["foreign_status"] == "domestic"
    assert row["foreign_country_code"] is None


def test_profiles_sql_normalizes_an_absent_state_to_unknown(tmp_path: Path) -> None:
    """``'' IN (postal codes)`` is false, so an absent state read as foreign. This
    is the defect ``foreign_status`` exists to prevent.
    """
    builder = _builder(
        tmp_path,
        tmp_path / "t",
        _write_profiles(tmp_path / "p.parquet", [_ABSENT_PROFILE]),
    )
    row = _projected(builder)["0000000001"]
    assert row["foreign_status"] == UNKNOWN_FOREIGN_STATUS
    assert row["foreign_country_code"] is None


def test_profiles_sql_normalizes_every_empty_source_field(tmp_path: Path) -> None:
    """One rule at the projection boundary: the guards matched on NULL while the
    producer writes an empty string.
    """
    builder = _builder(
        tmp_path,
        tmp_path / "t",
        _write_profiles(tmp_path / "p.parquet", [_ABSENT_PROFILE]),
    )
    row = _projected(builder)["0000000001"]
    assert row["filer_category_primary"] == "unspecified"
    assert row["owner_org_presence"] == "no_org"
    assert row["sic_code"] is None
    assert row["sic_description"] is None
    assert row["entity_type"] == "operating"
    # A struct-null must read the same way an empty string does.
    assert row["state_of_business"] is None


def test_profiles_sql_reports_a_genuinely_foreign_registrant(tmp_path: Path) -> None:
    """A present, non-US state is still foreign -- the fix is not a blunt demotion."""
    builder = _builder(
        tmp_path,
        tmp_path / "t",
        _write_profiles(
            tmp_path / "p.parquet",
            [_profile_row("0000000002", incorporation={"state": "GB"})],
        ),
    )
    row = _projected(builder)["0000000002"]
    assert row["foreign_status"] == "foreign"
    assert row["foreign_country_code"] == "GB"


def test_profiles_sql_reports_owner_org_presence_truthfully(tmp_path: Path) -> None:
    """A populated ``owner_org`` is a CIK string, and it is what ``has_org`` means."""
    builder = _builder(
        tmp_path,
        tmp_path / "t",
        _write_profiles(
            tmp_path / "p.parquet",
            [_profile_row("0000000003", classification={"owner_org": "0000000009"})],
        ),
    )
    row = _projected(builder)["0000000003"]
    assert row["owner_org_presence"] == "has_org"
    assert row["owner_org_cik"] == "0000000009"


def test_company_name_stays_a_string_for_a_name_less_registrant(tmp_path: Path) -> None:
    """``company_name`` feeds ``company_family`` and is itself a capped dimension,
    so NULL would collapse every name-less registrant into one bucket.
    """
    builder = _builder(
        tmp_path,
        tmp_path / "t",
        _write_profiles(
            tmp_path / "p.parquet",
            [_profile_row("0000000004", identity={"name": ""})],
        ),
    )
    assert _projected(builder)["0000000004"]["company_name"] == ""


def test_the_projection_carries_no_dropped_columns(tmp_path: Path) -> None:
    """``owner_org_name`` could never be non-NULL: the schema carries
    ``classification.owner_org`` (a CIK) and no org name anywhere.
    """
    builder = _builder(
        tmp_path,
        tmp_path / "t",
        _write_profiles(tmp_path / "p.parquet", [_PROFILE_ROW]),
    )
    with connect() as con:
        cursor = con.execute(f"SELECT * FROM ({builder._profiles_sql()}) LIMIT 0")
        names = {description[0] for description in cursor.description}
    assert "owner_org_name" not in names
    assert "state_of_business" in names
    assert {"owner_org_cik", "state_of_incorporation"} <= names


def test_absent_source_values_survive_into_the_built_snapshot(
    tmp_path: Path,
) -> None:
    """``inventory.value_counts`` and ``policy.normalize_value`` bypass this SQL and
    read the stored parquet, so the file is what must be pinned.
    """
    artifacts_root = tmp_path / "artifacts"
    target_root = _write_targets(
        artifacts_root / "targets",
        [
            {"source_cik": "0000000001", "reported_size": 400},
            {"source_cik": "0000000002", "reported_size": 400},
        ],
    )
    profile_path = _write_profiles(
        artifacts_root / "profiles.parquet",
        [_ABSENT_PROFILE, _profile_row("0000000002", incorporation={"state": "GB"})],
    )
    snapshot = _builder(artifacts_root, target_root, profile_path).build()

    with connect() as con:
        rows = con.execute(
            "SELECT source_cik, foreign_status, foreign_country_code, "
            "owner_org_presence, filer_category_primary, sic_code, "
            "state_of_incorporation, state_of_business, entity_type, "
            "company_name, company_family "
            f"FROM read_parquet('{snapshot.occurrence_features}') ORDER BY source_cik"
        ).fetchall()

    absent, foreign = rows
    assert absent[1:] == (
        UNKNOWN_FOREIGN_STATUS,
        None,
        "no_org",
        "unspecified",
        None,
        None,
        None,
        "operating",
        "Blank Co",
        "blank",
    )
    assert foreign[1:5] == ("foreign", "GB", "no_org", "Accelerated Filer")


def _builder(
    artifacts_root: Path, target_root: Path, profile_path: Path
) -> FeatureSnapshotBuilder:
    return FeatureSnapshotBuilder(
        target_root=target_root,
        profile_path=profile_path,
        output_root=artifacts_root,
        policy=_policy(),
    )
