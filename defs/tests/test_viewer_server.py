import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from viewer_fixtures import (  # noqa: F401 - fixtures registered via import
    artifacts_root,
    base64_id,
    chunk_dataset,
    parquet_dataset,
)

from defs.viewer.server import create_app


@pytest.fixture()
def client(artifacts_root, chunk_dataset, parquet_dataset):
    app = create_app(artifacts_root)
    return TestClient(app), artifacts_root


def test_health_and_listing(client, chunk_dataset, parquet_dataset):
    http, _root = client
    assert http.get("/api/health").json()["status"] == "ok"

    datasets = http.get("/api/datasets").json()
    kinds = {item["relative_path"]: item["kind"] for item in datasets}
    assert kinds[chunk_dataset["relative"].as_posix()] == "partition_chunk"
    assert kinds[parquet_dataset["relative"].as_posix()] == "published_dataset"


def test_rows_and_schema_endpoints(client, chunk_dataset):
    http, _root = client
    dataset_id = base64_id(chunk_dataset["relative"].as_posix())

    schema = http.get(f"/api/datasets/{dataset_id}/schema").json()
    assert {column["name"] for column in schema} == {"cik", "name", "status", "filings"}

    rows = http.get(
        f"/api/datasets/{dataset_id}/rows", params={"limit": 2, "sort": "cik"}
    ).json()
    assert len(rows["items"]) == 2
    assert rows["has_more"] is True
    assert rows["items"][0]["filings"][0]["form"] == "10-K"

    missing = http.get("/api/datasets/does-not-exist/schema")
    assert missing.status_code == 404


def test_sql_endpoint_rejects_writes_with_structured_error(client, chunk_dataset):
    http, _root = client
    dataset_id = base64_id(chunk_dataset["relative"].as_posix())

    ok = http.post(
        f"/api/datasets/{dataset_id}/sql",
        json={"query": "SELECT COUNT(*) AS n FROM dataset"},
    )
    assert ok.status_code == 200
    assert ok.json()["rows"][0]["n"] == 3

    rejected = http.post(
        f"/api/datasets/{dataset_id}/sql", json={"query": "DELETE FROM dataset"}
    )
    assert rejected.status_code == 400
    assert "SELECT" in rejected.json()["detail"] or "read" in rejected.json()["detail"]


def test_documents_endpoint_returns_content(client, artifacts_root):
    plan_relative = "transient/metadata/runs/run-1/plan.json"
    path = artifacts_root / plan_relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"chunks": 5}', encoding="utf-8")

    http, _root = client
    documents = http.get("/api/documents").json()
    assert documents[0]["relative_path"] == plan_relative

    document = http.get(f"/api/documents/{documents[0]['id']}").json()
    assert document["content"] == {"chunks": 5}


def test_listings_carry_revision_field(client, chunk_dataset, parquet_dataset):
    http, _root = client

    datasets = http.get("/api/datasets").json()
    by_path = {item["relative_path"]: item for item in datasets}
    chunk_entry = by_path[chunk_dataset["relative"].as_posix()]
    canonical_entry = by_path[parquet_dataset["relative"].as_posix()]

    assert "revision" in chunk_entry
    assert chunk_entry["revision"].startswith(f"{chunk_entry['size_bytes']}:")
    assert chunk_entry["revision"].split(":")[1].isdigit()
    assert canonical_entry["revision"]

    # Rewriting a backing file must change its revision on the next listing.
    path = chunk_dataset["path"]
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    refreshed = http.get("/api/datasets").json()
    new_entry = next(
        item
        for item in refreshed
        if item["relative_path"] == chunk_dataset["relative"].as_posix()
    )
    assert new_entry["revision"] != chunk_entry["revision"]


def test_sqlite_and_blob_endpoints(client, artifacts_root):
    import sqlite3

    import zstandard as zstd

    db_rel = "manifests/filing_documents/final/partition-00001.sqlite"
    db_path = artifacts_root / db_rel
    db_path.parent.mkdir(parents=True, exist_ok=True)

    html_content = "<html><body><h1>Item 1. Business</h1></body></html>"
    compressed_blob = zstd.ZstdCompressor(level=3).compress(
        html_content.encode("utf-8")
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE filing_documents (accession_number TEXT PRIMARY KEY, cik TEXT, normalized_payload BLOB)"
        )
        conn.execute(
            "INSERT INTO filing_documents VALUES (?, ?, ?)",
            ("0001000001-23-000001", "0001000001", compressed_blob),
        )

    http, _root = client

    datasets = http.get("/api/datasets").json()
    dataset = next(
        d
        for d in datasets
        if "partition-00001.sqlite::filing_documents" in d["relative_path"]
    )
    dataset_id = dataset["id"]

    # Test schema
    schema = http.get(f"/api/datasets/{dataset_id}/schema").json()
    assert {c["name"] for c in schema} == {
        "accession_number",
        "cik",
        "normalized_payload",
    }

    # Test rows
    rows = http.get(f"/api/datasets/{dataset_id}/rows").json()
    assert len(rows["items"]) == 1
    assert rows["items"][0]["normalized_payload"]["__blob__"] is True
    assert rows["items"][0]["normalized_payload"]["is_compressed"] is True

    # Test blob endpoint with primary key
    blob_res = http.get(
        f"/api/datasets/{dataset_id}/blob",
        params={
            "column": "normalized_payload",
            "pk_col": "accession_number",
            "pk_val": "0001000001-23-000001",
        },
    ).json()
    assert blob_res["is_compressed"] is True
    assert blob_res["mime_type"] == "text/html"
    assert blob_res["text"] == html_content
    assert blob_res["decompressed_bytes"] == len(html_content.encode("utf-8"))

    # Test blob endpoint with row_index
    blob_res2 = http.get(
        f"/api/datasets/{dataset_id}/blob",
        params={
            "column": "normalized_payload",
            "row_index": 0,
        },
    ).json()
    assert blob_res2["text"] == html_content

    # Test SQL on SQLite dataset
    sql_res = http.post(
        f"/api/datasets/{dataset_id}/sql",
        json={"query": "SELECT COUNT(*) AS total FROM dataset"},
    ).json()
    assert sql_res["rows"][0]["total"] == 1
