"""Shared builders and fixture rows for the selection feature tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.filing_catalog.schemas import PROFILE_SCHEMA, TARGET_SCHEMA
from edgar_sec.engine.selection.features import (
    FeatureSnapshotBuilder,
    form_family_sql,
)
from edgar_sec.engine.selection.policy import EraBand, SelectionPolicy
from edgar_sec.engine.selection.snapshot import SnapshotPaths
from edgar_sec.infra.storage.duckdb import connect


def make_policy() -> SelectionPolicy:
    return SelectionPolicy(
        corpus_id="test_corpus",
        forms=["10-K"],
        era_bands=[EraBand(name="modern", start_year=2010)],
        base_content_units=2,
    )


def families_by_cik(locators: Path) -> dict[str, str]:
    with connect() as con:
        rows = con.execute(
            f"SELECT representative_cik, company_family FROM read_parquet('{locators}')"
        ).fetchall()
    return {cik: family for cik, family in rows}


SIZE_SAMPLES = (400, 2_000, 8_000, 32_000, 128_000)


def banded(tmp_path: Path, sizes_by_form: dict[str, list[int]]) -> list[dict]:
    builder = make_builder(tmp_path, tmp_path / "t", tmp_path / "p.parquet")
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
        union = """SELECT form, reported_size,
                          'key-' || row_number() OVER () AS document_locator_key,
                          'occ-' || row_number() OVER () AS occurrence_id
                   FROM targets"""
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


# The producer writes '' for an absent field; the committed fixture has none.

PROFILE_DEFAULTS: dict[str, Any] = {
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
PROJECTED_FIELDS = (
    "identity",
    "classification",
    "incorporation",
    "addresses",
)

TARGET_DEFAULTS: dict[str, Any] = {
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
    "primary_exhibit_like": False,
    "reported_size": 500_000,
    "is_xbrl": True,
    "is_inline_xbrl": True,
    "is_xbrl_numeric": True,
}


def profile_row(cik: str, **overrides: Any) -> dict[str, Any]:
    """Structs merge field-by-field, so a test can blank ``owner_org`` without
    restating the other classification fields.
    """
    row: dict[str, Any] = {field.name: None for field in PROFILE_SCHEMA}
    for name, value in PROFILE_DEFAULTS.items():
        row[name] = value
    row["cik"] = cik
    for name, value in overrides.items():
        if name in PROJECTED_FIELDS and isinstance(value, dict):
            row[name] = {**row[name], **value}
        else:
            row[name] = value
    return row


def write_profiles(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=PROFILE_SCHEMA), path)
    return path


def write_targets(target_root: Path, rows: list[dict[str, Any]]) -> Path:
    target_root.mkdir(parents=True, exist_ok=True)
    merged = [{**TARGET_DEFAULTS, **row} for row in rows]
    pq.write_table(
        pa.Table.from_pylist(merged, schema=TARGET_SCHEMA),
        target_root / "part-00000.parquet",
    )
    return target_root


def projected(builder: FeatureSnapshotBuilder) -> dict[str, dict[str, Any]]:
    with connect() as con:
        cursor = con.execute(f"SELECT * FROM ({builder._profiles_sql()})")
        names = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
    return {
        row[names.index("profile_cik")]: dict(zip(names, row, strict=True))
        for row in rows
    }


PROFILE_ROW = profile_row("0000000001")

ABSENT_PROFILE = profile_row(
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


def make_builder(
    artifacts_root: Path, target_root: Path, profile_path: Path
) -> FeatureSnapshotBuilder:
    return FeatureSnapshotBuilder(
        target_root=target_root,
        profile_path=profile_path,
        output_root=artifacts_root,
        policy=make_policy(),
    )


def make_snapshot(tmp_path: Path, rows: list[dict[str, Any]]) -> SnapshotPaths:
    artifacts_root = tmp_path / "artifacts"
    target_root = write_targets(artifacts_root / "targets", rows)
    profile_path = write_profiles(artifacts_root / "profiles.parquet", [PROFILE_ROW])
    return make_builder(artifacts_root, target_root, profile_path).build()


def co_filed(count: int, key: str) -> list[dict[str, Any]]:
    """`count` registrants claiming one filing, the way a co-filed 10-K looks."""
    return [
        {
            "occurrence_id": f"occ-{key}-{index}",
            "document_locator_key": key,
            "source_cik": f"000000000{index + 1}",
            "accession": f"acc-{key}",
        }
        for index in range(count)
    ]
