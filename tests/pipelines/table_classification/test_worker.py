"""Tests for per-filing classification work."""

from __future__ import annotations

from edgar_sec.engine.document.page_markers.models import PageArtifactPolicy
from edgar_sec.engine.forms.normalize import normalize_document
from edgar_sec.engine.tables.extraction.assembly.context_production import DocumentInput
from edgar_sec.infra.storage.parquet import read_parquet_table
from edgar_sec.pipelines.table_classification.worker import (
    SourceDocumentPayload,
    classify_products,
    classify_work_item,
)

from .support import EXHIBIT_TEXT, HTML_10K, FakeSource, make_plan, primary_payload

ACCESSION = "0000000001-26-000001"


def _item(plan, accession: str = ACCESSION):  # noqa: ANN001, ANN202
    return next(item for item in plan.work_items if item.accession == accession)


def test_work_item_classifies_primary_tables(tmp_path) -> None:  # noqa: ANN001
    paths, plan = make_plan(tmp_path)
    source = FakeSource({ACCESSION: (primary_payload(),)})
    result = classify_work_item(plan, _item(plan), source, paths)
    assert result.status == "classified"
    assert result.geometry_count == 3
    assert result.classified_count == 3
    out_dir = paths.work_dir(plan.plan_id, result.work_item_id)
    record = read_parquet_table(out_dir / "filing_records.parquet").to_pylist()
    assert len(record) == 1
    assert record[0]["status"] == "classified"
    assert record[0]["document_count"] == 1
    assert record[0]["source_snapshot_id"] == "snap-test-1"
    geometries = read_parquet_table(out_dir / "geometry_inventory.parquet").to_pylist()
    classifications = read_parquet_table(
        out_dir / "classifications.parquet"
    ).to_pylist()
    assert len(geometries) == len(classifications) == 3
    assert {row["source_document"] for row in geometries} == {"primary"}
    assert {row["provenance_route"] for row in geometries} == {"render_to_txt"}
    assert all(row["family"] for row in classifications)
    assert all(row["evidence"].startswith("[") for row in classifications)


def test_absent_filing_is_honest_absence(tmp_path) -> None:  # noqa: ANN001
    paths, plan = make_plan(tmp_path)
    result = classify_work_item(plan, _item(plan), FakeSource({}), paths)
    assert result.status == "no_documents"
    assert result.geometry_count == 0
    out_dir = paths.work_dir(plan.plan_id, result.work_item_id)
    record = read_parquet_table(out_dir / "filing_records.parquet").to_pylist()
    assert record[0]["absence_reason"] == "not_in_snapshot"
    assert record[0]["document_count"] == 0


def test_unconfirmed_exhibit_is_not_classified(tmp_path) -> None:  # noqa: ANN001
    paths, plan = make_plan(tmp_path)
    exhibit = SourceDocumentPayload(
        document_name="ex13.htm",
        target_role="exhibit",
        target_type="EX-13",
        raw=b"<html><body><p>unrelated exhibit prose</p></body></html>",
        document_type="EX-13",
    )
    source = FakeSource({ACCESSION: (primary_payload(), exhibit)})
    result = classify_work_item(plan, _item(plan), source, paths)
    assert result.status == "classified"
    out_dir = paths.work_dir(plan.plan_id, result.work_item_id)
    record = read_parquet_table(out_dir / "filing_records.parquet").to_pylist()
    assert record[0]["document_count"] == 1


def test_classify_products_from_produced_documents(tmp_path) -> None:  # noqa: ANN001
    paths, plan = make_plan(tmp_path)
    filing = plan.filing_for(ACCESSION)
    result = normalize_document(
        HTML_10K.encode(),
        form="10-K",
        document_path="acme.htm",
        page_policy=PageArtifactPolicy.ANNOTATE,
    )
    outputs = classify_products(plan, filing, (DocumentInput("primary", result),))
    assert outputs.filing_record["status"] == "classified"
    assert outputs.filing_record["document_count"] == 1
    assert len(outputs.geometry_rows) == 3
    assert len(outputs.classification_rows) == 3
    assert {row["provenance_route"] for row in outputs.geometry_rows} == {
        "render_to_txt"
    }


def test_classify_products_with_no_documents_is_absence(tmp_path) -> None:  # noqa: ANN001
    paths, plan = make_plan(tmp_path)
    filing = plan.filing_for(ACCESSION)
    outputs = classify_products(plan, filing, ())
    assert outputs.filing_record["status"] == "no_documents"
    assert outputs.filing_record["absence_reason"] == "no_products"
    assert outputs.geometry_rows == ()


def test_confirmed_exhibit_documents_are_classified(tmp_path) -> None:  # noqa: ANN001
    paths, plan = make_plan(tmp_path)
    exhibit = SourceDocumentPayload(
        document_name="ex13.htm",
        target_role="exhibit",
        target_type="EX-13",
        raw=EXHIBIT_TEXT.encode(),
        document_type="EX-13",
    )
    source = FakeSource({ACCESSION: (primary_payload(), exhibit)})
    result = classify_work_item(plan, _item(plan), source, paths)
    assert result.status == "classified"
    out_dir = paths.work_dir(plan.plan_id, result.work_item_id)
    record = read_parquet_table(out_dir / "filing_records.parquet").to_pylist()
    assert record[0]["document_count"] == 2
    geometries = read_parquet_table(out_dir / "geometry_inventory.parquet").to_pylist()
    assert "ex13.htm" in {row["source_document"] for row in geometries}
