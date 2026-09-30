"""Unit tests for apps.viewer.server.

The HTTP surface is the trust boundary, so the tests here are about what a
caller *cannot* do as much as what it can: no path, no arbitrary column, no
write, no escape from the artifacts root.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from edgar_sec.apps.viewer.server import create_app
from tests.apps.viewer.conftest import build_metadata_snapshot


@pytest.fixture
def client(metadata_tree: Path) -> TestClient:
    return TestClient(create_app(metadata_tree))


def _dataset_id(client: TestClient, kind: str) -> str:
    for item in client.get("/api/datasets").json():
        if item["kind"] == kind:
            return str(item["id"])
    raise AssertionError(f"no {kind} in the listing")


def test_health_reports_the_resolved_root(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["artifacts_root"]


def test_listing_carries_a_revision_for_every_dataset(client: TestClient) -> None:
    items = client.get("/api/datasets").json()
    assert items
    assert all(item["revision"] for item in items)


def test_schema_endpoint_reports_columns(client: TestClient) -> None:
    body = client.get(
        f"/api/datasets/{_dataset_id(client, 'metadata_snapshot')}/schema"
    )
    assert body.status_code == 200
    assert [column["name"] for column in body.json()] == ["cik", "name"]


def test_rows_endpoint_pages(client: TestClient) -> None:
    dataset = _dataset_id(client, "metadata_snapshot")
    body = client.get(
        f"/api/datasets/{dataset}/rows", params={"limit": 2, "sort": "cik"}
    )
    assert body.status_code == 200
    payload = body.json()
    assert len(payload["items"]) == 2
    assert payload["has_more"] is True


def test_rows_endpoint_accepts_json_filters(client: TestClient) -> None:
    dataset = _dataset_id(client, "metadata_snapshot")
    response = client.get(
        f"/api/datasets/{dataset}/rows",
        params={"filters": json.dumps([{"column": "cik", "op": "eq", "value": 1000}])},
    )
    assert [row["cik"] for row in response.json()["items"]] == [1000]


def test_rows_endpoint_rejects_malformed_filters(client: TestClient) -> None:
    dataset = _dataset_id(client, "metadata_snapshot")
    assert (
        client.get(f"/api/datasets/{dataset}/rows", params={"filters": "{"}).status_code
        == 400
    )
    assert (
        client.get(
            f"/api/datasets/{dataset}/rows", params={"filters": "{}"}
        ).status_code
        == 400
    )


def test_rows_endpoint_rejects_an_out_of_range_limit(client: TestClient) -> None:
    dataset = _dataset_id(client, "metadata_snapshot")
    assert (
        client.get(f"/api/datasets/{dataset}/rows", params={"limit": 0}).status_code
        == 422
    )
    assert (
        client.get(f"/api/datasets/{dataset}/rows", params={"limit": 99999}).status_code
        == 422
    )


def test_rows_endpoint_rejects_a_bad_direction(client: TestClient) -> None:
    dataset = _dataset_id(client, "metadata_snapshot")
    response = client.get(f"/api/datasets/{dataset}/rows", params={"dir": "sideways"})
    assert response.status_code == 422


def test_stats_endpoint(client: TestClient) -> None:
    dataset = _dataset_id(client, "metadata_snapshot")
    body = client.get(f"/api/datasets/{dataset}/stats")
    assert body.status_code == 200
    assert all("top_values" in column for column in body.json())


def test_an_unknown_dataset_is_404(client: TestClient) -> None:
    assert client.get("/api/datasets/bm90c2U/rows").status_code == 404


def test_a_traversal_id_is_404_not_a_file_read(client: TestClient) -> None:
    """A forged id cannot reach outside the artifacts root."""
    from edgar_sec.apps.viewer.model import artifact_id

    escaped = artifact_id("../../etc/passwd")
    assert client.get(f"/api/datasets/{escaped}/rows").status_code == 404


def test_sql_endpoint_runs_a_read(client: TestClient) -> None:
    dataset = _dataset_id(client, "metadata_snapshot")
    response = client.post(
        f"/api/datasets/{dataset}/sql",
        json={"query": "SELECT COUNT(*) AS n FROM dataset"},
    )
    assert response.status_code == 200
    assert response.json()["rows"][0]["n"] == 4


def test_sql_endpoint_refuses_a_write_with_a_structured_error(
    client: TestClient,
) -> None:
    dataset = _dataset_id(client, "metadata_snapshot")
    response = client.post(
        f"/api/datasets/{dataset}/sql", json={"query": "DROP TABLE dataset"}
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_sql_endpoint_refuses_table_functions(client: TestClient) -> None:
    dataset = _dataset_id(client, "metadata_snapshot")
    response = client.post(
        f"/api/datasets/{dataset}/sql",
        json={"query": "SELECT * FROM read_parquet('/etc/passwd')"},
    )
    assert response.status_code == 400
    assert "table function" in response.json()["detail"]


def test_sql_endpoint_requires_a_query(client: TestClient) -> None:
    dataset = _dataset_id(client, "metadata_snapshot")
    assert client.post(f"/api/datasets/{dataset}/sql", json={}).status_code == 400


def test_documents_endpoint_returns_content(client: TestClient) -> None:
    documents = client.get("/api/documents").json()
    assert documents
    body = client.get(f"/api/documents/{documents[0]['id']}")
    assert body.status_code == 200
    payload = body.json()
    assert payload["content"]["snapshot_id"] == "snap-meta"
    assert payload["summary"]["id"] == documents[0]["id"]


def test_documents_and_datasets_are_separate_listings(client: TestClient) -> None:
    """A manifest is not a table and must not appear as browsable rows."""
    dataset_ids = {item["id"] for item in client.get("/api/datasets").json()}
    document_ids = {item["id"] for item in client.get("/api/documents").json()}
    assert dataset_ids.isdisjoint(document_ids)


def test_an_empty_root_lists_nothing(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "empty"))
    assert client.get("/api/datasets").json() == []
    assert client.get("/api/documents").json() == []


def test_a_damaged_snapshot_does_not_break_the_listing(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    build_metadata_snapshot(root)
    client = TestClient(create_app(root))
    paths = next(root.rglob("parts/part-00000.parquet"))
    paths.write_bytes(b"corrupted after publication")
    kinds = {item["kind"] for item in client.get("/api/datasets").json()}
    assert "metadata_snapshot" not in kinds
    assert "metadata_cik_index" in kinds


def test_blob_endpoint_reports_a_missing_value(client: TestClient) -> None:
    dataset = _dataset_id(client, "metadata_snapshot")
    response = client.get(
        f"/api/datasets/{dataset}/blob",
        params={"column": "cik", "pk_col": "cik", "pk_val": "nope"},
    )
    assert response.status_code == 400


def test_openapi_schema_builds(client: TestClient) -> None:
    assert client.get("/api/openapi.json").status_code == 200
