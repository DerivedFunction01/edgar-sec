import fcntl
import hashlib
import json
import os
from pathlib import Path

import pytest

import edgar_sec.infra.storage.cohort.workspace as workspace_module
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import CohortPaths
from edgar_sec.infra.storage.cohort.workspace import CohortWorkspace
from edgar_sec.infra.storage.duckdb import connect, copy_query_to_parquet
from edgar_sec.infra.storage.object_store.store import ObjectStore


def _registered(
    catalog: CohortCatalog,
    paths: CohortPaths,
    name: str,
    ciks: tuple[tuple[str, str], ...],
):
    roster_id = hashlib.sha256("\n".join(cik for cik, _ in ciks).encode()).hexdigest()
    cohort_id = f"c-{roster_id[:16]}"
    dataset = paths.cohort_dataset_file(cohort_id)
    query_rows = ", ".join(
        f"({ordinal}, '{cik}', '{entity_name}')"
        for ordinal, (cik, entity_name) in enumerate(ciks)
    )
    with connect() as connection:
        copy_query_to_parquet(
            connection,
            f"SELECT * FROM (VALUES {query_rows}) AS rows(ordinal, cik_padded, name)",
            dataset,
        )
    return catalog.register_cohort(
        cohort_id=cohort_id,
        name=name,
        origin_kind="file_import",
        roster_id=roster_id,
        row_count=len(ciks),
        distinct_cik_count=len(ciks),
        dataset_sha256=file_sha256(dataset),
        dataset_path=paths.relative_path(dataset),
    )


def _workspace(tmp_path: Path) -> tuple[CohortWorkspace, CohortCatalog, CohortPaths]:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    return CohortWorkspace(paths, catalog=catalog), catalog, paths


def test_workspace_uses_catalog_database_for_object_store(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    store = ObjectStore(paths.catalog_file)

    workspace = CohortWorkspace(paths, catalog=catalog, store=store)

    assert workspace.catalog is catalog
    assert workspace.store is store
    assert store.db_path == paths.catalog_file


def test_chained_expressions_advance_aliases_over_immutable_nodes(
    tmp_path: Path,
) -> None:
    workspace, catalog, paths = _workspace(tmp_path)
    _registered(catalog, paths, "first", (("0000000001", "One"),))
    _registered(catalog, paths, "second", (("0000000002", "Two"),))
    workspace.bind_alias("A", "first")
    workspace.bind_alias("B", "second")

    first_node = workspace.let_expression("x", "A + B")
    second_node = workspace.let_expression("x", "x - A")
    stored = workspace.store.get_object(second_node)
    assert stored is not None
    assert stored.object_id == second_node
    assert json.loads(stored.data)["left"] == {
        "node": "object_ref",
        "object_id": first_node,
    }
    assert first_node != second_node
    assert workspace.store.get_alias_target(workspace.session_id, "x") == second_node
    assert [member.cik_padded for member in workspace.peek("x")] == ["0000000002"]


def test_expression_chaining_and_serialization_do_not_write_datasets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, catalog, paths = _workspace(tmp_path)
    first = _registered(catalog, paths, "first", (("0000000001", "One"),))
    _registered(catalog, paths, "second", (("0000000002", "Two"),))
    workspace.bind_alias("A", first.cohort_id)
    workspace.bind_alias("B", "second")

    def reject_materialization(*args, **kwargs):
        raise AssertionError("expression operation materialized a dataset")

    monkeypatch.setattr(
        workspace_module, "copy_query_to_parquet", reject_materialization
    )
    expression_id = workspace.let_expression("x", "A + B")
    serialized = workspace.serialize_expression("x - A")

    assert workspace.store.get_object(expression_id) is not None
    assert serialized == {
        "node": "binary_op",
        "op": "difference",
        "left": {
            "node": "binary_op",
            "op": "union",
            "left": {"node": "cohort_ref", "cohort_identifier": first.cohort_id},
            "right": {
                "node": "cohort_ref",
                "cohort_identifier": catalog.get_cohort("second").cohort_id,
            },
        },
        "right": {"node": "cohort_ref", "cohort_identifier": first.cohort_id},
    }


def test_expression_parser_rejects_python_constructs(tmp_path: Path) -> None:
    workspace, _, _ = _workspace(tmp_path)

    with pytest.raises(ValueError, match="cohort expressions"):
        workspace.let_expression("x", "__import__('os').system('true')")

    assert workspace.list_variables() == []


def test_diff_peek_and_save_operate_on_resolved_expressions(tmp_path: Path) -> None:
    workspace, catalog, paths = _workspace(tmp_path)
    _registered(
        catalog,
        paths,
        "first",
        (("0000000001", "One"), ("0000000002", "Two")),
    )
    _registered(
        catalog,
        paths,
        "second",
        (("0000000002", "Two"), ("0000000003", "Three")),
    )
    workspace.bind_alias("A", "first")
    workspace.bind_alias("B", "second")
    workspace.let_expression("combined", "A + B")

    report = workspace.diff("combined", "A")
    saved = workspace.save("combined", "combined_saved", tags=("derived",))

    assert report.left_total == 3
    assert report.right_total == 2
    assert report.left_only_count == 1
    assert report.sample_left_only == (("0000000003", "Three"),)
    assert [member.cik_padded for member in workspace.peek("combined", limit=2)] == [
        "0000000001",
        "0000000002",
    ]
    assert saved.name == "combined_saved"
    assert saved.origin_kind == "set_operation"
    assert saved.tags == ("derived",)
    assert saved.dataset_path == f"{saved.cohort_id}/ciks.parquet"
    assert saved.row_count == 3
    assert catalog.get_cohort(saved.cohort_id) == saved


def test_workspace_save_holds_publication_lock_through_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, catalog, paths = _workspace(tmp_path)
    _registered(catalog, paths, "first", (("0000000001", "One"),))
    _registered(catalog, paths, "second", (("0000000002", "Two"),))
    workspace.bind_alias("A", "first")
    workspace.bind_alias("B", "second")
    workspace.let_expression("combined", "A + B")
    register = catalog.register_cohort

    def register_under_publication_lock(**kwargs):
        descriptor = os.open(paths.cohorts_root / ".publication.lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        final_dir = paths.cohort_dir(kwargs["cohort_id"])
        assert final_dir.is_dir()
        assert not (final_dir / ".stage.lease").exists()
        return register(**kwargs)

    monkeypatch.setattr(catalog, "register_cohort", register_under_publication_lock)

    saved = workspace.save("combined", "combined_saved")

    assert catalog.get_cohort(saved.cohort_id) == saved


def test_save_rejects_name_conflict_for_existing_cik_identity(tmp_path: Path) -> None:
    workspace, catalog, paths = _workspace(tmp_path)
    _registered(
        catalog,
        paths,
        "official",
        (("0000000001", "Official Name"), ("0000000002", "Two")),
    )
    _registered(
        catalog,
        paths,
        "upload",
        (("0000000001", "Upload Name"), ("0000000003", "Three")),
    )
    workspace.bind_alias("Official", "official")
    workspace.bind_alias("Upload", "upload")

    workspace.let_expression("left_first", "Official + Upload")
    first = workspace.save("left_first", "official_first")
    workspace.let_expression("upload_first", "Upload + Official")

    with pytest.raises(ValueError, match="is immutable"):
        workspace.save("upload_first", "upload_first")
    assert catalog.get_cohort(first.cohort_id) == first


def test_session_alias_lifecycle_and_session_switch(tmp_path: Path) -> None:
    workspace, catalog, paths = _workspace(tmp_path)
    record = _registered(catalog, paths, "first", (("0000000001", "One"),))
    workspace.bind_alias("A", record.cohort_id)

    assert workspace.drop_var("A")
    assert not workspace.drop_var("A")
    workspace.bind_alias("A", record.cohort_id)
    workspace.switch_session("other")
    assert workspace.list_variables() == []
    workspace.bind_alias("B", record.cohort_id)
    workspace.clear()
    assert workspace.session_id == "default"
    assert [variable.name for variable in workspace.list_variables()] == ["A"]
