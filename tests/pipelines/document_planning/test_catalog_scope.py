from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.filing_catalog.schemas import TARGET_SCHEMA
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.pipelines.document_planning.catalog_scope import (
    CatalogScopeError,
    iter_catalog_scope,
    resolve_catalog_scope,
)
from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths


def _row(
    accession: str,
    *,
    form: str = "10-K",
    filing_date: str = "2024-01-02",
    document_path: str = "primary.htm",
    occurrence_id: str = "occurrence-1",
) -> dict[str, object]:
    return {
        "occurrence_id": occurrence_id,
        "document_locator_key": f"locator-{occurrence_id}",
        "source_cik": "0000000001",
        "accession": accession,
        "form": form,
        "filing_date": filing_date,
        "report_date": None,
        "primary_document": document_path,
        "document_path": document_path,
        "archive_url": f"https://www.sec.gov/Archives/edgar/data/1/{accession}/{document_path}",
        "document_path_source": "primary_document",
        "reported_size": 12,
        "is_xbrl": True,
        "is_inline_xbrl": False,
        "is_xbrl_numeric": True,
    }


def _publish(
    root: Path,
    rows: list[dict[str, object]],
    *,
    plan_id: str = "scope-plan",
    include_digest: bool = False,
    forms: list[str] | None = None,
) -> tuple[Path, Path]:
    output_forms = sorted({str(row["form"]) for row in rows})
    plan_dir = root / "filing_catalog" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    part_records = []
    counts = {}
    for form in output_forms:
        part = plan_dir / "targets" / f"form={form.replace('/', '_')}" / "data.parquet"
        part.parent.mkdir(parents=True)
        form_rows = [row for row in rows if row["form"] == form]
        table = pa.Table.from_pylist(form_rows, schema=TARGET_SCHEMA)
        pq.write_table(table, part)
        counts[form] = table.num_rows
        part_records.append(
            {
                "path": part.relative_to(plan_dir).as_posix(),
                "form": form,
                "row_count": table.num_rows,
                "byte_size": part.stat().st_size,
                "sha256": file_sha256(part),
            }
        )
    manifest = {
        "plan_id": plan_id,
        "catalog_id": "catalog-1",
        "scope": "deterministic",
        "plan_schema_version": "1.3",
        "plan_fingerprint": "catalog-selection-fingerprint",
        "forms": output_forms if forms is None else forms,
        "counts": counts,
        "selected_rows": len(rows),
    }
    if include_digest:
        manifest["target_parts"] = part_records
    manifest_path = plan_dir / "plan.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return plan_dir, manifest_path


def _paths(root: Path):
    return resolve_filing_catalog_paths(root)


def test_iter_catalog_scope_aggregates_duplicate_accessions_in_sorted_order(
    tmp_path: Path,
) -> None:
    accession_a = "000000000124000001"
    accession_b = "000000000124000002"
    _publish(
        tmp_path,
        [
            _row(accession_b, occurrence_id="b"),
            _row(accession_a, occurrence_id="a2", document_path="second.htm"),
            _row(accession_a, occurrence_id="a1"),
        ],
        include_digest=True,
    )

    scope = resolve_catalog_scope("scope-plan", _paths(tmp_path))
    result = list(scope.iter_accessions(batch_size=1))

    assert [item.accession for item in result] == [accession_a, accession_b]
    assert result[0].form == "10-K"
    assert result[0].filing_date == "2024-01-02"
    assert [item.occurrence_id for item in result[0].occurrences] == ["a1", "a2"]
    assert result[0].occurrences[0].archive_url.endswith("/primary.htm")
    assert list(iter_catalog_scope("scope-plan", _paths(tmp_path))) == result


def test_empty_form_filter_does_not_hide_output_forms(tmp_path: Path) -> None:
    _publish(
        tmp_path,
        [_row("000000000124000001", form="10-K/A")],
        include_digest=True,
        forms=[],
    )

    result = list(iter_catalog_scope("scope-plan", _paths(tmp_path)))

    assert [(item.form, item.accession) for item in result] == [
        ("10-K/A", "000000000124000001")
    ]


@pytest.mark.parametrize("conflict", ["form", "filing_date"])
def test_conflicting_accession_facts_are_refused(tmp_path: Path, conflict: str) -> None:
    accession = "000000000124000001"
    second = _row(accession, occurrence_id="second")
    second[conflict] = "10-Q" if conflict == "form" else "2024-02-03"
    _publish(tmp_path, [_row(accession), second], include_digest=True)

    with pytest.raises(CatalogScopeError, match="conflicting catalog"):
        list(iter_catalog_scope("scope-plan", _paths(tmp_path)))


def test_source_pin_is_available_and_stable_before_iteration(tmp_path: Path) -> None:
    _publish(tmp_path, [_row("000000000124000001")], include_digest=True)

    first = resolve_catalog_scope("scope-plan", _paths(tmp_path))
    second = resolve_catalog_scope("scope-plan", _paths(tmp_path))

    assert first.pin.catalog_plan_id == "scope-plan"
    assert first.pin.digest == second.pin.digest
    assert len(first.pin.digest) == 64
    assert list(first.iter_accessions())[0].accession == "000000000124000001"


def test_declared_part_digest_mismatch_is_refused(tmp_path: Path) -> None:
    plan_dir, _ = _publish(
        tmp_path,
        [_row("000000000124000001")],
        include_digest=True,
    )
    part = plan_dir / "targets" / "form=10-K" / "data.parquet"
    tampered = bytearray(part.read_bytes())
    tampered[0] ^= 1
    part.write_bytes(tampered)

    with pytest.raises(CatalogScopeError, match="digest mismatch"):
        resolve_catalog_scope("scope-plan", _paths(tmp_path))


def test_plan_without_declared_part_digests_is_refused(tmp_path: Path) -> None:
    _publish(tmp_path, [_row("000000000124000001")])

    with pytest.raises(CatalogScopeError, match="digest-bearing target_parts"):
        resolve_catalog_scope("scope-plan", _paths(tmp_path))


def test_v12_plan_schema_without_payload_digests_is_refused(tmp_path: Path) -> None:
    _, manifest_path = _publish(
        tmp_path,
        [_row("000000000124000001")],
        include_digest=True,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["plan_schema_version"] = "1.2"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CatalogScopeError, match="schema version is unsupported"):
        resolve_catalog_scope("scope-plan", _paths(tmp_path))


def test_part_change_after_pin_is_refused_before_read(tmp_path: Path) -> None:
    plan_dir, _ = _publish(tmp_path, [_row("000000000124000001")], include_digest=True)
    scope = resolve_catalog_scope("scope-plan", _paths(tmp_path))
    part = plan_dir / "targets" / "form=10-K" / "data.parquet"
    part.write_bytes(part.read_bytes() + b"changed")

    with pytest.raises(CatalogScopeError, match="changed after pinning"):
        list(scope.iter_accessions())


def test_missing_or_corrupt_parts_are_refused(tmp_path: Path) -> None:
    plan_dir, _ = _publish(tmp_path, [_row("000000000124000001")], include_digest=True)
    part = plan_dir / "targets" / "form=10-K" / "data.parquet"
    part.unlink()
    with pytest.raises(CatalogScopeError, match="missing"):
        resolve_catalog_scope("scope-plan", _paths(tmp_path))

    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"not parquet")
    manifest_path = plan_dir / "plan.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["target_parts"][0]["byte_size"] = part.stat().st_size
    manifest["target_parts"][0]["sha256"] = file_sha256(part)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CatalogScopeError, match="corrupt"):
        resolve_catalog_scope("scope-plan", _paths(tmp_path))


def test_manifest_plan_id_and_counts_are_validated(tmp_path: Path) -> None:
    plan_dir, manifest_path = _publish(
        tmp_path, [_row("000000000124000001")], include_digest=True
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["10-K"] = 2
    manifest["selected_rows"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CatalogScopeError, match="target part rows"):
        resolve_catalog_scope("scope-plan", _paths(tmp_path))

    manifest["plan_id"] = "another-plan"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CatalogScopeError, match="envelope is missing or invalid"):
        resolve_catalog_scope("scope-plan", _paths(tmp_path))


def test_scope_does_not_mutate_source_bundle(tmp_path: Path) -> None:
    plan_dir, manifest_path = _publish(
        tmp_path, [_row("000000000124000001")], include_digest=True
    )
    before = {
        path.relative_to(plan_dir): file_sha256(path)
        for path in plan_dir.rglob("*")
        if path.is_file()
    }

    list(iter_catalog_scope("scope-plan", _paths(tmp_path)))

    after = {
        path.relative_to(plan_dir): file_sha256(path)
        for path in plan_dir.rglob("*")
        if path.is_file()
    }
    assert manifest_path.is_file()
    assert before == after
