"""Tests for the profile projection in selection features."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.selection.features import UNKNOWN_FOREIGN_STATUS
from edgar_sec.infra.storage.duckdb import connect
from tests.engine.selection.features_support import (
    ABSENT_PROFILE,
    PROFILE_ROW,
    make_builder,
    profile_row,
    projected,
    write_profiles,
    write_targets,
)


def test_profiles_sql_reads_a_populated_profile_as_written(tmp_path: Path) -> None:
    """Baseline against the absent-value cases below: without it a correction could
    pass by flattening every value to the absent marker.
    """
    builder = make_builder(
        tmp_path,
        tmp_path / "t",
        write_profiles(tmp_path / "p.parquet", [PROFILE_ROW]),
    )
    row = projected(builder)["0000000001"]
    assert row["sic_code"] == "3571"
    assert row["owner_org_presence"] == "no_org"
    assert row["filer_category_primary"] == "Accelerated Filer"
    assert row["entity_type"] == "operating"
    assert row["state_of_incorporation"] == "DE"
    assert row["company_name"] == "Example Co"
    assert row["foreign_status"] == "domestic"
    assert row["foreign_country_code"] is None


def test_profiles_sql_normalizes_an_absent_state_to_unknown(tmp_path: Path) -> None:
    """``'' IN (postal codes)`` is false, so an absent state read as foreign. This
    is the defect ``foreign_status`` exists to prevent.
    """
    builder = make_builder(
        tmp_path,
        tmp_path / "t",
        write_profiles(tmp_path / "p.parquet", [ABSENT_PROFILE]),
    )
    row = projected(builder)["0000000001"]
    assert row["foreign_status"] == UNKNOWN_FOREIGN_STATUS
    assert row["foreign_country_code"] is None


def test_profiles_sql_normalizes_every_empty_source_field(tmp_path: Path) -> None:
    """One rule at the projection boundary: the guards matched on NULL while the
    producer writes an empty string.
    """
    builder = make_builder(
        tmp_path,
        tmp_path / "t",
        write_profiles(tmp_path / "p.parquet", [ABSENT_PROFILE]),
    )
    row = projected(builder)["0000000001"]
    assert row["filer_category_primary"] == "unspecified"
    assert row["owner_org_presence"] == "no_org"
    assert row["sic_code"] is None
    assert row["entity_type"] == "operating"
    # A struct-null must read the same way an empty string does.
    assert row["state_of_incorporation"] is None


def test_profiles_sql_reports_a_genuinely_foreign_registrant(tmp_path: Path) -> None:
    """A present, non-US state is still foreign -- the fix is not a blunt demotion."""
    builder = make_builder(
        tmp_path,
        tmp_path / "t",
        write_profiles(
            tmp_path / "p.parquet",
            [profile_row("0000000002", incorporation={"state": "GB"})],
        ),
    )
    row = projected(builder)["0000000002"]
    assert row["foreign_status"] == "foreign"
    assert row["foreign_country_code"] == "GB"


def test_profiles_sql_reports_owner_org_presence_truthfully(tmp_path: Path) -> None:
    """A populated ``owner_org`` is a CIK string, and it is what ``has_org`` means."""
    builder = make_builder(
        tmp_path,
        tmp_path / "t",
        write_profiles(
            tmp_path / "p.parquet",
            [profile_row("0000000003", classification={"owner_org": "0000000009"})],
        ),
    )
    row = projected(builder)["0000000003"]
    assert row["owner_org_presence"] == "has_org"


def test_company_name_stays_a_string_for_a_name_less_registrant(tmp_path: Path) -> None:
    """``company_name`` is the internal fallback ``company_family`` resolves against,
    so NULL there would collapse every name-less registrant into one bucket.
    """
    builder = make_builder(
        tmp_path,
        tmp_path / "t",
        write_profiles(
            tmp_path / "p.parquet",
            [profile_row("0000000004", identity={"name": ""})],
        ),
    )
    assert projected(builder)["0000000004"]["company_name"] == ""


def test_the_projection_carries_no_dropped_columns(tmp_path: Path) -> None:
    """``owner_org_name``, ``sic_description`` and ``state_of_business`` are read by
    nothing; ``owner_org_cik`` stays because ``owner_org_presence`` derives from it.
    """
    builder = make_builder(
        tmp_path,
        tmp_path / "t",
        write_profiles(tmp_path / "p.parquet", [PROFILE_ROW]),
    )
    with connect() as con:
        cursor = con.execute(f"SELECT * FROM ({builder._profiles_sql()}) LIMIT 0")
        names = {description[0] for description in cursor.description}
    assert not {"owner_org_name", "sic_description", "state_of_business"} & names
    assert "owner_org_cik" in names
    assert "state_of_incorporation" in names


def test_absent_source_values_survive_into_the_built_snapshot(
    tmp_path: Path,
) -> None:
    """``inventory.value_counts`` and ``policy.normalize_value`` bypass this SQL and
    read the stored parquet, so the file is what must be pinned.
    """
    artifacts_root = tmp_path / "artifacts"
    target_root = write_targets(
        artifacts_root / "targets",
        [
            {"source_cik": "0000000001", "reported_size": 400},
            {"source_cik": "0000000002", "reported_size": 400},
        ],
    )
    profile_path = write_profiles(
        artifacts_root / "profiles.parquet",
        [ABSENT_PROFILE, profile_row("0000000002", incorporation={"state": "GB"})],
    )
    snapshot = make_builder(artifacts_root, target_root, profile_path).build()

    with connect() as con:
        rows = con.execute(
            "SELECT source_cik, foreign_status, foreign_country_code, "
            "owner_org_presence, filer_category_primary, sic_code, "
            "state_of_incorporation, entity_type, company_family "
            f"FROM {snapshot.occurrence_relation} ORDER BY source_cik"
        ).fetchall()

    absent, foreign = rows
    assert absent[1:] == (
        UNKNOWN_FOREIGN_STATUS,
        None,
        "no_org",
        "unspecified",
        None,
        None,
        "operating",
        # With no family index supplied the column falls back to the registrant name,
        # so an unmatched registrant stays distinct instead of sharing a null bucket.
        "Blank Co",
    )
    assert foreign[1:5] == ("foreign", "GB", "no_org", "Accelerated Filer")
