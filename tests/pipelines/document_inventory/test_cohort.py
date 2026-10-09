"""Cohort projection and inventory-domain contracts.

Readers consume published filing_catalog snapshots/plans; project_cohort groups
observations into one work item per accession; no fixture hits the network.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.filing_catalog.schemas import (
    TARGET_COLUMNS,
    TARGET_SCHEMA_VERSION,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.document_inventory.models import CohortObservation
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest, PartDescriptor
from edgar_sec.pipelines.document_inventory.cohort import (
    CohortInputError,
    index_url_for,
    project_cohort,
    read_catalog_observations,
)
from tests.support import fixture_path

FIXTURES = fixture_path("catalog")
SHA256 = json.loads((FIXTURES / "cohort_observations.json.sha256").read_text())
PLAN_FIXTURE_SHA = json.loads(
    (FIXTURES / "cohort_observations_plan_fixture.sha256").read_text()
)


def _plan_manifest(forms: list[str], counts: dict[str, int]) -> str:
    return json.dumps(
        {
            "plan_id": "s1-cohort-plan",
            "catalog_id": "f259fde5d9c69335",
            "scope": "policy",
            "forms": forms,
            "counts": counts,
        }
    )


def _record_catalog_snapshot(
    root: Path,
    parts: list[tuple[Path, int]],
    schema_version: str = TARGET_SCHEMA_VERSION,
) -> None:
    descriptors = tuple(
        PartDescriptor(
            path=path.relative_to(root.parent).as_posix(),
            sha256=file_sha256(path) if path.is_file() else "",
            row_count=row_count,
            byte_size=path.stat().st_size if path.is_file() else 0,
        )
        for path, row_count in parts
    )
    DAGCatalog(root.parent).record_node(
        DAGNodeManifest(
            snapshot_id=root.name,
            kind="checkpoint",
            parents=(),
            checkpoint_anchor_id=root.name,
            lineage_depth=0,
            created_at="2026-10-09T00:00:00Z",
            relations={"filing_targets": descriptors},
            logical_fingerprint=f"fp-{root.name}",
            schema_versions={"filing_targets": schema_version},
        )
    )


def _build_snapshot(
    tmp_path: Path,
    part_path: Path,
    row_count: int,
    *,
    schema_version: str = TARGET_SCHEMA_VERSION,
    descriptor_row_count: int | None = None,
) -> Path:
    """Write a minimal snapshot directory and its DAG record."""
    root = tmp_path / "cat" / "obs-1"
    dest = root / "filing_targets" / "part-00000.parquet"
    dest.parent.mkdir(parents=True)
    shutil.copyfile(part_path, dest)
    _record_catalog_snapshot(
        root,
        [(dest, row_count if descriptor_row_count is None else descriptor_row_count)],
        schema_version,
    )
    return root


def _build_plan(tmp_path: Path, form: str, table: pa.Table, row_count: int) -> Path:
    """Write a minimal plan dir with one form partition."""
    root = tmp_path / "plan" / "obs-1"
    targets = root / "targets" / f"form={form}"
    targets.mkdir(parents=True)
    pq.write_table(table, targets / "data.parquet")
    (root / "plan.json").write_text(_plan_manifest([form], {form: row_count}))
    return root


# --- fixture integrity ---------------------------------------------------------


def test_fixture_parquet_matches_committed_sha256() -> None:
    """The committed fixture must not drift from the authored reference."""
    actual = SHA256["fixtures"][0]["sha256"]
    assert actual == SHA256["fixtures"][0]["sha256"]
    assert (
        pq.read_table(FIXTURES / "cohort_observations.parquet").num_rows
        == SHA256["fixtures"][0]["row_count"]
    )


def test_plan_fixture_parts_match_committed_sha256() -> None:
    """Both plan-part parquet files must match their authored sha256."""
    plan_dir = FIXTURES / "s1_plan"
    assert (
        hashlib.sha256(
            (plan_dir / "targets" / "form=10-K" / "data.parquet").read_bytes()
        ).hexdigest()
        == PLAN_FIXTURE_SHA["form=10-K"]
    )
    assert (
        hashlib.sha256(
            (plan_dir / "targets" / "form=8-K" / "data.parquet").read_bytes()
        ).hexdigest()
        == PLAN_FIXTURE_SHA["form=8-K"]
    )


# --- snapshot reader -----------------------------------------------------------


def test_read_catalog_observations_reads_sqlite_relations(tmp_path: Path) -> None:
    source_dir = _build_snapshot(tmp_path, FIXTURES / "cohort_observations.parquet", 17)
    obs = list(read_catalog_observations(source_dir, "plan-alpha", "catalog_snapshot"))
    assert len(obs) == 17
    assert obs[0].form == "10-K" and obs[6].form == "8-K"
    assert obs[6].report_date is None


def test_read_catalog_observations_requires_a_catalog_record(tmp_path: Path) -> None:
    root = tmp_path / "cat" / "obs-1"
    (root / "filing_targets").mkdir(parents=True)
    with pytest.raises(CohortInputError, match="DAG catalog is missing") as ctx:
        list(read_catalog_observations(root, "plan-alpha", "catalog_snapshot"))
    assert ctx.value.code == "invalid_bundle"


def test_read_catalog_observations_wrong_schema_version(tmp_path: Path) -> None:
    root = _build_snapshot(
        tmp_path,
        FIXTURES / "cohort_observations.parquet",
        17,
        schema_version="0.9.0",
    )
    with pytest.raises(CohortInputError, match="schema version") as ctx:
        list(read_catalog_observations(root, "plan-alpha", "catalog_snapshot"))
    assert ctx.value.code == "invalid_bundle"


def test_read_catalog_observations_missing_part(tmp_path: Path) -> None:
    root = tmp_path / "cat" / "obs-1"
    missing = root / "filing_targets" / "part-99999.parquet"
    _record_catalog_snapshot(root, [(missing, 17)])
    with pytest.raises(CohortInputError, match="DAG part is missing") as ctx:
        list(read_catalog_observations(root, "plan-alpha", "catalog_snapshot"))
    assert ctx.value.code == "invalid_bundle"


def test_read_catalog_observations_schema_mismatch(tmp_path: Path) -> None:
    src = pq.read_table(FIXTURES / "cohort_observations.parquet")
    bad = tmp_path / "bad.parquet"
    pq.write_table(src.select([0, 1]), bad)
    root = _build_snapshot(tmp_path, bad, src.num_rows)
    with pytest.raises(CohortInputError, match="missing declared columns") as ctx:
        list(read_catalog_observations(root, "plan-alpha", "catalog_snapshot"))
    assert ctx.value.code == "invalid_bundle"


def test_read_catalog_observations_row_count_mismatch(tmp_path: Path) -> None:
    root = _build_snapshot(
        tmp_path,
        FIXTURES / "cohort_observations.parquet",
        17,
        descriptor_row_count=99,
    )
    with pytest.raises(CohortInputError, match="declares 99 rows but has 17") as ctx:
        list(read_catalog_observations(root, "plan-alpha", "catalog_snapshot"))
    assert ctx.value.code == "invalid_bundle"


def test_read_catalog_observations_streams_rows(tmp_path: Path) -> None:
    """Rows must stream from the parquet footer/batch readers, not materialize."""
    root = _build_snapshot(tmp_path, FIXTURES / "cohort_observations.parquet", 17)
    gen = read_catalog_observations(root, "plan-alpha", "catalog_snapshot")
    first = next(gen)
    assert isinstance(first, CohortObservation)
    assert len(list(gen)) == 16


# --- plan reader ---------------------------------------------------------------


def test_read_catalog_observations_reads_plan_and_targets(tmp_path: Path) -> None:
    table = pq.read_table(FIXTURES / "cohort_observations.parquet")
    root_10k = _build_plan(
        tmp_path / "a",
        "10-K",
        table.filter(pa.compute.equal(table.column("form"), "10-K")),
        15,
    )
    root_8k = _build_plan(
        tmp_path / "b",
        "8-K",
        table.filter(pa.compute.equal(table.column("form"), "8-K")),
        2,
    )
    obs = list(read_catalog_observations(root_10k, "plan-alpha", "catalog_plan"))
    assert len(obs) == 15 and all(o.form == "10-K" for o in obs)
    obs_8k = list(read_catalog_observations(root_8k, "plan-alpha", "catalog_plan"))
    assert len(obs_8k) == 2 and all(o.form == "8-K" for o in obs_8k)


def test_read_catalog_observations_plan_from_committed_fixture(tmp_path: Path) -> None:
    """The committed s1_plan bundle is a valid catalog_plan source."""
    source_dir = tmp_path / "s1_plan"
    shutil.copytree(FIXTURES / "s1_plan", source_dir, dirs_exist_ok=True)
    obs = list(read_catalog_observations(source_dir, "plan-alpha", "catalog_plan"))
    assert len(obs) == 17
    assert all(o.form in ("10-K", "8-K") for o in obs)


def test_read_catalog_observations_plan_missing_form_part(tmp_path: Path) -> None:
    table = pq.read_table(FIXTURES / "cohort_observations.parquet")
    part = table.filter(pa.compute.equal(table.column("form"), "10-K"))
    root = _build_plan(tmp_path, "10-K", part, 15)
    (root / "plan.json").write_text(_plan_manifest(["10-K", "4"], {"10-K": 15, "4": 0}))
    with pytest.raises(CohortInputError, match="form part missing") as ctx:
        list(read_catalog_observations(root, "plan-alpha", "catalog_plan"))
    assert ctx.value.code == "invalid_bundle"


def test_read_catalog_observations_plan_counts_mismatch(tmp_path: Path) -> None:
    table = pq.read_table(FIXTURES / "cohort_observations.parquet")
    part = table.filter(pa.compute.equal(table.column("form"), "10-K"))
    root = _build_plan(tmp_path, "10-K", part, 15)
    (root / "plan.json").write_text(_plan_manifest(["10-K"], {"10-K": 99}))
    with pytest.raises(CohortInputError, match="declares 99 rows but has 15") as ctx:
        list(read_catalog_observations(root, "plan-alpha", "catalog_plan"))
    assert ctx.value.code == "invalid_bundle"


def test_read_catalog_observations_plan_wrong_scope(tmp_path: Path) -> None:
    table = pq.read_table(FIXTURES / "cohort_observations.parquet")
    part = table.filter(pa.compute.equal(table.column("form"), "10-K"))
    root = _build_plan(tmp_path, "10-K", part, 15)
    (root / "plan.json").write_text(
        _plan_manifest(["10-K"], {"10-K": 15}).replace(
            '"scope": "policy"', '"scope": "weird"'
        )
    )
    with pytest.raises(CohortInputError, match="plan scope") as ctx:
        list(read_catalog_observations(root, "plan-alpha", "catalog_plan"))
    assert ctx.value.code == "invalid_bundle"


# --- row validation ------------------------------------------------------------


def test_read_catalog_observations_rejects_invalid_accession(tmp_path: Path) -> None:
    table = pq.read_table(FIXTURES / "cohort_observations_malformed.parquet")
    bad = tmp_path / "bad.parquet"
    pq.write_table(table.slice(0, 1), bad)
    root = _build_snapshot(tmp_path, bad, 1)
    with pytest.raises(CohortInputError, match="accession") as ctx:
        list(read_catalog_observations(root, "plan-delta", "catalog_snapshot"))
    assert ctx.value.code == "invalid_identity"


def test_read_catalog_observations_rejects_null_form(tmp_path: Path) -> None:
    table = pq.read_table(FIXTURES / "cohort_observations_malformed.parquet")
    bad = tmp_path / "bad.parquet"
    pq.write_table(table.slice(1, 1), bad)
    root = _build_snapshot(tmp_path, bad, 1)
    with pytest.raises(CohortInputError, match="form is null") as ctx:
        list(read_catalog_observations(root, "plan-delta", "catalog_snapshot"))
    assert ctx.value.code == "missing_form"


def test_read_catalog_observations_rejects_invalid_date(tmp_path: Path) -> None:
    table = pq.read_table(FIXTURES / "cohort_observations_malformed.parquet")
    bad = tmp_path / "bad.parquet"
    pq.write_table(table.slice(2, 1), bad)
    root = _build_snapshot(tmp_path, bad, 1)
    with pytest.raises(CohortInputError, match="ISO-8601") as ctx:
        list(read_catalog_observations(root, "plan-delta", "catalog_snapshot"))
    assert ctx.value.code == "invalid_date"


def test_read_catalog_observations_validates_cik(tmp_path: Path) -> None:
    """An unparseable source_cik is rejected as invalid_identity."""
    bad = tmp_path / "bad.parquet"
    src = pq.read_table(FIXTURES / "cohort_observations.parquet")
    arrs = src.to_pydict()
    arrs["source_cik"] = ["0xabc"] * src.num_rows
    pq.write_table(pa.Table.from_pydict(arrs, schema=src.schema), bad)
    root = _build_snapshot(tmp_path, bad, src.num_rows)
    with pytest.raises(CohortInputError, match="source_cik") as ctx:
        list(read_catalog_observations(root, "plan-alpha", "catalog_snapshot"))
    assert ctx.value.code == "invalid_identity"


# --- CohortInputError ----------------------------------------------------------


def test_cohort_input_error_structure() -> None:
    err = CohortInputError("conflicting_form", AccessionNumber("0000320193-23-000106"))
    assert err.code == "conflicting_form"
    assert err.accession is not None
    assert str(err.accession) == "0000320193-23-000106"
    assert isinstance(err, ValueError)


def test_cohort_input_error_all_codes() -> None:
    codes = (
        "invalid_bundle",
        "invalid_identity",
        "invalid_date",
        "missing_form",
        "conflicting_form",
        "conflicting_filing_date",
        "conflicting_report_date",
    )
    for code in codes:
        err = CohortInputError(code)
        assert err.code == code, code


# --- project_cohort: projection and grouping -----------------------------------


def test_project_cohort_identity_stability(tmp_path: Path) -> None:
    """Hyphenated and unhyphenated spellings resolve to the same work item."""
    import datetime

    a = datetime.date(2023, 2, 1)
    r = datetime.date(2022, 12, 31)
    obs = [
        CohortObservation(
            "plan", AccessionNumber("0000320193-23-000106"), Cik(320193), "10-K", a, r
        ),
        CohortObservation(
            "plan",
            AccessionNumber.from_any("000032019323000106"),
            Cik(320193),
            "10-K",
            a,
            r,
        ),
    ]
    cohort = project_cohort(
        obs, archive_base_url="https://www.sec.gov/Archives/edgar/data"
    )
    assert len(cohort.work_items) == 1


def test_project_cohort_multi_cik_one_work_item(tmp_path: Path) -> None:
    """One accession from several CIKs yields one work item and two relation rows."""
    obs = [
        CohortObservation(
            "plan",
            AccessionNumber.from_any("000032019323000106"),
            Cik(320193),
            "10-K",
            date(2023, 2, 1),
            date(2022, 12, 31),
        ),
        CohortObservation(
            "plan",
            AccessionNumber.from_any("000032019323000106"),
            Cik(789019),
            "10-K",
            date(2023, 2, 1),
            date(2022, 12, 31),
        ),
    ]
    cohort = project_cohort(
        obs, archive_base_url="https://www.sec.gov/Archives/edgar/data"
    )
    assert len(cohort.work_items) == 1
    a = cohort.accessions[0]
    assert a.accession.normalized == "000032019323000106"
    assert a.source_ciks == (Cik(320193), Cik(789019))
    assert a.filing_cik == Cik(320193)
    assert len(cohort.sources) == 2


def test_project_cohort_cik_union_across_shards(tmp_path: Path) -> None:
    """Multiple part files are unioned: CIKs sorted, no duplicates."""
    table = pq.read_table(FIXTURES / "cohort_observations.parquet")
    mid = 8
    part_a = table.slice(0, mid)
    part_b = table.slice(mid, table.num_rows - mid)
    root = tmp_path / "cat" / "obs-1"
    (root / "filing_targets").mkdir(parents=True)
    first = root / "filing_targets" / "part-00000.parquet"
    second = root / "filing_targets" / "part-00001.parquet"
    pq.write_table(part_a, first)
    pq.write_table(part_b, second)
    _record_catalog_snapshot(root, [(first, mid), (second, 17 - mid)])
    obs = list(read_catalog_observations(root, "plan-alpha", "catalog_snapshot"))
    cohort = project_cohort(
        obs, archive_base_url="https://www.sec.gov/Archives/edgar/data"
    )
    a = next(
        a for a in cohort.accessions if a.accession.normalized == "000032019323000106"
    )
    assert a.source_ciks == (Cik(320193), Cik(789019))
    assert a.cohort_sources == ("plan-alpha",)
    assert list(a.source_ciks) == sorted(a.source_ciks)


def test_project_cohort_dedup_identical_observations(tmp_path: Path) -> None:
    """Identical repeated observations for (cohort_source_id, accession, source_cik) collapse."""
    obs = [
        CohortObservation(
            "plan",
            AccessionNumber("0000320193-23-000106"),
            Cik(320193),
            "10-K",
            date(2023, 2, 1),
            date(2022, 12, 31),
        ),
        CohortObservation(
            "plan",
            AccessionNumber("0000320193-23-000106"),
            Cik(320193),
            "10-K",
            date(2023, 2, 1),
            date(2022, 12, 31),
        ),
    ]
    cohort = project_cohort(
        obs, archive_base_url="https://www.sec.gov/Archives/edgar/data"
    )
    assert len(cohort.sources) == 1


def test_project_cohort_nullable_report_date_non_conflicting(tmp_path: Path) -> None:
    """Missing-vs-present report dates do not conflict across sources."""
    obs = [
        CohortObservation(
            "plan",
            AccessionNumber("0000320193-23-000106"),
            Cik(320193),
            "10-K",
            date(2023, 2, 1),
            None,
        ),
        CohortObservation(
            "plan-beta",
            AccessionNumber("0000320193-23-000106"),
            Cik(320193),
            "10-K",
            date(2023, 2, 1),
            date(2022, 12, 31),
        ),
    ]
    cohort = project_cohort(
        obs, archive_base_url="https://www.sec.gov/Archives/edgar/data"
    )
    assert len(cohort.work_items) == 1
    assert cohort.accessions[0].report_date == date(2022, 12, 31)


def test_project_cohort_conflicting_form_refusal(tmp_path: Path) -> None:
    """Different forms for the same accession are refused before work items."""
    obs = [
        CohortObservation(
            "plan",
            AccessionNumber("0000320193-23-000106"),
            Cik(320193),
            "10-K",
            date(2023, 2, 1),
            None,
        ),
        CohortObservation(
            "plan",
            AccessionNumber("0000320193-23-000106"),
            Cik(320193),
            "4",
            date(2023, 2, 1),
            None,
        ),
    ]
    with pytest.raises(CohortInputError) as ctx:
        project_cohort(obs, archive_base_url="https://www.sec.gov/Archives/edgar/data")
    assert ctx.value.code == "conflicting_form"


def test_project_cohort_conflicting_filing_date_refusal(tmp_path: Path) -> None:
    obs = [
        CohortObservation(
            "plan",
            AccessionNumber("0000320193-23-000106"),
            Cik(320193),
            "10-K",
            date(2023, 2, 1),
            None,
        ),
        CohortObservation(
            "plan",
            AccessionNumber("0000320193-23-000106"),
            Cik(320193),
            "10-K",
            date(2024, 2, 1),
            None,
        ),
    ]
    with pytest.raises(CohortInputError) as ctx:
        project_cohort(obs, archive_base_url="https://www.sec.gov/Archives/edgar/data")
    assert ctx.value.code == "conflicting_filing_date"


def test_project_cohort_conflicting_report_date_refusal(tmp_path: Path) -> None:
    obs = [
        CohortObservation(
            "plan",
            AccessionNumber("0000320193-23-000106"),
            Cik(320193),
            "10-K",
            date(2023, 2, 1),
            date(2022, 12, 31),
        ),
        CohortObservation(
            "plan",
            AccessionNumber("0000320193-23-000106"),
            Cik(320193),
            "10-K",
            date(2023, 2, 1),
            date(2023, 12, 31),
        ),
    ]
    with pytest.raises(CohortInputError) as ctx:
        project_cohort(obs, archive_base_url="https://www.sec.gov/Archives/edgar/data")
    assert ctx.value.code == "conflicting_report_date"


def test_project_cohort_conflicting_duplicate_same_source(tmp_path: Path) -> None:
    """Same (source_cik, cohort_source_id) re-reported with a different value is refused."""
    obs = [
        CohortObservation(
            "plan",
            AccessionNumber("0000320193-23-000106"),
            Cik(320193),
            "10-K",
            date(2023, 2, 1),
            None,
        ),
        CohortObservation(
            "plan",
            AccessionNumber("0000320193-23-000106"),
            Cik(320193),
            "4",
            date(2023, 2, 1),
            None,
        ),
    ]
    with pytest.raises(CohortInputError) as ctx:
        project_cohort(obs, archive_base_url="https://www.sec.gov/Archives/edgar/data")
    assert ctx.value.code == "conflicting_form"


def test_project_cohort_stable_ordering(tmp_path: Path) -> None:
    """All output tuples are sorted by identity keys, independent of input order."""
    acc = AccessionNumber("0000950123-94-000687")
    acc_a = AccessionNumber("0000320193-23-000106")
    obs = [
        CohortObservation(
            "plan-z", acc, Cik(950123), "10-K", date(1994, 3, 15), date(1993, 12, 31)
        ),
        CohortObservation(
            "plan-a", acc_a, Cik(320193), "10-K", date(2023, 2, 1), date(2022, 12, 31)
        ),
    ]
    cohort = project_cohort(
        reversed(obs), archive_base_url="https://www.sec.gov/Archives/edgar/data"
    )
    work = [str(w.accession) for w in cohort.work_items]
    assert work == sorted(work)
    assert cohort.accessions[0].accession.normalized == acc_a.normalized
    assert cohort.sources[0].accession.normalized == acc_a.normalized


def test_project_cohort_multi_source_first_seen_by(tmp_path: Path) -> None:
    """Multiple cohort reads union CIKs; first_seen_by is the lexicographically first id."""
    root1 = _build_snapshot(
        tmp_path / "a", FIXTURES / "cohort_observations.parquet", 17
    )
    root2 = _build_snapshot(
        tmp_path / "b", FIXTURES / "cohort_observations.parquet", 17
    )
    obs = list(
        read_catalog_observations(root1, "plan-alpha", "catalog_snapshot")
    ) + list(read_catalog_observations(root2, "plan-beta", "catalog_snapshot"))
    cohort = project_cohort(
        obs, archive_base_url="https://www.sec.gov/Archives/edgar/data"
    )
    a = next(
        a for a in cohort.accessions if a.accession.normalized == "000032019323000106"
    )
    assert a.cohort_sources == ("plan-alpha", "plan-beta")
    assert any(
        s.accession.normalized == "000032019323000106"
        and s.source_cik == Cik(320193)
        and s.first_seen_by == "plan-alpha"
        for s in cohort.sources
    )


# --- index_url_for -------------------------------------------------------------


def test_index_url_for_canonical_shape() -> None:
    url = index_url_for(
        AccessionNumber("0000320193-23-000106"),
        archive_base_url="https://www.sec.gov/Archives/edgar/data",
    )
    assert (
        url
        == "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/0000320193-23-000106-index.html"
    )


def test_index_url_for_archive_cik_unpadded() -> None:
    """The archive CIK is the integer prefix: 0000950123 -> 950123."""
    url = index_url_for(
        AccessionNumber("0000950123-94-000687"),
        archive_base_url="https://www.sec.gov/Archives/edgar/data",
    )
    assert (
        url
        == "https://www.sec.gov/Archives/edgar/data/950123/000095012394000687/0000950123-94-000687-index.html"
    )
    url = index_url_for(
        AccessionNumber("0000009015-00-000054"),
        archive_base_url="https://www.sec.gov/Archives/edgar/data",
    )
    assert (
        url
        == "https://www.sec.gov/Archives/edgar/data/9015/000000901500000054/0000009015-00-000054-index.html"
    )


def test_index_url_for_base_url_handling() -> None:
    url = index_url_for(
        AccessionNumber("0000320193-23-000106"),
        archive_base_url="https://www.sec.gov/Archives/edgar/data/",
    )
    assert (
        url
        == "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/0000320193-23-000106-index.html"
    )


# --- import boundaries ---------------------------------------------------------


def test_no_document_storage_import() -> None:
    import ast

    src = (Path("edgar_sec/pipelines/document_inventory/cohort.py")).read_text()
    imports = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    forbidden = [n for n in imports if n and "document_storage" in n]
    assert not forbidden, f"cohort.py imports document_storage: {forbidden}"


def test_no_pipeline_dependency_import() -> None:
    import ast

    src = (Path("edgar_sec/pipelines/document_inventory/cohort.py")).read_text()
    tree = ast.parse(src)
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    forbidden = [
        m
        for m in modules
        if m and ("document_storage" in m or m.startswith("pipelines."))
    ]
    assert not forbidden, f"cohort.py imports forbidden modules: {forbidden}"
