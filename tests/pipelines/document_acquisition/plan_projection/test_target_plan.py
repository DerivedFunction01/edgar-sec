from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.foundation.runtime.settings.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.pipelines.document_acquisition.arrow_schemas import WORK_ORDER_SCHEMA
from edgar_sec.pipelines.document_acquisition.plan_projection.target_plan import (
    TargetPlanError,
    _validate_url,
    _validate_row,
    load_acquisition_work_order,
)
from edgar_sec.pipelines.document_acquisition.arrow_schemas import (
    RESOLVED_OPERATION_SCHEMA,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    target_plan_bundle_schema_version,
    target_plan_matcher_version,
)
from edgar_sec.pipelines.document_planning.schemas import (
    OPERATION_INPUT_SCHEMA_VERSION,
    PLAN_RELATION_SCHEMAS,
    SOURCE_REQUEST_SCHEMA_VERSION,
    TARGET_SCHEMA,
    TARGET_SCHEMA_VERSION,
    TARGET_OPERATION_SCHEMA_VERSION,
)
from tests.pipelines.document_acquisition.plan_projection.plan_fixture import (
    write_plan_bundle,
)


@pytest.fixture
def target_plan_factory(tmp_path):
    def build(
        rows: list[dict[str, Any]] | None = None,
        *,
        has_inventory_snapshot: bool = True,
    ) -> tuple[Path, list[dict[str, Any]]]:
        inventory_digest = "b" * 64 if has_inventory_snapshot else None
        identity = {
            "bundle_schema_version": target_plan_bundle_schema_version(),
            "target_schema_version": TARGET_SCHEMA_VERSION,
            "target_operation_schema_version": TARGET_OPERATION_SCHEMA_VERSION,
            "source_request_schema_version": SOURCE_REQUEST_SCHEMA_VERSION,
            "operation_input_schema_version": OPERATION_INPUT_SCHEMA_VERSION,
            "matcher_version": target_plan_matcher_version(),
            "row_group_size": DEFAULT_ROW_GROUP_SIZE,
            "profile_digest": "c" * 64,
            "catalog_plan_id": "catalog-fixture",
            "catalog_plan_digest": "a" * 64,
            "inventory_snapshot_id": (
                "snapshot-fixture" if has_inventory_snapshot else None
            ),
            "inventory_snapshot_digest": inventory_digest,
        }
        plan_id = f"dplan_{canonical_hash(identity)[:32]}"
        plan_root = tmp_path / plan_id
        plan_root.mkdir(parents=True)
        target_rows = rows or _rows(plan_id)
        for row in target_rows:
            row["target_id"] = canonical_hash(
                [
                    plan_id,
                    row["accession"],
                    row["request_id"],
                    row["inventory_entry_id"],
                    row["status"],
                ]
            )
        write_plan_bundle(plan_root, plan_id, identity, target_rows)
        return plan_root, target_rows

    return build


def _rows(plan_id: str) -> list[dict[str, Any]]:
    accessions = [
        "0000000001-24-000001",
        "0000000001-24-000002",
        "0000000001-24-000003",
        "0000000001-24-000004",
    ]
    result = [
        {
            "target_id": "",
            "accession": accessions[0],
            "form": "10-K",
            "filing_date": "2024-01-01",
            "request_id": "primary:primary",
            "target_role": "primary",
            "target_type": "primary",
            "optional": False,
            "inventory_entry_id": "entry-direct",
            "status": "matched",
            "status_reason": None,
            "source_origin": "inventory_index",
            "retrieval_mode": "direct_url",
            "target_url": "https://www.sec.gov/Archives/edgar/data/1/000000000124000001/report.htm",
            "sequence": None,
            "byte_size": 250,
            "availability_evidence": "index_html",
            "catalog_direct_selection": None,
        },
        {
            "target_id": "",
            "accession": accessions[1],
            "form": "10-K",
            "filing_date": "2024-01-02",
            "request_id": "exhibit:EX-21",
            "target_role": "exhibit",
            "target_type": "EX-21",
            "optional": True,
            "inventory_entry_id": "entry-bundle",
            "status": "matched",
            "status_reason": None,
            "source_origin": "inventory_index",
            "retrieval_mode": "bundle_sequence",
            "target_url": "https://www.sec.gov/Archives/edgar/data/1/000000000124000002/0000000001-24-000002.txt",
            "sequence": 3,
            "byte_size": 500,
            "availability_evidence": "index_html",
            "catalog_direct_selection": None,
        },
        {
            "target_id": "",
            "accession": accessions[2],
            "form": "10-K",
            "filing_date": "2024-01-03",
            "request_id": "graphic:GRAPHIC",
            "target_role": "graphic",
            "target_type": "GRAPHIC",
            "optional": True,
            "inventory_entry_id": None,
            "status": "constructed_candidate",
            "status_reason": "unverified_candidate",
            "source_origin": "inventory_index",
            "retrieval_mode": "constructed_package",
            "target_url": "https://www.sec.gov/Archives/edgar/data/1/000000000124000003/report.zip",
            "sequence": None,
            "byte_size": None,
            "availability_evidence": "constructed",
            "catalog_direct_selection": None,
        },
        {
            "target_id": "",
            "accession": accessions[3],
            "form": "10-K",
            "filing_date": "2024-01-04",
            "request_id": "exhibit:EX-99",
            "target_role": "exhibit",
            "target_type": "EX-99",
            "optional": True,
            "inventory_entry_id": None,
            "status": "unresolved",
            "status_reason": "no_usable_retrieval_locator",
            "source_origin": "inventory_index",
            "retrieval_mode": "none",
            "target_url": None,
            "sequence": None,
            "byte_size": None,
            "availability_evidence": "none",
            "catalog_direct_selection": None,
        },
    ]
    for row in result:
        row["target_id"] = canonical_hash(
            [
                plan_id,
                row["accession"],
                row["request_id"],
                row["inventory_entry_id"],
                row["status"],
            ]
        )
    return result


def _seal_manifest(manifest: dict[str, Any], root: Path) -> None:
    import json

    manifest.pop("plan_digest", None)
    manifest["plan_digest"] = canonical_hash(manifest)
    (root / "plan.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_projects_targets_and_preserves_v4_operation_relations(
    target_plan_factory, tmp_path
):
    plan_root, source_rows = target_plan_factory()
    output = tmp_path / "work-order.parquet"

    result = load_acquisition_work_order(plan_root, output)

    work_order = pq.read_table(output)
    assert work_order.schema.equals(WORK_ORDER_SCHEMA, check_metadata=False)
    assert work_order.num_rows == len(source_rows)
    assert result.executable_count == 2
    assert result.skipped_count == 2
    assert work_order.column("executable").to_pylist() == [True, True, False, False]
    assert work_order.column("skip_reason").to_pylist() == [
        None,
        None,
        "candidate_not_authorized",
        "target_not_matched",
    ]
    assert target_plan_bundle_schema_version() == 5
    assert target_plan_matcher_version() == "target-matcher-v6"
    assert result.bundle_schema_version == 5
    assert result.matcher_version == "target-matcher-v6"
    assert result.target_schema_version == TARGET_SCHEMA_VERSION
    assert sum(
        part["row_count"] for part in result.relation_parts["target_operations"]
    ) == 3 * len(source_rows)
    for relation in (
        "target_operations",
        "source_requests",
        "operation_inputs",
    ):
        descriptors = result.relation_parts[relation]
        assert descriptors
        table = pq.read_table(output.parent / descriptors[0]["path"])
        assert table.schema.equals(
            PLAN_RELATION_SCHEMAS[relation], check_metadata=False
        )
    operation_rows = pq.read_table(
        output.parent / result.relation_parts["target_operations"][0]["path"]
    ).to_pylist()
    input_rows = pq.read_table(
        output.parent / result.relation_parts["operation_inputs"][0]["path"]
    ).to_pylist()
    assert len(operation_rows) == 3 * len(source_rows)
    assert {row["operation_id"] for row in input_rows} <= {
        row["operation_id"] for row in operation_rows
    }
    assert result.relation_counts["source_requests"] == 2
    resolved_descriptors = result.relation_parts["resolved_operations"]
    resolved_table = pq.read_table(output.parent / resolved_descriptors[0]["path"])
    assert resolved_table.schema.equals(RESOLVED_OPERATION_SCHEMA, check_metadata=False)
    resolved_rows = resolved_table.to_pylist()
    assert len(resolved_rows) == 3 * len(source_rows)
    assert all(row["selected"] is (row["operation"] == "raw") for row in resolved_rows)
    assert (
        sum(
            row["source_request_id"] is not None
            for row in resolved_rows
            if row["operation"] == "raw"
        )
        == 2
    )
    assert file_sha256(plan_root / "targets/form=10-K/part-00000.parquet") == next(
        part["sha256"]
        for part in _manifest(plan_root)["parts"]
        if part["relation"] == "targets"
    )


def test_missing_declared_part_size_fails_before_output(target_plan_factory, tmp_path):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    target_part = next(
        part for part in manifest["parts"] if part["relation"] == "targets"
    )
    del target_part["byte_size"]
    _seal_manifest(manifest, plan_root)
    output = tmp_path / "not-created" / "work-order.parquet"

    with pytest.raises(TargetPlanError, match="missing declared byte_size"):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()
    assert not output.parent.exists()


@pytest.mark.parametrize("version", [None, 1])
def test_missing_or_unsupported_bundle_schema_version_fails_before_output(
    target_plan_factory, tmp_path, version
):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    if version is None:
        del manifest["bundle_schema_version"]
        message = "missing or unsupported target-plan bundle schema version"
    else:
        manifest["bundle_schema_version"] = version
        message = "missing or unsupported target-plan bundle schema version"
    _seal_manifest(manifest, plan_root)
    output = tmp_path / "work-order.parquet"

    with pytest.raises(TargetPlanError, match=message):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()


def test_missing_bundle_schema_version_in_identity_is_rejected(
    target_plan_factory, tmp_path
):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    del manifest["plan_identity"]["bundle_schema_version"]
    _seal_manifest(manifest, plan_root)
    output = tmp_path / "work-order.parquet"

    with pytest.raises(
        TargetPlanError, match="bundle schema version in target-plan identity"
    ):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()


def test_unsupported_bundle_schema_version_in_identity_is_rejected(
    target_plan_factory, tmp_path
):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    manifest["plan_identity"]["bundle_schema_version"] = 1
    _seal_manifest(manifest, plan_root)
    output = tmp_path / "work-order.parquet"

    with pytest.raises(
        TargetPlanError, match="bundle schema version in target-plan identity"
    ):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()


@pytest.mark.parametrize(
    ("location", "field"),
    [
        ("manifest", "target_operation_schema_version"),
        ("manifest", "source_request_schema_version"),
        ("manifest", "operation_input_schema_version"),
        ("plan_identity", "target_operation_schema_version"),
        ("plan_identity", "source_request_schema_version"),
        ("plan_identity", "operation_input_schema_version"),
    ],
)
def test_relation_schema_version_mismatch_is_rejected(
    target_plan_factory, tmp_path, location, field
):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    target = manifest if location == "manifest" else manifest["plan_identity"]
    target[field] += 1
    _seal_manifest(manifest, plan_root)

    message = field if location == "manifest" else "relation schema versions"
    with pytest.raises(TargetPlanError, match=message):
        load_acquisition_work_order(plan_root, tmp_path / "work-order.parquet")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("dangling", "lack full matching coverage"),
        ("duplicate", "not sorted and unique"),
    ],
)
def test_operation_input_relations_fail_closed(
    target_plan_factory, tmp_path, mutation, message
):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    descriptor = next(
        part for part in manifest["parts"] if part["relation"] == "operation_inputs"
    )
    path = plan_root / descriptor["path"]
    rows = pq.read_table(path).to_pylist()
    if mutation == "dangling":
        rows[0]["source_request_id"] = "f" * 64
    else:
        rows.append(dict(rows[-1]))
        descriptor["rows"] += 1
        manifest["relation_row_counts"]["operation_inputs"] += 1
    pq.write_table(
        pa.Table.from_pylist(rows, schema=PLAN_RELATION_SCHEMAS["operation_inputs"]),
        path,
        row_group_size=DEFAULT_ROW_GROUP_SIZE,
    )
    descriptor["byte_size"] = path.stat().st_size
    descriptor["sha256"] = file_sha256(path)
    _seal_manifest(manifest, plan_root)

    with pytest.raises(TargetPlanError, match=message):
        load_acquisition_work_order(plan_root, tmp_path / "work-order.parquet")


@pytest.mark.parametrize(
    ("location", "field", "version", "message"),
    [
        (
            "manifest",
            "bundle_schema_version",
            True,
            "target-plan bundle schema version",
        ),
        (
            "manifest",
            "bundle_schema_version",
            float(target_plan_bundle_schema_version()),
            "target-plan bundle schema version",
        ),
        ("manifest", "target_schema_version", True, "target schema version"),
        (
            "manifest",
            "target_schema_version",
            float(TARGET_SCHEMA_VERSION),
            "target schema version",
        ),
        (
            "plan_identity",
            "bundle_schema_version",
            True,
            "bundle schema version in target-plan identity",
        ),
        (
            "plan_identity",
            "bundle_schema_version",
            float(target_plan_bundle_schema_version()),
            "bundle schema version in target-plan identity",
        ),
        (
            "plan_identity",
            "target_schema_version",
            True,
            "metadata does not match its identity",
        ),
        (
            "plan_identity",
            "target_schema_version",
            float(TARGET_SCHEMA_VERSION),
            "metadata does not match its identity",
        ),
    ],
)
def test_schema_versions_reject_boolean_and_float_types(
    target_plan_factory, tmp_path, location, field, version, message
):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    target = manifest if location == "manifest" else manifest["plan_identity"]
    target[field] = version
    _seal_manifest(manifest, plan_root)
    output = tmp_path / "work-order.parquet"

    with pytest.raises(TargetPlanError, match=message):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()


def test_matcher_version_mismatch_is_rejected_before_output(
    target_plan_factory, tmp_path
):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    manifest["matcher_version"] = "target-matcher-v1"
    _seal_manifest(manifest, plan_root)
    output = tmp_path / "work-order.parquet"

    with pytest.raises(TargetPlanError, match="requires target-matcher-v6"):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()


def test_matcher_version_mismatch_in_identity_is_rejected(
    target_plan_factory, tmp_path
):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    manifest["plan_identity"]["matcher_version"] = "target-matcher-v1"
    _seal_manifest(manifest, plan_root)
    output = tmp_path / "work-order.parquet"

    with pytest.raises(
        TargetPlanError, match="matcher version in target-plan identity"
    ):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()


def test_cross_accession_url_fails_before_output(target_plan_factory, tmp_path):
    plan_root, _rows_value = target_plan_factory()
    part = plan_root / "targets/form=10-K/part-00000.parquet"
    rows = pq.read_table(part).to_pylist()
    rows[0]["target_url"] = (
        "https://www.sec.gov/Archives/edgar/data/1/000000000124000002/report.htm"
    )
    _replace_part(plan_root, rows)
    output = tmp_path / "work-order.parquet"

    with pytest.raises(TargetPlanError, match="outside the accession's SEC archive"):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()


def test_target_url_does_not_infer_archive_cik_from_accession_prefix() -> None:
    url = "https://www.sec.gov/Archives/edgar/data/2/000000000124000001/report.htm"

    assert _validate_url(url, "0000000001-24-000001", bundle=False) == url


@pytest.mark.parametrize("sequence", [True, 0, -1])
def test_bundle_sequence_rejects_boolean_and_nonpositive_values(
    target_plan_factory, sequence
):
    plan_root, rows = target_plan_factory()
    row = dict(rows[1], sequence=sequence)

    with pytest.raises(TargetPlanError, match="positive integer"):
        _validate_row(row, plan_root.name, True, "10-K")


def _manifest(root: Path) -> dict[str, Any]:
    import json

    return json.loads((root / "plan.json").read_text(encoding="utf-8"))


def _replace_part(root: Path, rows: list[dict[str, Any]]) -> None:
    import json

    part = root / "targets/form=10-K/part-00000.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=TARGET_SCHEMA), part)
    manifest = _manifest(root)
    target_descriptor = next(
        descriptor
        for descriptor in manifest["parts"]
        if descriptor["relation"] == "targets"
    )
    manifest["target_row_count"] = len(rows)
    manifest["status_counts"] = dict(Counter(row["status"] for row in rows))
    manifest["origin_counts"] = dict(Counter(row["source_origin"] for row in rows))
    target_descriptor["rows"] = len(rows)
    target_descriptor["byte_size"] = part.stat().st_size
    target_descriptor["sha256"] = file_sha256(part)
    _seal_manifest(manifest, root)


def test_load_work_order_lazy_index_trigger_projection(
    target_plan_factory, tmp_path
) -> None:
    base_rows = _rows("test_plan")
    custom_rows = [
        dict(
            base_rows[0],
            source_origin="catalog_direct",
            target_role="primary",
            target_type="primary",
            catalog_direct_selection="exact_form_with_lazy_index",
            inventory_entry_id=None,
        ),
        dict(
            base_rows[1],
            source_origin="catalog_direct",
            target_role="primary",
            target_type="primary",
            catalog_direct_selection="submitted_primary",
            inventory_entry_id=None,
        ),
    ]
    plan_root, _ = target_plan_factory(custom_rows, has_inventory_snapshot=False)
    out = load_acquisition_work_order(plan_root, tmp_path / "work_order.parquet")
    table = pq.read_table(out.parquet_path)
    triggers = table.column("lazy_index_trigger_id").to_pylist()
    versions = table.column("lazy_index_trigger_version").to_pylist()
    assert triggers[0] == "10-K.exact_form"
    assert versions[0] == "1"
    assert triggers[1] is None
    assert versions[1] is None


def test_load_work_order_numeric_form_hive_partition_safety(
    target_plan_factory, tmp_path
) -> None:
    """Numeric form partition names must not be inferred as INT64 in DuckDB."""
    base_rows = _rows("test_plan")
    custom_rows = [
        dict(
            base_rows[0],
            form="4",
            source_origin="catalog_direct",
            target_role="primary",
            target_type="primary",
            catalog_direct_selection="submitted_primary",
            inventory_entry_id=None,
        ),
    ]
    plan_root, _ = target_plan_factory(custom_rows, has_inventory_snapshot=False)
    out = load_acquisition_work_order(plan_root, tmp_path / "work_order.parquet")
    table = pq.read_table(out.parquet_path)
    assert table.column("form").to_pylist() == ["4"]
    assert table.column("lazy_index_trigger_id").to_pylist() == [None]


def test_form_4_exact_form_selection_projects_lazy_index_trigger(
    target_plan_factory, tmp_path
) -> None:
    base = _rows("test_plan")[0]
    custom = dict(
        base,
        form="4",
        source_origin="catalog_direct",
        target_role="primary",
        target_type="primary",
        catalog_direct_selection="exact_form_with_lazy_index",
        inventory_entry_id=None,
    )
    plan_root, _ = target_plan_factory([custom], has_inventory_snapshot=False)
    out = load_acquisition_work_order(plan_root, tmp_path / "work_order.parquet")
    table = pq.read_table(out.parquet_path)
    assert table.column("lazy_index_trigger_id").to_pylist() == ["4.exact_form"]
    assert table.column("lazy_index_trigger_version").to_pylist() == ["1"]


def _scan_row(**overrides):
    base = _rows("test_plan")[0]
    custom = dict(
        base,
        form="4",
        source_origin="catalog_direct",
        target_role="primary",
        target_type="primary",
        catalog_direct_selection="exact_form_with_lazy_index",
        inventory_entry_id=None,
        retrieval_mode="bundle_scan",
        sequence=None,
        target_url=(
            "https://www.sec.gov/Archives/edgar/data/1/"
            "000000000124000001/0000000001-24-000001.txt"
        ),
    )
    custom.update(overrides)
    return custom


def test_bundle_scan_row_projects_executable_without_trigger(
    target_plan_factory, tmp_path
) -> None:
    plan_root, _ = target_plan_factory([_scan_row()], has_inventory_snapshot=False)
    out = load_acquisition_work_order(plan_root, tmp_path / "work_order.parquet")
    table = pq.read_table(out.parquet_path)
    assert table.column("executable").to_pylist() == [True]
    assert table.column("skip_reason").to_pylist() == [None]
    assert table.column("retrieval_mode").to_pylist() == ["bundle_scan"]
    assert table.column("lazy_index_trigger_id").to_pylist() == [None]


def test_bundle_scan_row_with_sequence_is_rejected(
    target_plan_factory, tmp_path
) -> None:
    plan_root, _ = target_plan_factory(
        [_scan_row(sequence=2)], has_inventory_snapshot=False
    )
    with pytest.raises(TargetPlanError, match="must not carry a sequence"):
        load_acquisition_work_order(plan_root, tmp_path / "work_order.parquet")


def test_bundle_scan_row_with_document_url_is_rejected(
    target_plan_factory, tmp_path
) -> None:
    plan_root, _ = target_plan_factory(
        [
            _scan_row(
                target_url=(
                    "https://www.sec.gov/Archives/edgar/data/1/"
                    "000000000124000001/report.htm"
                )
            )
        ],
        has_inventory_snapshot=False,
    )
    with pytest.raises(TargetPlanError, match="canonical submission file"):
        load_acquisition_work_order(plan_root, tmp_path / "work_order.parquet")


def test_amended_form_alias_projects_lazy_index_trigger(
    target_plan_factory, tmp_path
) -> None:
    plan_root, _ = target_plan_factory(
        [
            _scan_row(
                retrieval_mode="direct_url",
                target_url=(
                    "https://www.sec.gov/Archives/edgar/data/1/"
                    "000000000124000001/report.htm"
                ),
                form="4/A",
            )
        ],
        has_inventory_snapshot=False,
    )
    out = load_acquisition_work_order(plan_root, tmp_path / "work_order.parquet")
    table = pq.read_table(out.parquet_path)
    assert table.column("lazy_index_trigger_id").to_pylist() == ["4.exact_form"]
